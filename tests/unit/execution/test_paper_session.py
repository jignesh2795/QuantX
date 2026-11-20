from datetime import UTC, datetime
from decimal import Decimal

from quantx.domain.accounts import AccountId
from quantx.domain.clock import FixedClock
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderStatus, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Fill
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import Money
from quantx.execution.accounting import FillAccounting
from quantx.execution.paper import PaperExecutionEngine, PaperSimulationProfile, QuoteSnapshot
from quantx.execution.paper_session import PaperSession
from quantx.markets import default_market_registry
from tests.unit._execution_request_proofs import approved_request


def _instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    return Instrument(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        market=market,
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def _request() -> ApprovedExecutionRequest:
    market = _instrument().market
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )
    intent = TradeIntent(
        instrument=_instrument().instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        execution_context=context,
    )
    from quantx.domain.execution_request import build_order_from_intent

    order = build_order_from_intent(intent)
    return approved_request(order, context, RiskResult(RiskDecision.APPROVE, "approved"))


def test_execute_account_and_value_uses_observed_mark() -> None:
    engine = PaperExecutionEngine(
        market_registry=default_market_registry(),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    instrument = _instrument()
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
    )
    result = session.execute_and_value(
        _request(),
        snapshot=QuoteSnapshot(
            instrument=instrument.instrument_id,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Decimal("99"),
            ask=Decimal("100"),
            last=Decimal("100"),
        ),
        cash=Money(Decimal("5000"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
    )
    assert result.accounting_entry.quantity == Decimal("10")
    assert result.valuation.completeness == "COMPLETE"
    assert result.valuation.snapshot.unrealized_pnl.amount == Decimal("0")


def test_idempotent_receipt_does_not_double_apply_position_or_cash() -> None:
    engine = PaperExecutionEngine(
        market_registry=default_market_registry(),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        profile=PaperSimulationProfile(fee_bps=Decimal("10")),
    )
    instrument = _instrument()
    accounting = FillAccounting()
    cash_ledger = __import__("quantx.execution.cash_ledger", fromlist=["CashLedger"]).CashLedger(
        Money(Decimal("5000"), "INR")
    )
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
        accounting=accounting,
        cash_ledger=cash_ledger,
    )
    request = _request()
    snapshot = QuoteSnapshot(
        instrument=instrument.instrument_id,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )

    first = session.execute_and_value(request, snapshot=snapshot)
    second = session.execute_and_value(request, snapshot=snapshot)

    assert first.execution == second.execution
    assert second.accounting_entry.quantity == Decimal("10")
    assert second.accounting_entry.fees == Decimal("1")
    assert second.cash.amount == Decimal("3999")
    assert accounting.snapshot() == (second.accounting_entry,)
    assert cash_ledger.entries() == (first.cash_entries[0],)


def test_receipt_fee_flows_into_accounting_by_default() -> None:
    from quantx.execution.paper import PaperSimulationProfile

    engine = PaperExecutionEngine(
        market_registry=default_market_registry(),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        profile=PaperSimulationProfile(fee_bps=Decimal("10")),
    )
    instrument = _instrument()
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
    )

    result = session.execute_and_value(
        _request(),
        snapshot=QuoteSnapshot(
            instrument=instrument.instrument_id,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            bid=Decimal("99"),
            ask=Decimal("100"),
            last=Decimal("100"),
        ),
        cash=Money(Decimal("5000"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
    )

    assert result.execution.fee == Decimal("1.00")
    assert result.accounting_entry.fees == Decimal("1.00")


def test_missing_mark_produces_incomplete_valuation() -> None:
    engine = PaperExecutionEngine(
        market_registry=default_market_registry(),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    instrument = _instrument()
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
    )
    result = session.execute_and_value(
        _request(),
        snapshot=QuoteSnapshot(
            instrument=instrument.instrument_id,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            ask=Decimal("100"),
        ),
        cash=Money(Decimal("5000"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
    )
    assert result.valuation.completeness == "INCOMPLETE"
    assert result.valuation.unavailable_instruments


def test_partial_continuation_reuses_account_pipeline_and_post_trade_risk() -> None:
    from quantx.domain.orders import Fill
    from quantx.execution.accounting import FillAccounting
    from quantx.execution.paper_engine import PaperSimulationProfile
    from quantx.execution.post_trade_enforcement import PostTradeRiskEnforcer
    from quantx.execution.post_trade_risk import PostTradeRiskLimits
    from quantx.execution.receipts.lifecycle import ExecutionLifecycle
    from quantx.execution.trading_gate import TradingGate

    instrument = _instrument()
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    engine = PaperExecutionEngine(
        market_registry=default_market_registry(),
        clock=clock,
        profile=PaperSimulationProfile(partial_fill_ratio=Decimal("1"), fee_bps=Decimal("10")),
    )
    accounting = FillAccounting()
    accounting.apply(
        Fill(
            client_order_id=_request().order.client_order_id,
            instrument=instrument.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("4"),
            price=Decimal("100"),
            filled_at=clock.now(),
        )
    )
    gate = TradingGate()
    enforcer = PostTradeRiskEnforcer(
        limits=PostTradeRiskLimits(max_daily_loss=Money(Decimal("0"), "INR")),
        trading_gate=gate,
    )
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
        accounting=accounting,
        initial_cash=Money(Decimal("2000"), "INR"),
        post_trade_risk=enforcer,
    )
    request = _request()
    lifecycle = ExecutionLifecycle(
        request.order.client_order_id,
        Decimal("10"),
        Decimal("4"),
        OrderStatus.PARTIALLY_FILLED,
    )

    result = session.continue_partial(
        request,
        lifecycle,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh continuation approval"),
        snapshot=QuoteSnapshot(
            instrument=instrument.instrument_id,
            timestamp=clock.now(),
            bid=Decimal("99"),
            ask=Decimal("100"),
            last=Decimal("100"),
        ),
    )

    assert result.execution.filled_quantity == Decimal("6")
    assert result.accounting_entry.quantity == Decimal("10")
    assert result.financial_state is not None
    assert result.risk_enforcement is not None
    assert result.risk_enforcement.allowed is False
    assert "daily loss" in result.risk_enforcement.reasons[0]
    assert gate.allow() is False


def test_partial_continuation_recalculates_position_margin_for_full_resulting_position() -> None:
    from quantx.execution.accounting import FillAccounting
    from quantx.execution.margin_ledger import MarginLedger
    from quantx.execution.margin_policy import FixedPerUnitMarginPolicy
    from quantx.execution.post_trade_enforcement import PostTradeRiskEnforcer
    from quantx.execution.post_trade_risk import PostTradeRiskLimits
    from quantx.execution.receipts.lifecycle import ExecutionLifecycle
    from quantx.execution.trading_gate import TradingGate

    instrument = _instrument()
    request = _request()
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    engine = PaperExecutionEngine(
        market_registry=default_market_registry(),
        clock=clock,
        profile=PaperSimulationProfile(partial_fill_ratio=Decimal("1")),
    )
    accounting = FillAccounting()
    accounting.apply(
        Fill(
            client_order_id=request.order.client_order_id,
            instrument=instrument.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("4"),
            price=Decimal("100"),
            filled_at=clock.now(),
        )
    )
    margin = MarginLedger(Decimal("100"))
    margin.reserve(
        request.order.client_order_id,
        Decimal("40"),
        instrument=instrument.instrument_id,
        quantity=Decimal("4"),
    )
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
        accounting=accounting,
        initial_cash=Money(Decimal("2000"), "INR"),
        margin_ledger=margin,
        position_margin_policy=FixedPerUnitMarginPolicy(Decimal("10")),
        post_trade_risk=PostTradeRiskEnforcer(
            limits=PostTradeRiskLimits(
                max_position_exposure=Money(Decimal("2000"), "INR"),
            ),
            trading_gate=TradingGate(),
        ),
    )

    result = session.continue_partial(
        request,
        ExecutionLifecycle(
            request.order.client_order_id,
            Decimal("10"),
            Decimal("4"),
            OrderStatus.PARTIALLY_FILLED,
        ),
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh continuation approval"),
        snapshot=QuoteSnapshot(
            instrument=instrument.instrument_id,
            timestamp=clock.now(),
            bid=Decimal("99"),
            ask=Decimal("100"),
            last=Decimal("100"),
        ),
    )

    assert result.accounting_entry.quantity == Decimal("10")
    assert session.margin_state is not None
    assert session.margin_state.used == Decimal("100")
    assert session.margin_state.available == Decimal("0")


def test_partial_continuation_is_blocked_before_executor_on_projected_position_exposure() -> None:
    from quantx.execution.post_trade_enforcement import PostTradeRiskEnforcer
    from quantx.execution.post_trade_risk import PostTradeRiskLimits
    from quantx.execution.receipts.lifecycle import ExecutionLifecycle
    from quantx.execution.trading_gate import TradingGate

    instrument = _instrument()
    request = _request()
    clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    engine = PaperExecutionEngine(
        market_registry=default_market_registry(),
        clock=clock,
        profile=PaperSimulationProfile(partial_fill_ratio=Decimal("1")),
    )
    accounting = FillAccounting()
    accounting.apply(
        Fill(
            client_order_id=request.order.client_order_id,
            instrument=instrument.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("4"),
            price=Decimal("100"),
            filled_at=clock.now(),
        )
    )
    gate = TradingGate()
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
        accounting=accounting,
        initial_cash=Money(Decimal("2000"), "INR"),
        post_trade_risk=PostTradeRiskEnforcer(
            limits=PostTradeRiskLimits(max_position_exposure=Money(Decimal("500"), "INR")),
            trading_gate=gate,
        ),
    )

    result_before = accounting.get(instrument.instrument_id)
    assert result_before is not None
    try:
        session.continue_partial(
            request,
            ExecutionLifecycle(
                request.order.client_order_id,
                Decimal("10"),
                Decimal("4"),
                OrderStatus.PARTIALLY_FILLED,
            ),
            risk_result=RiskResult(RiskDecision.APPROVE, "fresh continuation approval"),
            snapshot=QuoteSnapshot(
                instrument=instrument.instrument_id,
                timestamp=clock.now(),
                bid=Decimal("99"),
                ask=Decimal("100"),
                last=Decimal("100"),
            ),
        )
    except ValueError as exc:
        assert "single-position exposure" in str(exc)
    else:
        raise AssertionError("projected exposure should block continuation")

    result_after = accounting.get(instrument.instrument_id)
    assert result_after == result_before


def test_paper_session_applies_each_rounded_per_fill_charge_without_equal_split() -> None:
    from quantx.execution.charges import ChargeBreakdown, ChargeComponent
    from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt

    instrument = _instrument()
    request = _request()
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    fills = (
        Fill(
            client_order_id=request.order.client_order_id,
            instrument=instrument.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("5"),
            price=Decimal("100"),
            filled_at=timestamp,
        ),
        Fill(
            client_order_id=request.order.client_order_id,
            instrument=instrument.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("5"),
            price=Decimal("100"),
            filled_at=timestamp,
        ),
    )
    per_fill = (
        ChargeBreakdown(
            currency="INR",
            components=(ChargeComponent("brokerage", Decimal("0.005")),),
            model_id="schedule.test",
            model_version="1",
            rounded_total=Decimal("0.00"),
        ),
        ChargeBreakdown(
            currency="INR",
            components=(ChargeComponent("brokerage", Decimal("0.015")),),
            model_id="schedule.test",
            model_version="1",
            rounded_total=Decimal("0.02"),
        ),
    )
    receipt = ExecutionReceipt(
        request_id=__import__("uuid").uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.FILLED,
        order_status=OrderStatus.FILLED,
        executed_at=timestamp,
        fills=fills,
        fee=Decimal("0.02"),
        per_fill_charges=per_fill,
        order_quantity=Decimal("10"),
    )

    class _ReceiptAdapter:
        def execute(self, request, *, snapshot):
            return receipt

    engine = PaperExecutionEngine(
        market_registry=default_market_registry(),
        clock=FixedClock(timestamp),
    )
    accounting = FillAccounting()
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
        accounting=accounting,
        initial_cash=Money(Decimal("5000"), "INR"),
    )
    snapshot = QuoteSnapshot(
        instrument=instrument.instrument_id,
        timestamp=timestamp,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )

    result = session.execute_and_value(
        request,
        snapshot=snapshot,
        execution_adapter=_ReceiptAdapter(),
    )

    assert result.accounting_entry.fees == Decimal("0.02")
    assert tuple(entry.fee.amount for entry in result.cash_entries) == (
        Decimal("0.00"),
        Decimal("0.02"),
    )
    assert result.cash.amount == Decimal("3999.98")


