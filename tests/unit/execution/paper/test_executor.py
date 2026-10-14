from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quantx.domain.orders import Fill, Order
from quantx.domain.value_objects import InstrumentId
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.paper.broker import PaperBroker, PaperExecutionResult
from quantx.execution.paper.evidence import SimulationEvidence, SimulationEvidenceStatus
from quantx.execution.paper.executor import PaperOrderExecutor
from quantx.execution.paper.fills import MarketSnapshot, SimulatedFill
from quantx.execution.paper.matching import MatchDecision
from quantx.execution.paper.order_types import PaperOrderSpec
from quantx.execution.paper.profile import (
    ExecutionProfile,
    OrderBookLevel,
    OrderBookSnapshot,
    SlippageModel,
)


def make_order(
    order_type=OrderType.MARKET,
    quantity=Decimal("2"),
    time_in_force=TimeInForce.DAY,
) -> Order:
    limit_price = Decimal("100") if order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT} else None
    stop_price = Decimal("100") if order_type in {OrderType.STOP, OrderType.STOP_LIMIT} else None
    return Order(
        client_order_id=uuid4(),
        instrument=InstrumentId("TEST", "BTCUSDT"),
        side=OrderSide.BUY,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        stop_price=stop_price,
        time_in_force=time_in_force,
        status=OrderStatus.CREATED,
    )


def make_executor() -> PaperOrderExecutor:
    profile = ExecutionProfile(
        profile_id="test",
        version="1",
        slippage_model=SlippageModel.NONE,
        fee_rate=Decimal("0.001"),
    )
    return PaperOrderExecutor(PaperBroker(profile), FillAccounting())


class _CountingAccounting(FillAccounting):
    """Accounting spy proving fills reach the ledger exactly once."""

    def __init__(self) -> None:
        super().__init__()
        self.applications: list[Fill] = []

    def apply(self, fill: Fill, *, fee: Decimal = Decimal("0")) -> PositionLedgerEntry:
        self.applications.append(fill)
        return super().apply(fill, fee=fee)


def _ioc_executor() -> tuple[PaperOrderExecutor, _CountingAccounting]:
    accounting = _CountingAccounting()
    profile = ExecutionProfile(
        profile_id="ioc",
        version="1",
        slippage_model=SlippageModel.NONE,
        fee_rate=Decimal("0"),
    )
    return PaperOrderExecutor(PaperBroker(profile), accounting), accounting


def _thin_book() -> OrderBookSnapshot:
    return OrderBookSnapshot(
        bids=(),
        asks=(OrderBookLevel(Decimal("100"), Decimal("1")),),
        observed_at_ns=1_000_000_000,
    )


def test_confirmed_fill_reaches_accounting() -> None:
    order = make_order()
    snapshot = MarketSnapshot(Decimal("99"), Decimal("100"), Decimal("99.5"))
    result = make_executor().execute(
        order,
        snapshot=snapshot,
        submitted_at_ns=1_000_000_000,
        observed_at=datetime.now(UTC),
    )

    assert result.lifecycle_status is OrderStatus.FILLED
    assert result.fill is not None
    assert result.ledger_entry is not None
    assert result.fill.price == Decimal("100")
    assert result.fill.quantity == Decimal("2")


def test_missing_snapshot_becomes_unknown_without_accounting() -> None:
    order = make_order()
    result = make_executor().execute(
        order,
        snapshot=None,
        submitted_at_ns=1_000_000_000,
        observed_at=datetime.now(UTC),
    )

    assert result.lifecycle_status is OrderStatus.UNKNOWN
    assert result.fill is None
    assert result.ledger_entry is None


def test_non_marketable_limit_remains_submitted() -> None:
    order = make_order(OrderType.LIMIT)
    order = Order(
        client_order_id=order.client_order_id,
        instrument=order.instrument,
        side=order.side,
        order_type=order.order_type,
        quantity=order.quantity,
        limit_price=Decimal("99"),
        status=OrderStatus.CREATED,
    )
    snapshot = MarketSnapshot(Decimal("99.5"), Decimal("100"), Decimal("99.7"))
    result = make_executor().execute(
        order,
        snapshot=snapshot,
        submitted_at_ns=1_000_000_000,
        observed_at=datetime.now(UTC),
    )

    assert result.lifecycle_status is OrderStatus.SUBMITTED
    assert result.fill is None
    assert result.ledger_entry is None


