from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.enums import AssetClass, OrderSide, OrderStatus
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.instruments import Instrument, MarketContext, MarketFamily, MarketRegion
from quantx.domain.market_data import Quote
from quantx.domain.orders import Fill
from quantx.domain.value_objects import InstrumentId, Money
from quantx.execution.accounting import FillAccounting
from quantx.execution.historical_account_state import (
    AccountStateCompleteness,
    HistoricalAccountStateTracker,
)
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt

INSTRUMENT = InstrumentId("NSE", "TCS")
T0 = datetime(2026, 1, 5, 9, 15, tzinfo=UTC)
T1 = datetime(2026, 1, 5, 9, 16, tzinfo=UTC)


def _instrument(multiplier: str = "1") -> Instrument:
    return Instrument(
        INSTRUMENT,
        "TCS",
        AssetClass.EQUITY,
        MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
        multiplier=Decimal(multiplier),
    )


def _registry(multiplier: str = "1") -> InMemoryInstrumentRegistry:
    return InMemoryInstrumentRegistry((_instrument(multiplier),))


def _financial_state(cash: str = "1000") -> AccountFinancialState:
    return AccountFinancialState(
        capital_source=CapitalSourceType.BACKTEST_CONFIGURED,
        cash_balance=Money(Decimal(cash), "INR"),
        available_cash=Money(Decimal(cash), "INR"),
        blocked_cash=Money.zero("INR"),
        margin_used=Money.zero("INR"),
        margin_available=Money(Decimal(cash), "INR"),
        buying_power=Money(Decimal(cash), "INR"),
    )


def _tracker(multiplier: str = "1", cash: str = "1000"):
    accounting = FillAccounting()
    tracker = HistoricalAccountStateTracker(
        _financial_state(cash),
        accounting=accounting,
        instrument_registry=_registry(multiplier),
    )
    return tracker, accounting


def _receipt(
    side: OrderSide,
    quantity: str,
    price: str,
    fee: str = "0",
    *,
    executed_at: datetime = T0,
) -> ExecutionReceipt:
    fill = Fill(
        client_order_id=uuid4(),
        instrument=INSTRUMENT,
        side=side,
        quantity=Decimal(quantity),
        price=Decimal(price),
        filled_at=executed_at,
    )
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=fill.client_order_id,
        outcome=ExecutionOutcome.FILLED,
        order_status=OrderStatus.FILLED,
        executed_at=executed_at,
        fills=(fill,),
        simulated=True,
        source="test",
        fee=Decimal(fee),
        order_id=fill.client_order_id,
        order_quantity=Decimal(quantity),
    )


def _snapshot(
    timestamp: datetime = T0,
    *,
    price: str | None = "100",
    last: str | None = None,
    bid: str | None = None,
    ask: str | None = None,
) -> Quote:
    if price is not None:
        observed_last = Decimal(price)
    elif last is not None:
        observed_last = Decimal(last)
    else:
        observed_last = None

    return Quote(
        instrument=INSTRUMENT,
        timestamp=timestamp,
        bid=None if bid is None else Decimal(bid),
        ask=None if ask is None else Decimal(ask),
        last=observed_last,
    )


def test_tracker_derives_complete_state_for_long_position() -> None:
    tracker, _ = _tracker()

    receipt = _receipt(OrderSide.BUY, "2", "100", "1")
    result = tracker.record(receipt, snapshot=_snapshot(price="110"))

    assert result.completeness is AccountStateCompleteness.COMPLETE
    assert result.cash == Money(Decimal("799"), "INR")
    assert result.market_value == Money(Decimal("220"), "INR")
    assert result.equity == Money(Decimal("1019"), "INR")
    assert result.realized_pnl == Money.zero("INR")
    assert result.unrealized_pnl == Money(Decimal("20"), "INR")
    assert result.gross_exposure == Money(Decimal("220"), "INR")
    assert result.fees == Money(Decimal("1"), "INR")
    assert result.net_pnl == Money(Decimal("19"), "INR")
    assert result.positions[0].quantity == Decimal("2")
    evidence = result.valuation_evidence[0]
    assert evidence.instrument_id == str(INSTRUMENT)
    assert evidence.mark_price == Decimal("110")
    assert evidence.source == "historical-replay-last"
    assert evidence.observed_at == T0
    assert evidence.selected_at == T0
    assert evidence.unavailable is False