def test_paper_session_rejects_ambiguous_multi_fill_aggregate_fee_before_accounting() -> None:
    from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt

    instrument = _instrument()
    request = _request()
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    fills = tuple(
        Fill(
            client_order_id=request.order.client_order_id,
            instrument=instrument.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("5"),
            price=Decimal("100"),
            filled_at=timestamp,
        )
        for _ in range(2)
    )
    receipt = ExecutionReceipt(
        request_id=__import__("uuid").uuid4(),
        client_order_id=request.order.client_order_id,
        outcome=ExecutionOutcome.FILLED,
        order_status=OrderStatus.FILLED,
        executed_at=timestamp,
        fills=fills,
        fee=Decimal("2"),
        order_quantity=Decimal("10"),
    )

    class _ReceiptAdapter:
        def execute(self, request, *, snapshot):
            return receipt

    engine = PaperExecutionEngine(
        market_registry=default_market_registry(),
        clock=FixedClock(timestamp),
    )
    accounting = FillAccounting()
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
        accounting=accounting,
        initial_cash=Money(Decimal("5000"), "INR"),
    )
    snapshot = QuoteSnapshot(
        instrument=instrument.instrument_id,
        timestamp=timestamp,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )

    import pytest

    with pytest.raises(ValueError, match="cannot be allocated across multiple fills"):
        session.execute_and_value(
            request,
            snapshot=snapshot,
            execution_adapter=_ReceiptAdapter(),
        )
    assert accounting.snapshot() == ()


