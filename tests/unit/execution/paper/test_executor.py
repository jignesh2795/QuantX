from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from quantx.domain.enums import OrderSide, OrderStatus, OrderType
from quantx.domain.instruments import Instrument
from quantx.domain.orders import Order
from quantx.execution.accounting import FillAccounting
from quantx.execution.order_lifecycle import OrderLifecycleStatus
from quantx.execution.paper.broker import PaperBroker
from quantx.execution.paper.evidence import SimulationEvidenceStatus
from quantx.execution.paper.executor import PaperOrderExecutor
from quantx.execution.paper.fills import MarketSnapshot
from quantx.execution.paper.profile import ExecutionProfile, SlippageModel


def make_order(order_type=OrderType.MARKET, quantity=Decimal("2")) -> Order:
    return Order(
        client_order_id=uuid4(),
        instrument=Instrument(symbol="BTCUSDT", venue="TEST"),
        side=OrderSide.BUY,
        order_type=order_type,
        quantity=quantity,
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


def test_confirmed_fill_reaches_accounting() -> None:
    order = make_order()
    snapshot = MarketSnapshot(Decimal("99"), Decimal("100"), Decimal("99.5"))
    result = make_executor().execute(
        order,
        snapshot=snapshot,
        submitted_at_ns=1_000_000_000,
        observed_at=datetime.now(timezone.utc),
    )

    assert result.lifecycle_status is OrderLifecycleStatus.FILLED
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
        observed_at=datetime.now(timezone.utc),
    )

    assert result.lifecycle_status is OrderLifecycleStatus.UNKNOWN
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
        observed_at=datetime.now(timezone.utc),
    )

    assert result.lifecycle_status is OrderLifecycleStatus.SUBMITTED
    assert result.fill is None
    assert result.ledger_entry is None
