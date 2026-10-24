"""Composition-root slice A: the LIVE stack factory and its mandatory guards.

These tests exercise the built stack through its public surface: an execution
request in, a dispatch result out, plus the durable gate state and the SQLite
quarantine rows. Nothing here inspects a private attribute of the factory's
result.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from quantx.application.execution import ExecutionDispatchStatus
from quantx.application.live_execution import (
    LiveExecutionCompositionError,
    LiveExecutionConfig,
    build_live_execution,
)
from quantx.application.live_risk import LiveRiskEvaluationInputs
from quantx.application.pending_recovery import PendingRecoveryRun
from quantx.application.production import ProductionRuntime
from quantx.application.runtime import ApplicationRuntime
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import (
    PreTradeRiskEngine,
    RiskContext,
    RiskDecision,
    RiskLimits,
    RiskResult,
    RiskSnapshot,
)
from quantx.domain.value_objects import Money, ProductCode
from quantx.execution.trading_gate import TradingGateState
from quantx.india.domain import IndianExchange, IndianSegment
from quantx.india.execution_rules import IndiaRuleDecision, IndiaRuleResult
from quantx.india.market_checks import india_market_policy
from quantx.india.session_calendar import (
    IndiaSessionDecision,
    IndiaSessionPermission,
    IndiaSessionResult,
)
from quantx.integrations.account_registry import AccountConnectionRegistry
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteSubmissionQuarantineRepository,
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)
from tests.unit._execution_request_proofs import approved_request, policy_verifier
from tests.unit.application.test_execution import FakeBroker

EVALUATED_AT = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 1, 1, 9, 29, tzinfo=UTC)

INDIA_PACK_ID = "india-equity"
INDIA_RULE_VERSION = "india-products-v1"
TEST_PACK_ID = "test-pack"
TEST_RULE_VERSION = "test-v1"


def _india_market() -> MarketContext:
    return MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def _north_america_market() -> MarketContext:
    return MarketContext(MarketRegion.NORTH_AMERICA, MarketFamily.EQUITY, "NYSE", "US")


def _india_instrument() -> Instrument:
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        _india_market(),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _north_america_instrument() -> Instrument:
    return Instrument(
        InstrumentId("NYSE", "AAPL"),
        "AAPL",
        AssetClass.EQUITY,
        _north_america_market(),
        "USD",
        Decimal("0.01"),
        Decimal("1"),
    )


def _financial() -> AccountFinancialState:
    return AccountFinancialState(
        CapitalSourceType.PAPER_CONFIGURED,
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
    )


def _context() -> RiskContext:
    return RiskContext(
        _india_instrument(),
        _financial(),
        broker_constraints=(),
        reference_price=Decimal("100"),
    )


def _limits(**overrides) -> RiskLimits:
    values: dict = {
        "max_order_notional": Decimal("100000"),
        "max_position_notional": Decimal("100000"),
        "max_portfolio_exposure": Decimal("1000000"),
        "max_instrument_concentration": Decimal("0.9"),
        "max_daily_loss": Decimal("10000"),
        "max_drawdown": Decimal("0.5"),
        "max_snapshot_age": timedelta(minutes=5),
    }
    values.update(overrides)
    return RiskLimits(**values)


def _snapshot() -> RiskSnapshot:
    return RiskSnapshot(
        observed_at=OBSERVED_AT,
        current_position_exposure=Decimal("0"),
        current_instrument_exposure=Decimal("0"),
        current_portfolio_exposure=Decimal("100000"),
        available_margin=Decimal("100000"),
        required_margin=Decimal("1000"),
        daily_pnl=Decimal("0"),
        equity=Decimal("100000"),
        high_water_mark=Decimal("100000"),
    )


def _risk_intent() -> TradeIntent:
    return TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        required_margin=Decimal("1000"),
        required_capabilities=frozenset({"ORDER_SUBMISSION"}),
        execution_context=_execution_context(),
        product=ProductCode("CNC"),
    )


def _execution_context(
    market: MarketContext | None = None,
    *,
    pack_id: str = INDIA_PACK_ID,
    rule_version: str = INDIA_RULE_VERSION,
) -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=market or _india_market(),
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
        market_pack_id=pack_id,
        rule_version=rule_version,
    )


def _request(
    market: MarketContext | None = None,
    *,
    pack_id: str = INDIA_PACK_ID,
    rule_version: str = INDIA_RULE_VERSION,
) -> ApprovedExecutionRequest:
    context = _execution_context(market, pack_id=pack_id, rule_version=rule_version)
    instrument = _north_america_instrument() if market is not None else _india_instrument()
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        execution_context=context,
        product=ProductCode("CNC"),
    )
    return approved_request(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        product=ProductCode("CNC"),
    )


def _live_request() -> ApprovedExecutionRequest:
    return _request()


def _approving_risk_inputs(request: ApprovedExecutionRequest) -> LiveRiskEvaluationInputs:
    """Approving evidence for the real engine; the provider ignores the request.

    That indifference is the caller-supplied-risk-evidence gap recorded in the
    slice-A non-claims. It is not something this factory closes.
    """
    return LiveRiskEvaluationInputs(
        intent=_risk_intent(),
        context=_context(),
        snapshot=_snapshot(),
        evaluated_at=EVALUATED_AT,
    )


def _approving_india_evaluator():
    def approve(request) -> IndiaRuleResult:
        return IndiaRuleResult(
            IndiaRuleDecision.APPROVE,
            "india compatibility approved for test",
            rule_set_version="test-b3",
            provenance="test-b3",
            evaluated_at=EVALUATED_AT,
            compatibility_evaluated=True,
        )

    return approve


def _approving_india_session_evaluator():
    def allow(request) -> IndiaSessionResult:
        return IndiaSessionResult(
            IndiaSessionDecision.ALLOW,
            "india session approved for test",
            calendar_version="test-calendar-v1",
            provenance="test-calendar",
            evaluated_at=EVALUATED_AT,
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
            session_id="regular",
            granted_permissions=frozenset({IndiaSessionPermission.ORDER_SUBMISSION}),
            calendar_evaluated=True,
        )

    return allow


def _policy(*, session: bool = True, rules: bool = True):
    return india_market_policy(
        session_evaluator=_approving_india_session_evaluator() if session else None,
        rule_evaluator=_approving_india_evaluator() if rules else None,
    )


def _config(**overrides) -> LiveExecutionConfig:
    values: dict = {
        "risk_limits": _limits(),
        "risk_engine": PreTradeRiskEngine(),
        "risk_inputs_for_request": _approving_risk_inputs,
        "market_policy": _policy(),
        "policy_verifier": policy_verifier(),
    }
    values.update(overrides)
    return LiveExecutionConfig(**values)


def _started_application() -> ApplicationRuntime:
    class NoopRecovery:
        def run(self, *, checked_at=None) -> PendingRecoveryRun:
            return PendingRecoveryRun()

    application = ApplicationRuntime(pending_recovery=NoopRecovery())
    application.start(checked_at=EVALUATED_AT)
    return application


def _runtime(database: SqliteDatabase) -> ProductionRuntime:
    return ProductionRuntime(
        database=database,
        unit_of_work=SqliteUnitOfWork(database),
        registry=AccountConnectionRegistry(),
        application=_started_application(),
    )


def _expect_build_error(database: SqliteDatabase, config, message: str) -> None:
    """Assert the build fails with fixed text and writes no durable state."""
    with pytest.raises(LiveExecutionCompositionError, match=message):
        build_live_execution(_runtime(database), config)
    assert SqliteTradingGateStateStore(database).load() is None


def test_build_disarms_persisted_enabled_gate_on_new_process_start(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        store = SqliteTradingGateStateStore(database)
        store.save(TradingGateState(enabled=True))
        assert store.load() == TradingGateState(enabled=True)

        stack = build_live_execution(_runtime(database), _config())

        persisted = store.load()
        assert persisted is not None
        assert persisted.enabled is False
        assert persisted.reason == "LIVE gate disarmed for new process start"
        assert stack.gate.state() == persisted

        broker = FakeBroker()
        result = stack.orchestrator.execute(_live_request(), broker=broker)
        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert broker.submit_calls == 0
    finally:
        database.close()


def test_built_stack_is_disarmed_and_blocks_a_valid_live_request(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        runtime = _runtime(database)
        stack = build_live_execution(runtime, _config())
        broker = FakeBroker()
        request = _live_request()

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert result.reason.startswith("trading is blocked")
        assert stack.gate.state().enabled is False
        assert broker.submit_calls == 0
        assert SqliteTradingGateStateStore(database).load() == stack.gate.state()
        assert (
            SqliteSubmissionQuarantineRepository(database).list_by_client_order(
                request.order.client_order_id
            )
            == ()
        )
    finally:
        database.close()


def test_enabled_stack_executes_a_valid_live_request_exactly_once(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        runtime = _runtime(database)
        stack = build_live_execution(runtime, _config())
        stack.gate.enable()
        broker = FakeBroker()
        request = _live_request()

        first = stack.orchestrator.execute(request, broker=broker)
        second = stack.orchestrator.execute(request, broker=broker)

        assert first.status is ExecutionDispatchStatus.EXECUTED
        assert first.receipt is not None
        assert first.receipt.source == "fake-broker"
        assert second.status is ExecutionDispatchStatus.EXECUTED
        assert second.receipt == first.receipt
        assert "idempotent duplicate" in second.reason
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_block_after_enable_blocks_the_next_request(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        runtime = _runtime(database)
        stack = build_live_execution(runtime, _config())
        stack.gate.enable()
        broker = FakeBroker()

        executed = stack.orchestrator.execute(_live_request(), broker=broker)
        stack.gate.block("operator stop")
        blocked = stack.orchestrator.execute(_live_request(), broker=broker)

        assert executed.status is ExecutionDispatchStatus.EXECUTED
        assert blocked.status is ExecutionDispatchStatus.BLOCKED
        assert "operator stop" in blocked.reason
        assert broker.submit_calls == 1
    finally:
        database.close()


def test_build_rejects_empty_risk_limits(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        _expect_build_error(
            database,
            _config(risk_limits=RiskLimits()),
            "LIVE risk limits require explicit positive limits",
        )
    finally:
        database.close()


def test_build_rejects_a_missing_mandatory_limit(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        _expect_build_error(
            database,
            _config(risk_limits=_limits(max_daily_loss=None)),
            "LIVE risk limits require explicit positive limits",
        )
    finally:
        database.close()


def test_build_rejects_an_india_policy_with_an_empty_pre_dispatch_stage(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        _expect_build_error(
            database,
            _config(market_policy=_policy(session=False)),
            "market_policy must place at least one pre-dispatch check for India",
        )
    finally:
        database.close()


def test_build_rejects_an_india_policy_with_an_empty_pre_submit_stage(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        _expect_build_error(
            database,
            _config(market_policy=_policy(rules=False)),
            "market_policy must place at least one pre-submit check for India",
        )
    finally:
        database.close()


def test_build_rejects_a_non_callable_risk_inputs_provider(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        _expect_build_error(
            database,
            _config(risk_inputs_for_request="not callable"),
            "risk_inputs_for_request must be callable",
        )
    finally:
        database.close()


def test_build_rejects_wrong_field_types(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        _expect_build_error(
            database, object(), "live execution config must be a LiveExecutionConfig"
        )
        _expect_build_error(
            database, _config(risk_limits=object()), "risk_limits must be a RiskLimits"
        )
        _expect_build_error(
            database, _config(risk_engine=object()), "risk_engine must be a PreTradeRiskEngine"
        )
        _expect_build_error(
            database,
            _config(market_policy=object()),
            "market_policy must be a MarketPolicyConfig",
        )
        _expect_build_error(
            database,
            _config(policy_verifier=object()),
            "policy_verifier must be a MarketPackPolicyVerifier",
        )
    finally:
        database.close()


def test_live_execution_config_requires_a_policy_verifier() -> None:
    with pytest.raises(TypeError, match="policy_verifier"):
        LiveExecutionConfig(
            risk_limits=_limits(),
            risk_engine=PreTradeRiskEngine(),
            risk_inputs_for_request=_approving_risk_inputs,
            market_policy=_policy(),
        )


def _garbage_risk_result(self, *args, **kwargs):
    return "not a risk result"


def test_built_stack_blocks_a_malformed_risk_evaluator_result(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(PreTradeRiskEngine, "evaluate_with_limits", _garbage_risk_result)
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        runtime = _runtime(database)
        stack = build_live_execution(runtime, _config())
        stack.gate.enable()
        broker = FakeBroker()

        result = stack.orchestrator.execute(_live_request(), broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert result.reason == "live pre-trade risk evaluation returned an invalid result"
        assert broker.submit_calls == 0
    finally:
        database.close()


def test_non_india_live_request_through_the_built_stack_is_blocked(tmp_path) -> None:
    """The sanctioned LIVE composition is India-only, even after gate enablement."""
    database = SqliteDatabase(tmp_path / "quantx.db")
    risk_input_calls: list[ApprovedExecutionRequest] = []

    def record_risk_inputs(request: ApprovedExecutionRequest) -> LiveRiskEvaluationInputs:
        risk_input_calls.append(request)
        return _approving_risk_inputs(request)

    try:
        runtime = _runtime(database)
        stack = build_live_execution(
            runtime,
            _config(risk_inputs_for_request=record_risk_inputs),
        )
        stack.gate.enable()
        broker = FakeBroker(instrument=_north_america_instrument())
        request = _request(
            _north_america_market(),
            pack_id=TEST_PACK_ID,
            rule_version=TEST_RULE_VERSION,
        )

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert result.reason == "LIVE execution is not enabled for this market region"
        assert broker.submit_calls == 0
        assert risk_input_calls == []
        assert (
            SqliteSubmissionQuarantineRepository(database).list_by_client_order(
                request.order.client_order_id
            )
            == ()
        )
    finally:
        database.close()


def test_build_rejects_a_duck_typed_runtime(tmp_path) -> None:
    """A runtime-shaped object that is not a ProductionRuntime cannot build."""

    class DuckRuntime:
        def __init__(self, runtime: ProductionRuntime) -> None:
            self.database = runtime.database
            self.unit_of_work = runtime.unit_of_work
            self.application = runtime.application

    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        duck = DuckRuntime(_runtime(database))
        with pytest.raises(
            LiveExecutionCompositionError, match="runtime must be a ProductionRuntime"
        ):
            build_live_execution(cast(ProductionRuntime, duck), _config())
        assert SqliteTradingGateStateStore(database).load() is None
    finally:
        database.close()