class MissingFillTimestampBroker(PaperBroker):
    def execute(
        self,
        order: PaperOrderSpec,
        *,
        snapshot: MarketSnapshot | None,
        submitted_at_ns: int,
        order_book: OrderBookSnapshot | None = None,
    ) -> PaperExecutionResult:
        return PaperExecutionResult(
            evidence=SimulationEvidence(
                SimulationEvidenceStatus.CONFIRMED,
                "test confirmed execution",
                source_timestamp_ns=submitted_at_ns,
            ),
            match=MatchDecision(True, Decimal("100"), "test executable"),
            fill=SimulatedFill(
                price=Decimal("100"),
                quantity=Decimal("2"),
                fee=Decimal("0"),
            ),
            fill_at_ns=None,
        )


class ContradictoryFillBroker(PaperBroker):
    """Broker whose fill flag contradicts the evidenced fill quantity."""

    def __init__(self, profile_id: str, quantity: Decimal, partial: bool) -> None:
        super().__init__(
            ExecutionProfile(
                profile_id=profile_id,
                version="1",
                slippage_model=SlippageModel.NONE,
                fee_rate=Decimal("0"),
            )
        )
        self._quantity = quantity
        self._partial = partial

    def execute(
        self,
        order: PaperOrderSpec,
        *,
        snapshot: MarketSnapshot | None,
        submitted_at_ns: int,
        order_book: OrderBookSnapshot | None = None,
    ) -> PaperExecutionResult:
        return PaperExecutionResult(
            evidence=SimulationEvidence(
                SimulationEvidenceStatus.CONFIRMED,
                "test confirmed execution",
                source_timestamp_ns=submitted_at_ns,
            ),
            match=MatchDecision(True, Decimal("100"), "test executable"),
            fill=SimulatedFill(
                price=Decimal("100"),
                quantity=self._quantity,
                fee=Decimal("0"),
                partial=self._partial,
            ),
            fill_at_ns=submitted_at_ns,
        )


def test_fill_flagged_full_without_full_quantity_is_rejected() -> None:
    executor = PaperOrderExecutor(
        ContradictoryFillBroker("false-full", Decimal("1"), partial=False),
        FillAccounting(),
    )

    with pytest.raises(ValueError, match="full-quantity"):
        executor.execute(
            make_order(),
            snapshot=MarketSnapshot(Decimal("99"), Decimal("100"), Decimal("99.5")),
            submitted_at_ns=1_000_000_000,
            observed_at=datetime.now(UTC),
        )


def test_fill_flagged_partial_with_full_quantity_is_rejected() -> None:
    executor = PaperOrderExecutor(
        ContradictoryFillBroker("false-partial", Decimal("2"), partial=True),
        FillAccounting(),
    )

    with pytest.raises(ValueError, match="partial-quantity"):
        executor.execute(
            make_order(),
            snapshot=MarketSnapshot(Decimal("99"), Decimal("100"), Decimal("99.5")),
            submitted_at_ns=1_000_000_000,
            observed_at=datetime.now(UTC),
        )


def test_ioc_market_full_fill_is_filled_with_single_accounting() -> None:
    executor, accounting = _ioc_executor()
    result = executor.execute(
        make_order(time_in_force=TimeInForce.IOC),
        snapshot=MarketSnapshot(Decimal("99"), Decimal("100"), Decimal("99.5")),
        submitted_at_ns=1_000_000_000,
        observed_at=datetime.now(UTC),
    )

    assert result.lifecycle_status is OrderStatus.FILLED
    assert result.fill is not None
    assert result.fill.quantity == Decimal("2")
    assert result.ledger_entry is not None
    assert len(accounting.applications) == 1
    assert accounting.applications[0] == result.fill