def test_tracker_handles_realized_pnl_and_fees_on_partial_close() -> None:
    tracker, _ = _tracker()

    opening = _receipt(OrderSide.BUY, "2", "100", "1", executed_at=T0)
    tracker.record(opening, snapshot=_snapshot(T0, price="100"))

    closing = _receipt(OrderSide.SELL, "1", "110", "1", executed_at=T1)
    result = tracker.record(closing, snapshot=_snapshot(T1, price="110"))

    assert result.cash == Money(Decimal("908"), "INR")
    assert result.market_value == Money(Decimal("110"), "INR")
    assert result.equity == Money(Decimal("1018"), "INR")
    assert result.realized_pnl == Money(Decimal("10"), "INR")
    assert result.unrealized_pnl == Money(Decimal("10"), "INR")
    evidence = result.valuation_evidence[0]
    assert evidence.mark_price == Decimal("110")
    assert evidence.source == "historical-replay-last"
    assert evidence.observed_at == T1
    assert evidence.selected_at == T1
    assert evidence.unavailable is False
    assert result.fees == Money(Decimal("2"), "INR")
    assert result.net_pnl == Money(Decimal("18"), "INR")


def test_tracker_uses_signed_market_value_for_short_positions() -> None:
    tracker, _ = _tracker()

    receipt = _receipt(OrderSide.SELL, "2", "100")
    result = tracker.record(receipt, snapshot=_snapshot(price="100"))

    assert result.cash == Money(Decimal("1200"), "INR")
    assert result.market_value == Money(Decimal("-200"), "INR")
    assert result.equity == Money(Decimal("1000"), "INR")
    assert result.gross_exposure == Money(Decimal("200"), "INR")
    evidence = result.valuation_evidence[0]
    assert evidence.mark_price == Decimal("100")
    assert evidence.source == "historical-replay-last"
    assert evidence.observed_at == T0
    assert evidence.selected_at == T0
    assert evidence.unavailable is False


def test_tracker_honors_instrument_multiplier() -> None:
    tracker, _ = _tracker(multiplier="50", cash="100000")

    receipt = _receipt(OrderSide.BUY, "2", "1000")
    result = tracker.record(receipt, snapshot=_snapshot(price="1100"))

    assert result.cash == Money(Decimal("0"), "INR")
    assert result.market_value == Money(Decimal("110000"), "INR")
    assert result.equity == Money(Decimal("110000"), "INR")


def test_tracker_missing_price_is_incomplete_without_fabrication() -> None:
    tracker, _ = _tracker()

    receipt = _receipt(OrderSide.BUY, "1", "100")
    result = tracker.record(receipt, snapshot=_snapshot(price=None))

    assert result.completeness is AccountStateCompleteness.INCOMPLETE
    assert result.cash == Money(Decimal("900"), "INR")
    assert result.market_value is None
    assert result.equity is None
    assert result.unrealized_pnl is None
    assert result.gross_exposure is None
    assert result.unavailable_instruments == (str(INSTRUMENT),)
    assert result.issue is not None
    evidence = result.valuation_evidence[0]
    assert evidence.instrument_id == str(INSTRUMENT)
    assert evidence.mark_price is None
    assert evidence.source == "historical-replay-no-price"
    assert evidence.observed_at == T0
    assert evidence.selected_at == T0
    assert evidence.unavailable is True
    assert evidence.reason == "explicit mark has no usable price or observation time"


def test_tracker_rejects_live_capital_source() -> None:
    live = AccountFinancialState(
        capital_source=CapitalSourceType.LIVE_BROKER,
        cash_balance=Money(Decimal("1000"), "INR"),
        available_cash=Money(Decimal("1000"), "INR"),
        blocked_cash=Money.zero("INR"),
        margin_used=Money.zero("INR"),
        margin_available=Money(Decimal("1000"), "INR"),
        buying_power=Money(Decimal("1000"), "INR"),
    )

    with pytest.raises(ValueError, match="configured paper/backtest capital"):
        HistoricalAccountStateTracker(
            live,
            accounting=FillAccounting(),
            instrument_registry=_registry(),
        )