def test_cost_schedule_currency_mismatch_is_rejected_before_idempotency_and_retryable() -> None:
    import pytest

    from quantx.execution.cash_ledger import CashLedger
    from quantx.execution.charges import (
        ChargeBase,
        CostLine,
        CostSchedule,
        CostScheduleChargeModel,
    )
    from quantx.execution.idempotency import InMemoryIdempotencyStore, request_fingerprint

    def _schedule(currency: str) -> CostScheduleChargeModel:
        return CostScheduleChargeModel(
            CostSchedule(
                lines=(CostLine("brokerage", ChargeBase.ORDER, Decimal("1")),),
                currency=currency,
                digits=2,
                source="caller-supplied-test",
            )
        )

    instrument = _instrument()
    request = _request()
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    idempotency = InMemoryIdempotencyStore()
    engine = PaperExecutionEngine(
        market_registry=default_market_registry(),
        clock=FixedClock(timestamp),
        profile=PaperSimulationProfile(charge_model=_schedule("USD")),
        idempotency_store=idempotency,
    )
    accounting = FillAccounting()
    cash_ledger = CashLedger(Money(Decimal("5000"), "INR"))
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
        accounting=accounting,
        cash_ledger=cash_ledger,
    )
    snapshot = QuoteSnapshot(
        instrument=instrument.instrument_id,
        timestamp=timestamp,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )

    with pytest.raises(ValueError, match="per-fill charge currency does not match"):
        session.execute_and_value(request, snapshot=snapshot)

    decision = idempotency.check(
        request.order.client_order_id,
        request_fingerprint(request),
    )
    assert decision.existing_receipt_id is None
    assert not decision.reservation_pending
    assert engine.receipt_for(request.order.client_order_id) is None
    assert engine.events() == ()
    assert accounting.snapshot() == ()
    assert cash_ledger.balance == Money(Decimal("5000"), "INR")
    assert cash_ledger.entries() == ()

    # Correcting only the schedule configuration must allow the same request
    # and client-order id to execute because the failed preflight reserved nothing.
    engine._profile = PaperSimulationProfile(charge_model=_schedule("INR"))
    result = session.execute_and_value(request, snapshot=snapshot)

    assert result.execution.per_fill_charges[0].currency == "INR"
    assert result.execution.fee == Decimal("1.00")
    assert result.accounting_entry.fees == Decimal("1.00")
    assert result.cash == Money(Decimal("3999.00"), "INR")
    assert cash_ledger.balance == Money(Decimal("3999.00"), "INR")
    assert len(cash_ledger.entries()) == 1
    assert len(engine.events()) == 2
    completed = idempotency.check(
        request.order.client_order_id,
        request_fingerprint(request),
    )
    assert completed.existing_receipt_id == result.execution.receipt_id
    assert not completed.reservation_pending