def test_ioc_market_partial_fill_cancels_remainder() -> None:
    executor, accounting = _ioc_executor()
    result = executor.execute(
        make_order(time_in_force=TimeInForce.IOC),
        snapshot=MarketSnapshot(Decimal("99"), Decimal("100"), Decimal("99.5")),
        submitted_at_ns=1_000_000_000,
        observed_at=datetime.now(UTC),
        order_book=_thin_book(),
    )

    assert result.lifecycle_status is OrderStatus.CANCELLED
    assert result.fill is not None
    assert result.fill.quantity == Decimal("1")
    assert result.ledger_entry is not None
    assert len(accounting.applications) == 1
    assert accounting.applications[0].quantity == Decimal("1")


def test_day_market_partial_fill_rests_without_cancelling() -> None:
    result = make_executor().execute(
        make_order(time_in_force=TimeInForce.DAY),
        snapshot=MarketSnapshot(Decimal("99"), Decimal("100"), Decimal("99.5")),
        submitted_at_ns=1_000_000_000,
        observed_at=datetime.now(UTC),
        order_book=_thin_book(),
    )

    assert result.lifecycle_status is OrderStatus.PARTIALLY_FILLED
    assert result.fill is not None
    assert result.fill.quantity == Decimal("1")
    assert result.ledger_entry is not None


def test_ioc_non_marketable_limit_cancels_without_fill_or_accounting() -> None:
    executor, accounting = _ioc_executor()
    order = make_order(OrderType.LIMIT, time_in_force=TimeInForce.IOC)
    order = Order(
        client_order_id=order.client_order_id,
        instrument=order.instrument,
        side=order.side,
        order_type=order.order_type,
        quantity=order.quantity,
        limit_price=Decimal("99"),
        time_in_force=TimeInForce.IOC,
        status=OrderStatus.CREATED,
    )
    result = executor.execute(
        order,
        snapshot=MarketSnapshot(Decimal("99.5"), Decimal("100"), Decimal("99.7")),
        submitted_at_ns=1_000_000_000,
        observed_at=datetime.now(UTC),
    )

    assert result.lifecycle_status is OrderStatus.CANCELLED
    assert result.fill is None
    assert result.ledger_entry is None
    assert accounting.applications == []


def test_ioc_missing_snapshot_stays_unknown_without_cancellation() -> None:
    executor, accounting = _ioc_executor()
    result = executor.execute(
        make_order(time_in_force=TimeInForce.IOC),
        snapshot=None,
        submitted_at_ns=1_000_000_000,
        observed_at=datetime.now(UTC),
    )

    assert result.lifecycle_status is OrderStatus.UNKNOWN
    assert result.fill is None
    assert result.ledger_entry is None
    assert accounting.applications == []


@pytest.mark.parametrize("time_in_force", [TimeInForce.FOK, TimeInForce.GTC])
def test_unsupported_time_in_force_is_rejected_explicitly(
    time_in_force: TimeInForce,
) -> None:
    with pytest.raises(ValueError, match="not a valid PaperTimeInForce"):
        make_executor().execute(
            make_order(time_in_force=time_in_force),
            snapshot=MarketSnapshot(Decimal("99"), Decimal("100"), Decimal("99.5")),
            submitted_at_ns=1_000_000_000,
            observed_at=datetime.now(UTC),
        )


def test_fill_requires_timestamp_when_present() -> None:
    order = make_order()
    executor = PaperOrderExecutor(
        MissingFillTimestampBroker(
            ExecutionProfile(
                profile_id="missing-timestamp",
                version="1",
                slippage_model=SlippageModel.NONE,
                fee_rate=Decimal("0"),
            )
        ),
        FillAccounting(),
    )

    try:
        executor.execute(
            order,
            snapshot=MarketSnapshot(Decimal("99"), Decimal("100"), Decimal("99.5")),
            submitted_at_ns=1_000_000_000,
            observed_at=datetime.now(UTC),
        )
    except ValueError as exc:
        assert "fill_at_ns is required" in str(exc)
    else:
        raise AssertionError("missing fill timestamp was accepted")
