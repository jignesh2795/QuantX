"""Composition-root tests for LIVE validation and fail-closed refusal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from quantx.application.live_execution import (
    LiveExecutionCompositionError,
    LiveExecutionConfig,
    _india_only_market_policy,
    build_live_execution,
)
from quantx.application.pending_recovery import PendingRecoveryRun
from quantx.application.production import ProductionRuntime
from quantx.application.runtime import ApplicationRuntime
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.clock import FixedClock
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
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
    RiskDecision,
    RiskLimits,
    RiskResult,
)
from quantx.domain.value_objects import ProductCode
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
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)
from quantx.ports.market_checks import (
    MarketCheckResult,
    MarketCheckStage,
    MarketPolicyConfig,
    PlacedCheck,
)
from tests.unit._execution_request_proofs import approved_request, policy_verifier

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


def _limits(**overrides) -> RiskLimits:
    values: dict = {
        "max_order_notional": Decimal("100000"),
        "max_position_notional": Decimal("100000"),
        "max_portfolio_exposure": Decimal("1000000"),
        "max_instrument_concentration": Decimal("0.9"),
        "max_daily_loss": Decimal("10000"),
        "max_unrealized_loss": Decimal("5000"),
        "max_drawdown": Decimal("0.5"),
        "max_snapshot_age": timedelta(minutes=5),
    }
    values.update(overrides)
    return RiskLimits(**values)


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
        "clock": FixedClock(EVALUATED_AT),
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


def test_build_refusal_does_not_mutate_existing_gate(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        store = SqliteTradingGateStateStore(database)
        seeded = TradingGateState(enabled=True)
        store.save(seeded)
        with pytest.raises(LiveExecutionCompositionError, match="LIVE risk evidence authority set"):
            build_live_execution(_runtime(database), _config())
        # A refused construction is side-effect-free; it returns no stack.
        assert store.load() == seeded
    finally:
        database.close()

def test_sanctioned_live_composition_refuses_until_authorities_are_wired(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        _expect_build_error(
            database,
            _config(),
            (
                "LIVE risk evidence authority set unavailable; "
                "production LIVE composition is blocked"
            ),
        )
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
        _expect_build_error(database, _config(clock=object()), "clock must be a Clock")
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


def test_live_execution_config_rejects_caller_supplied_risk_provider() -> None:
    with pytest.raises(TypeError, match="risk_inputs_for_request"):
        LiveExecutionConfig(
            risk_limits=_limits(),
            risk_engine=PreTradeRiskEngine(),
            clock=FixedClock(EVALUATED_AT),
            market_policy=_policy(),
            policy_verifier=policy_verifier(),
            **{"risk_inputs_for_request": object()},
        )


def test_live_execution_config_requires_a_policy_verifier() -> None:
    with pytest.raises(TypeError, match="policy_verifier"):
        LiveExecutionConfig(
            risk_limits=_limits(),
            risk_engine=PreTradeRiskEngine(),
            clock=FixedClock(EVALUATED_AT),
            market_policy=_policy(),
        )


def test_live_execution_config_requires_a_trusted_clock() -> None:
    with pytest.raises(TypeError, match="clock"):
        LiveExecutionConfig(
            risk_limits=_limits(),
            risk_engine=PreTradeRiskEngine(),
            market_policy=_policy(),
            policy_verifier=policy_verifier(),
        )


class _NonIndiaCheck:
    """A caller-placed check for a non-India region; it must never execute."""

    check_id = "NORTH_AMERICA.pre-a"

    def __call__(self, request: ApprovedExecutionRequest) -> MarketCheckResult:
        raise AssertionError("a rejected policy must never run a placed check")


def _policy_with_a_non_india_placement() -> MarketPolicyConfig:
    base = _policy()
    placement = PlacedCheck(
        region=MarketRegion.NORTH_AMERICA,
        stage=MarketCheckStage.PRE_DISPATCH,
        check=_NonIndiaCheck(),
    )
    return MarketPolicyConfig(regions=base.regions, checks=(*base.checks, placement))


def _assert_placements_preserved(
    derived: MarketPolicyConfig, expected: tuple[PlacedCheck, ...]
) -> None:
    """India's placements survive derivation object for object, in order."""
    assert len(derived.checks) == len(expected)
    for derived_placed, expected_placed in zip(derived.checks, expected, strict=True):
        assert derived_placed.region is expected_placed.region
        assert derived_placed.stage is expected_placed.stage
        assert derived_placed.check is expected_placed.check
        assert derived_placed.validated_check_id == expected_placed.validated_check_id


def test_derived_policy_locks_every_region_but_india() -> None:
    """Every non-India member requires both stages and places no checks."""
    caller = _policy()

    derived = _india_only_market_policy(caller)

    caller_india = caller.policy_for(MarketRegion.INDIA)
    india = derived.policy_for(MarketRegion.INDIA)
    assert india is caller_india
    assert india.region is caller_india.region
    assert india.requires_pack is caller_india.requires_pack
    assert india.required_stages == caller_india.required_stages
    assert india.optional_stages == caller_india.optional_stages
    assert india.replaces_session_guard is caller_india.replaces_session_guard
    _assert_placements_preserved(derived, caller.checks)
    assert len(derived.regions) == len(MarketRegion)
    for member in MarketRegion:
        if member is MarketRegion.INDIA:
            continue
        policy = derived.policy_for(member)
        assert policy.region is member
        assert policy.requires_pack is True
        assert policy.required_stages == frozenset(
            {MarketCheckStage.PRE_DISPATCH, MarketCheckStage.PRE_SUBMIT}
        )
        assert policy.optional_stages == frozenset()
        assert policy.replaces_session_guard is False
        assert derived.checks_for(member, MarketCheckStage.PRE_DISPATCH) == ()
        assert derived.checks_for(member, MarketCheckStage.PRE_SUBMIT) == ()

    # The factory rejects a contaminated policy before derivation; the helper
    # must not resurrect a non-India placement either.
    contaminated_caller = _policy_with_a_non_india_placement()
    contaminated = _india_only_market_policy(contaminated_caller)
    expected_india = tuple(
        placed for placed in contaminated_caller.checks if placed.region is MarketRegion.INDIA
    )
    _assert_placements_preserved(contaminated, expected_india)
    assert contaminated.checks_for(MarketRegion.NORTH_AMERICA, MarketCheckStage.PRE_DISPATCH) == ()


def test_build_rejects_a_non_india_policy_placement(tmp_path) -> None:
    """A caller policy that places a non-India check cannot build."""
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        _expect_build_error(
            database,
            _config(market_policy=_policy_with_a_non_india_placement()),
            "market_policy must not place checks for a non-India region",
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


# Trusted clock (slice B): the composition root owns the freshness instant.


def test_build_rejects_an_invalid_clock(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        _expect_build_error(database, _config(clock=None), "clock must be a Clock")
        _expect_build_error(database, _config(clock=object()), "clock must be a Clock")
    finally:
        database.close()