def test_tracker_consumes_first_class_charge_breakdown_total() -> None:
    from dataclasses import replace

    from quantx.execution.charges import ChargeBreakdown, ChargeComponent

    tracker, _ = _tracker()
    receipt = replace(
        _receipt(OrderSide.BUY, "1", "100", "1"),
        charges=ChargeBreakdown(
            currency="INR",
            components=(ChargeComponent("simulated_brokerage", Decimal("1")),),
            model_id="test.paper.charges",
            model_version="1",
            provenance=("test_configuration",),
        ),
    )

    result = tracker.record(receipt, snapshot=_snapshot(price="100"))

    assert result.fees == Money(Decimal("1"), "INR")
    assert result.cash == Money(Decimal("899"), "INR")


def test_tracker_record_is_idempotent_by_receipt_identity() -> None:
    tracker, _ = _tracker()

    receipt = _receipt(OrderSide.BUY, "1", "100", "1")
    first = tracker.record(receipt, snapshot=_snapshot(price="100"))
    second = tracker.record(receipt, snapshot=_snapshot(price="105"))

    assert second == first
    assert second.cash == Money(Decimal("899"), "INR")


def test_tracker_time_indexed_snapshot_rejects_stale_mark_reuse() -> None:
    tracker, _ = _tracker()

    opening = _receipt(OrderSide.BUY, "1", "100", executed_at=T0)
    tracker.record(opening, snapshot=_snapshot(T0, price="100"))

    stale = tracker.snapshot_at(
        T1,
        require_current_marks=True,
    )

    assert stale.completeness is AccountStateCompleteness.INCOMPLETE
    assert stale.market_value is None
    assert stale.equity is None
    assert stale.unrealized_pnl is None
    assert stale.gross_exposure is None
    assert stale.unavailable_instruments == (str(INSTRUMENT),)
    stale_evidence = stale.valuation_evidence[0]
    assert stale_evidence.mark_price == Decimal("100")
    assert stale_evidence.observed_at == T0
    assert stale_evidence.selected_at == T1
    assert stale_evidence.unavailable is True
    assert stale_evidence.reason == "explicit mark is stale for exact-current sampling"


def test_tracker_time_indexed_snapshot_uses_exact_current_mark() -> None:
    tracker, _ = _tracker()

    opening = _receipt(OrderSide.BUY, "1", "100", executed_at=T0)
    tracker.record(opening, snapshot=_snapshot(T0, price="100"))

    current = _snapshot(T1, price="110")
    tracker.observe_mark(current)
    result = tracker.snapshot_at(T1, require_current_marks=True)

    assert result.completeness is AccountStateCompleteness.COMPLETE
    assert result.timestamp == T1
    assert result.market_value == Money(Decimal("110"), "INR")
    assert result.equity == Money(Decimal("1010"), "INR")
    assert result.unrealized_pnl == Money(Decimal("10"), "INR")


def test_tracker_records_c4_as_of_mark_selection() -> None:
    tracker, _ = _tracker()

    receipt = _receipt(OrderSide.BUY, "1", "100", executed_at=T1)
    result = tracker.record(receipt, snapshot=_snapshot(T0, price="105"))

    evidence = result.valuation_evidence[0]
    assert evidence.unavailable is False
    assert evidence.mark_price == Decimal("105")
    assert evidence.source == "historical-replay-last"
    assert evidence.observed_at == T0
    assert evidence.selected_at == T1


def test_tracker_records_future_mark_as_unavailable_evidence() -> None:
    tracker, _ = _tracker()

    opening = _receipt(OrderSide.BUY, "1", "100", executed_at=T0)
    tracker.record(opening, snapshot=_snapshot(T0, price="100"))
    tracker.observe_mark(_snapshot(T1, price="110"))

    result = tracker.snapshot_at(T0)

    assert result.completeness is AccountStateCompleteness.INCOMPLETE
    evidence = result.valuation_evidence[0]
    assert evidence.instrument_id == str(INSTRUMENT)
    assert evidence.mark_price == Decimal("110")
    assert evidence.source == "historical-replay-last"
    assert evidence.observed_at == T1
    assert evidence.selected_at == T0
    assert evidence.unavailable is True
    assert evidence.reason == "explicit mark is observed after snapshot timestamp"