def test_cost_schedule_currency_preflight_rejects_instrument_account_mismatch() -> None:
    import pytest

    from quantx.execution.cash_ledger import CashLedger
    from quantx.execution.charges import (
        ChargeBase,
        CostLine,
        CostSchedule,
        CostScheduleChargeModel,
    )
    from quantx.execution.idempotency import InMemoryIdempotencyStore, request_fingerprint

    instrument = _instrument()
    request = _request()
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    idempotency = InMemoryIdempotencyStore()
    schedule = CostScheduleChargeModel(
        CostSchedule(
            lines=(CostLine("brokerage", ChargeBase.ORDER, Decimal("1")),),
            currency="INR",
            digits=2,
            source="caller-supplied-test",
        )
    )
    engine = PaperExecutionEngine(
        market_registry=default_market_registry(),
        clock=FixedClock(timestamp),
        profile=PaperSimulationProfile(charge_model=schedule),
        idempotency_store=idempotency,
    )
    accounting = FillAccounting()
    cash_ledger = CashLedger(Money(Decimal("5000"), "USD"))
    session = PaperSession(
        executor=engine,
        instrument_registry=InMemoryInstrumentRegistry((instrument,)),
        accounting=accounting,
        cash_ledger=cash_ledger,
    )
    snapshot = QuoteSnapshot(
        instrument=instrument.instrument_id,
        timestamp=timestamp,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )

    with pytest.raises(ValueError, match="scheduled charge currency must match"):
        session.execute_and_value(request, snapshot=snapshot)

    decision = idempotency.check(
        request.order.client_order_id,
        request_fingerprint(request),
    )
    assert decision.existing_receipt_id is None
    assert not decision.reservation_pending
    assert engine.receipt_for(request.order.client_order_id) is None
    assert engine.events() == ()
    assert accounting.snapshot() == ()
    assert cash_ledger.balance == Money(Decimal("5000"), "USD")
    assert cash_ledger.entries() == ()
