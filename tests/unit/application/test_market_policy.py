"""Market-pack pre-trade-check pipeline: selection, ordering and evidence.

Covers the neutral contract (ports/market_checks.py) and its wiring
through ExecutionOrchestrator without touching broker submission,
execution/recovery internals, or India-owned result classes from core.
"""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
from quantx.application.pending_recovery import PendingRecoveryRun
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
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.trading_gate import DurableTradingGate, InMemoryTradingGateStateStore
from quantx.integrations.brokers import BrokerConnectionRef, CapabilitySet
from quantx.ports.market_checks import (
    MarketCheckEvidence,
    MarketCheckFailureCode,
    MarketCheckOutcome,
    MarketCheckResult,
    MarketCheckStage,
    MarketPolicyConfig,
    PlacedCheck,
    RegionMarketPolicy,
    sequence_to_mapping,
)


def _market(
    region: MarketRegion = MarketRegion.INDIA,
    family: MarketFamily = MarketFamily.EQUITY,
    venue: str = "NSE",
) -> MarketContext:
    return MarketContext(region, family, venue, "IN")


def _instrument() -> Instrument:
    from quantx.domain.instruments import Instrument

    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        _market(),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _request(
    mode: ExecutionMode = ExecutionMode.LIVE, market: MarketContext | None = None
) -> ApprovedExecutionRequest:
    instrument = _instrument()
    market = market or instrument.market
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=mode,
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _started_runtime() -> ApplicationRuntime:
    class NoopRecovery:
        def run(self, *, checked_at=None) -> PendingRecoveryRun:
            return PendingRecoveryRun()

    runtime = ApplicationRuntime(pending_recovery=NoopRecovery())
    runtime.start(checked_at=datetime(2026, 1, 1, tzinfo=UTC))
    return runtime


def _live_orchestrator(**overrides) -> ExecutionOrchestrator:
    return ExecutionOrchestrator(
        trading_gate=DurableTradingGate(InMemoryTradingGateStateStore()),
        application_runtime=_started_runtime(),
        **overrides,
    )


class _ToyCheck:
    """Test-only pack check with a fixed verdict and call recording."""

    def __init__(
        self,
        check_id: str,
        outcome: MarketCheckOutcome,
        calls: list,
        reason: str = "toy check verdict",
        stage: MarketCheckStage = MarketCheckStage.PRE_DISPATCH,
    ) -> None:
        self._check_id = check_id
        self._outcome = outcome
        self._calls = calls
        self._reason = reason
        self._stage = stage

    @property
    def check_id(self) -> str:
        return self._check_id

    def __call__(self, request: ApprovedExecutionRequest) -> MarketCheckResult:
        self._calls.append(request)
        if self._outcome is MarketCheckOutcome.PASS:
            return MarketCheckResult(self._check_id, MarketCheckOutcome.PASS, None, self._reason)
        return MarketCheckResult(
            self._check_id,
            self._outcome,
            "toy.pack.rejected",
            self._reason,
            evidence=MarketCheckEvidence(
                check_id=self._check_id,
                stage=self._stage,
                outcome=self._outcome,
                region=MarketRegion.NORTH_AMERICA,
                family=MarketFamily.EQUITY,
                venue="NYSE",
            ),
        )


def _canonical_india_policy() -> RegionMarketPolicy:
    """Canonical India classification preserved by every toy configuration."""
    return RegionMarketPolicy(
        region=MarketRegion.INDIA,
        requires_pack=True,
        required_stages=frozenset({MarketCheckStage.PRE_DISPATCH, MarketCheckStage.PRE_SUBMIT}),
        replaces_session_guard=True,
    )


def _regions_with_canonical_india(special: RegionMarketPolicy | None = None) -> tuple:
    """All regions core-only except canonical India plus one special policy."""
    policies = []
    for member in MarketRegion:
        if member is MarketRegion.INDIA:
            policies.append(_canonical_india_policy())
        elif special is not None and member is special.region:
            policies.append(special)
        else:
            policies.append(RegionMarketPolicy(region=member))
    return tuple(policies)


def _toy_policy(
    *,
    region: MarketRegion = MarketRegion.NORTH_AMERICA,
    pre_dispatch_outcome: MarketCheckOutcome = MarketCheckOutcome.PASS,
    pre_submit_outcome: MarketCheckOutcome = MarketCheckOutcome.PASS,
    optional_submit: bool = False,
    replaces_session_guard: bool = False,
    calls: list | None = None,
) -> tuple[MarketPolicyConfig, list]:
    """Build a config reclassifying one region as pack-required (test-only).

    The canonical India policy is always preserved; only the toy region is
    reclassified, so India invariants stay covered while the toy region
    exercises extensibility.
    """
    calls = calls if calls is not None else []
    pa = _ToyCheck(f"{region.value}.pre-a", pre_dispatch_outcome, calls)
    checks = [PlacedCheck(region, MarketCheckStage.PRE_DISPATCH, pa)]
    if not optional_submit:
        checks.append(
            PlacedCheck(
                region,
                MarketCheckStage.PRE_SUBMIT,
                _ToyCheck(
                    f"{region.value}.pre-b",
                    pre_submit_outcome,
                    calls,
                    stage=MarketCheckStage.PRE_SUBMIT,
                ),
            )
        )
    policy = RegionMarketPolicy(
        region=region,
        requires_pack=True,
        required_stages=frozenset({MarketCheckStage.PRE_DISPATCH})
        if optional_submit
        else frozenset({MarketCheckStage.PRE_DISPATCH, MarketCheckStage.PRE_SUBMIT}),
        optional_stages=frozenset({MarketCheckStage.PRE_SUBMIT})
        if optional_submit
        else frozenset(),
        replaces_session_guard=replaces_session_guard,
    )
    regions = tuple(
        _canonical_india_policy()
        if member is MarketRegion.INDIA
        else (policy if member is region else RegionMarketPolicy(region=member))
        for member in MarketRegion
    )
    return MarketPolicyConfig(regions=regions, checks=tuple(checks)), calls


class _RecordingBroker:
    """Broker double recording submit calls without contacting any venue."""

    def __init__(self, instrument) -> None:
        self.submit_calls = 0
        self._instrument = instrument
        self._connection = BrokerConnectionRef(
            AccountId("acct-1"), BrokerConnectionId("conn-1"), "toy", "NYSE"
        )

    @property
    def connection(self):
        return self._connection

    def health(self) -> bool:
        return True

    def capabilities(self):
        return CapabilitySet(frozenset())

    def instrument(self, instrument_id):
        return self._instrument if instrument_id == self._instrument.instrument_id else None

    def submit(self, request):
        self.submit_calls += 1
        raise AssertionError("toy broker must never submit")


def _us_market() -> MarketContext:
    return MarketContext(MarketRegion.NORTH_AMERICA, MarketFamily.EQUITY, "NYSE", "US")


def _us_instrument():
    from quantx.domain.instruments import Instrument

    return Instrument(
        InstrumentId("NYSE", "AAPL"),
        "AAPL",
        AssetClass.EQUITY,
        _us_market(),
        "USD",
        Decimal("0.01"),
        Decimal("1"),
    )


def _us_request() -> ApprovedExecutionRequest:
    instrument = _us_instrument()
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


# ---------------------------------------------------------------------------
# A. No India imports under quantx.application
# ---------------------------------------------------------------------------


def test_application_source_has_no_india_imports() -> None:
    package = Path(__file__).resolve().parents[3] / "src" / "quantx" / "application"
    offenders = []
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("quantx.india"):
                offenders.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("quantx.india"):
                        offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


# ---------------------------------------------------------------------------
# Ordering: P-A/P-B against every intervening core guard
# ---------------------------------------------------------------------------


def test_toy_pa_block_runs_before_session_guard() -> None:
    from quantx.execution.session_guard import SessionExecutionGuard

    policy, calls = _toy_policy(pre_dispatch_outcome=MarketCheckOutcome.BLOCK)
    closed_guard = SessionExecutionGuard(session=_ClosedSession())
    orchestrator = _live_orchestrator(market_policy=policy, session_guard=closed_guard)
    result = orchestrator.execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "toy check verdict"
    assert [call for call in calls] != []
    assert result.check_evidence is not None
    assert [entry.check_id for entry in result.check_evidence.entries] == ["NORTH_AMERICA.pre-a"]
    assert result.check_evidence.blocking_check_id == "NORTH_AMERICA.pre-a"
    assert result.check_evidence.blocking_failure_code == "toy.pack.rejected"


def test_toy_pb_block_runs_after_broker_checks_before_submit() -> None:
    policy, calls = _toy_policy(pre_submit_outcome=MarketCheckOutcome.BLOCK)
    broker = _RecordingBroker(_us_instrument())
    orchestrator = _live_orchestrator(market_policy=policy)
    result = orchestrator.execute(_us_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "toy check verdict"
    assert broker.submit_calls == 0
    assert result.check_evidence is not None
    assert [entry.check_id for entry in result.check_evidence.entries] == [
        "NORTH_AMERICA.pre-a",
        "NORTH_AMERICA.pre-b",
    ]
    assert result.check_evidence.short_circuited is True
    assert result.check_evidence.blocking_check_id == "NORTH_AMERICA.pre-b"


def test_toy_approval_without_broker_blocks_without_submit() -> None:
    policy, _ = _toy_policy()
    orchestrator = _live_orchestrator(market_policy=policy)
    result = orchestrator.execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "broker adapter" in result.reason
    assert result.check_evidence is not None
    assert result.check_evidence.short_circuited is False
    assert [entry.check_id for entry in result.check_evidence.entries] == ["NORTH_AMERICA.pre-a"]
    assert [entry.outcome for entry in result.check_evidence.entries] == [MarketCheckOutcome.PASS]


class _ClosedSession:
    def status(self):
        from quantx.domain.sessions import SessionState, TradingSessionStatus

        return TradingSessionStatus(
            state=SessionState.CLOSED,
            observed_at=datetime(2026, 1, 1, 9, 15, tzinfo=UTC),
            timezone="UTC",
        )


# ---------------------------------------------------------------------------
# Missing pack/stage, duplicates, invalid configuration
# ---------------------------------------------------------------------------


def test_missing_required_pack_stage_blocks_with_code() -> None:
    orchestrator = _live_orchestrator()
    result = orchestrator.execute(_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "required pre-dispatch market checks are missing" in result.reason
    assert result.check_evidence is not None
    assert result.check_evidence.short_circuited is True
    assert result.check_evidence.blocking_failure_code == (
        MarketCheckFailureCode.MISSING_REQUIRED_STAGE
    )


def test_duplicate_check_identity_rejected() -> None:
    calls: list = []
    check = _ToyCheck("dup", MarketCheckOutcome.PASS, calls)
    regions = _regions_with_canonical_india(
        RegionMarketPolicy(
            region=MarketRegion.NORTH_AMERICA,
            requires_pack=True,
            required_stages=frozenset({MarketCheckStage.PRE_DISPATCH}),
        )
    )
    with pytest.raises(ValueError, match="duplicate check identity"):
        MarketPolicyConfig(
            regions=regions,
            checks=(
                PlacedCheck(MarketRegion.NORTH_AMERICA, MarketCheckStage.PRE_DISPATCH, check),
                PlacedCheck(MarketRegion.NORTH_AMERICA, MarketCheckStage.PRE_DISPATCH, check),
            ),
        )


def test_duplicate_region_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate region policy"):
        MarketPolicyConfig(
            regions=(
                RegionMarketPolicy(region=MarketRegion.INDIA, requires_pack=True),
                RegionMarketPolicy(region=MarketRegion.INDIA),
            )
        )


def test_overlapping_required_optional_stages_rejected() -> None:
    with pytest.raises(ValueError, match="both required and optional"):
        RegionMarketPolicy(
            region=MarketRegion.INDIA,
            requires_pack=True,
            required_stages=frozenset({MarketCheckStage.PRE_DISPATCH}),
            optional_stages=frozenset({MarketCheckStage.PRE_DISPATCH}),
        )


def test_unclassified_region_rejected_at_build() -> None:
    regions = tuple(
        _canonical_india_policy()
        if member is MarketRegion.INDIA
        else RegionMarketPolicy(region=member)
        for member in MarketRegion
        if member is not MarketRegion.GLOBAL
    )
    with pytest.raises(ValueError, match="unclassified regions"):
        MarketPolicyConfig(regions=regions)


def test_unknown_region_string_fails_closed() -> None:
    orchestrator = _live_orchestrator()
    request = _request()
    from quantx.domain.instruments import MarketContext as Ctx

    foreign = Ctx("NOWHERE", request.execution_context.market.family, "XXX", "US")
    context = ExecutionContext(
        account_id=request.execution_context.account_id,
        portfolio_id=request.execution_context.portfolio_id,
        deployment_id=request.execution_context.deployment_id,
        market=foreign,
        broker_connection_id=request.execution_context.broker_connection_id,
        execution_mode=ExecutionMode.LIVE,
    )
    intent = TradeIntent(
        instrument=request.order.instrument,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        execution_context=context,
    )
    foreign_request = ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )
    result = orchestrator.execute(foreign_request)
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "unknown market region or family fails closed" in result.reason


def test_unknown_family_string_fails_closed() -> None:
    from quantx.domain.instruments import MarketContext as Ctx

    request = _request()
    foreign = Ctx(MarketRegion.NORTH_AMERICA, "NOPE", "NYSE", "US")
    context = ExecutionContext(
        account_id=request.execution_context.account_id,
        portfolio_id=request.execution_context.portfolio_id,
        deployment_id=request.execution_context.deployment_id,
        market=foreign,
        broker_connection_id=request.execution_context.broker_connection_id,
        execution_mode=ExecutionMode.LIVE,
    )
    intent = TradeIntent(
        instrument=request.order.instrument,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        execution_context=context,
    )
    foreign_request = ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )
    orchestrator = _live_orchestrator()
    result = orchestrator.execute(foreign_request)
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "unknown market region or family fails closed" in result.reason


# ---------------------------------------------------------------------------
# Unmapped India families, modes, BACKTEST
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "family",
    [
        MarketFamily.DIGITAL_ASSETS,
        MarketFamily.FIXED_INCOME,
        MarketFamily.FUND,
        MarketFamily.OTHER,
    ],
)
def test_unmapped_india_families_block(family: MarketFamily) -> None:
    from quantx.india.market_checks import india_market_policy

    market = MarketContext(MarketRegion.INDIA, family, "NSE", "IN")
    request = _request(market=market)
    orchestrator = _live_orchestrator(market_policy=india_market_policy())
    result = orchestrator.execute(request)

    assert result.status is ExecutionDispatchStatus.BLOCKED


@pytest.mark.parametrize("mode", [ExecutionMode.PAPER, ExecutionMode.SHADOW, ExecutionMode.REPLAY])
def test_india_non_live_modes_keep_session_guard_without_pack_checks(
    mode: ExecutionMode,
) -> None:
    from quantx.execution.session_guard import SessionExecutionGuard

    calls: list = []
    policy, _ = _toy_policy(calls=calls)
    request = _request(mode=mode)
    orchestrator = ExecutionOrchestrator(
        trading_gate=DurableTradingGate(InMemoryTradingGateStateStore()),
        application_runtime=_started_runtime(),
        session_guard=SessionExecutionGuard(session=_ClosedSession()),
        market_policy=policy,
    )
    result = orchestrator.execute(request)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert calls == []


def test_backtest_mode_rejection_preserved() -> None:
    from quantx.domain.deployment import ExecutionMode as Mode

    request = _request(mode=Mode.BACKTEST)
    orchestrator = _live_orchestrator()
    result = orchestrator.execute(request)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "unsupported execution mode" in result.reason


# ---------------------------------------------------------------------------
# Sanitization and allow-list
# ---------------------------------------------------------------------------


def test_b3_exception_in_session_evaluator_sanitized() -> None:
    from quantx.india.market_checks import IndiaSessionCheck

    def exploding(request):
        raise RuntimeError("B3 venue snapshot exploded")

    policy, _ = _toy_policy()
    regions = tuple(
        _canonical_india_policy()
        if member is MarketRegion.INDIA
        else RegionMarketPolicy(region=member)
        for member in MarketRegion
    )
    config = MarketPolicyConfig(
        regions=regions,
        checks=(
            PlacedCheck(
                MarketRegion.INDIA, MarketCheckStage.PRE_DISPATCH, IndiaSessionCheck(exploding)
            ),
        ),
    )
    orchestrator = _live_orchestrator(market_policy=config)
    result = orchestrator.execute(_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "B3" not in result.reason
    assert "evaluation failed closed" in result.reason
    assert result.check_evidence is not None
    assert result.check_evidence.blocking_failure_code == "india.session-calendar.evaluation-failed"


def test_b3_exception_in_compat_evaluator_sanitized() -> None:
    from quantx.india.market_checks import IndiaCompatCheck

    def exploding(request):
        raise RuntimeError("B3 compat exploded")

    from quantx.india.market_checks import IndiaSessionCheck as SessionCheck

    regions = tuple(
        _canonical_india_policy()
        if member is MarketRegion.INDIA
        else RegionMarketPolicy(region=member)
        for member in MarketRegion
    )
    config = MarketPolicyConfig(
        regions=regions,
        checks=(
            PlacedCheck(
                MarketRegion.INDIA,
                MarketCheckStage.PRE_DISPATCH,
                SessionCheck(_approving_session()),
            ),
            PlacedCheck(
                MarketRegion.INDIA, MarketCheckStage.PRE_SUBMIT, IndiaCompatCheck(exploding)
            ),
        ),
    )
    orchestrator = _live_orchestrator(market_policy=config)
    result = orchestrator.execute(_request(), broker=_RecordingBroker(_instrument()))

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "B3" not in result.reason
    assert "evaluation failed closed" in result.reason


def _approving_session():
    from quantx.india.domain import IndianExchange, IndianSegment
    from quantx.india.session_calendar import IndiaSessionDecision, IndiaSessionResult

    def allow(request):
        return IndiaSessionResult(
            IndiaSessionDecision.ALLOW,
            "india session approved for test",
            calendar_version="test-calendar-v1",
            provenance="test-calendar",
            evaluated_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
            calendar_evaluated=True,
        )

    return allow


# ---------------------------------------------------------------------------
# Determinism: ordering + fixed-clock serialization
# ---------------------------------------------------------------------------


def test_evidence_ordering_and_serialization_deterministic() -> None:
    policy, _ = _toy_policy()
    broker = _RecordingBroker(_us_instrument())
    first = _live_orchestrator(market_policy=policy).execute(_us_request(), broker=broker)
    second = _live_orchestrator(market_policy=policy).execute(_us_request(), broker=broker)

    assert first.status is ExecutionDispatchStatus.BLOCKED
    assert first.check_evidence is not None and second.check_evidence is not None
    assert [entry.check_id for entry in first.check_evidence.entries] == [
        "NORTH_AMERICA.pre-a",
        "NORTH_AMERICA.pre-b",
    ]
    assert json.dumps(sequence_to_mapping(first.check_evidence), sort_keys=True) == json.dumps(
        sequence_to_mapping(second.check_evidence), sort_keys=True
    )


def test_skipped_optional_stage_recorded_not_passed() -> None:
    policy, _ = _toy_policy(optional_submit=True)
    broker = _RecordingBroker(_us_instrument())
    orchestrator = _live_orchestrator(market_policy=policy)
    result = orchestrator.execute(_us_request(), broker=broker)

    assert result.check_evidence is not None
    outcomes = [entry.outcome for entry in result.check_evidence.entries]
    assert MarketCheckOutcome.SKIPPED in outcomes
    assert MarketCheckOutcome.PASS in outcomes
    assert result.check_evidence.short_circuited is False


def test_core_only_region_ignores_registered_pack() -> None:
    calls: list = []
    regions = _regions_with_canonical_india()
    config = MarketPolicyConfig(
        regions=regions,
        checks=(
            PlacedCheck(
                MarketRegion.NORTH_AMERICA,
                MarketCheckStage.PRE_DISPATCH,
                _ToyCheck("na.pre-a", MarketCheckOutcome.PASS, calls),
            ),
        ),
    )
    broker = _RecordingBroker(_us_instrument())
    orchestrator = _live_orchestrator(market_policy=config)
    result = orchestrator.execute(_us_request(), broker=broker)

    assert calls == []
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is None


def test_malformed_check_result_fails_closed() -> None:
    class _BadCheck:
        check_id = "na.bad"

        def __call__(self, request):
            return "not a result"

    regions = _regions_with_canonical_india(
        RegionMarketPolicy(
            region=MarketRegion.NORTH_AMERICA,
            requires_pack=True,
            required_stages=frozenset({MarketCheckStage.PRE_DISPATCH}),
        )
    )
    config = MarketPolicyConfig(
        regions=regions,
        checks=(
            PlacedCheck(MarketRegion.NORTH_AMERICA, MarketCheckStage.PRE_DISPATCH, _BadCheck()),
        ),
    )
    orchestrator = _live_orchestrator(market_policy=config)
    result = orchestrator.execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "malformed result" in result.reason
    assert result.check_evidence is not None
    assert result.check_evidence.blocking_failure_code == (MarketCheckFailureCode.MALFORMED_RESULT)


def test_check_without_identity_rejected_at_registration() -> None:
    class _AnonymousCheck:
        def __call__(self, request):
            return None

    with pytest.raises(ValueError, match="check id must not be empty"):
        PlacedCheck(MarketRegion.NORTH_AMERICA, MarketCheckStage.PRE_DISPATCH, _AnonymousCheck())


# ---------------------------------------------------------------------------
# Fix 1 — India policy invariant
# ---------------------------------------------------------------------------


def test_india_core_only_rejected() -> None:
    regions = tuple(
        RegionMarketPolicy(region=member, requires_pack=member is not MarketRegion.INDIA)
        for member in MarketRegion
    )
    with pytest.raises(ValueError, match="must not be classified as core-only"):
        MarketPolicyConfig(regions=regions)


@pytest.mark.parametrize(
    "stages",
    [
        frozenset({MarketCheckStage.PRE_DISPATCH}),
        frozenset({MarketCheckStage.PRE_SUBMIT}),
        frozenset(),
    ],
)
def test_india_incomplete_required_stages_rejected(stages) -> None:
    regions = tuple(
        RegionMarketPolicy(
            region=member,
            requires_pack=True,
            required_stages=stages if member is MarketRegion.INDIA else frozenset(),
            replaces_session_guard=member is MarketRegion.INDIA,
        )
        for member in MarketRegion
    )
    with pytest.raises(ValueError, match="both pre-dispatch and pre-submit"):
        MarketPolicyConfig(regions=regions)


def test_requires_pack_without_stages_rejected() -> None:
    regions = _regions_with_canonical_india(
        RegionMarketPolicy(region=MarketRegion.NORTH_AMERICA, requires_pack=True)
    )
    with pytest.raises(ValueError, match="no required stages"):
        MarketPolicyConfig(regions=regions)


def _india_approving_session():
    from quantx.india.domain import IndianExchange, IndianSegment
    from quantx.india.session_calendar import IndiaSessionDecision, IndiaSessionResult

    def allow(request):
        return IndiaSessionResult(
            IndiaSessionDecision.ALLOW,
            "india session approved for test",
            calendar_version="test-calendar-v1",
            provenance="test-calendar",
            evaluated_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
            calendar_evaluated=True,
        )

    return allow


def test_india_partial_pack_blocks_before_submit() -> None:
    from quantx.india.market_checks import india_market_policy

    config = india_market_policy(session_evaluator=_india_approving_session())
    broker = _RecordingBroker(_instrument())
    orchestrator = _live_orchestrator(market_policy=config)
    result = orchestrator.execute(_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "required pre-submit market checks are missing" in result.reason
    assert broker.submit_calls == 0
    assert result.check_evidence is not None
    assert result.check_evidence.blocking_failure_code == (
        MarketCheckFailureCode.MISSING_REQUIRED_STAGE
    )


# ---------------------------------------------------------------------------
# Fix 2 — evidence outcome matches the result
# ---------------------------------------------------------------------------


def test_session_rejection_carries_block_evidence() -> None:
    from quantx.india.domain import IndianExchange, IndianSegment
    from quantx.india.market_checks import india_market_policy
    from quantx.india.session_calendar import IndiaSessionDecision, IndiaSessionResult

    def closed(request):
        return IndiaSessionResult(
            IndiaSessionDecision.BLOCK,
            "india trading session is closed",
            calendar_version="test-calendar-v1",
            provenance="test-calendar",
            evaluated_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
            calendar_evaluated=True,
        )

    config = india_market_policy(session_evaluator=closed)
    orchestrator = _live_orchestrator(market_policy=config)
    result = orchestrator.execute(_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is not None
    assert len(result.check_evidence.entries) == 1
    entry = result.check_evidence.entries[0]
    assert entry.outcome is MarketCheckOutcome.BLOCK
    assert result.check_evidence.blocking_check_id == "india.session-calendar"
    assert result.check_evidence.blocking_failure_code == "india.session-calendar.rejected"


def test_compat_rejection_carries_block_evidence() -> None:
    from quantx.india.execution_rules import IndiaRuleDecision, IndiaRuleResult
    from quantx.india.market_checks import IndiaCompatCheck, IndiaSessionCheck

    def rejecting(request):
        return IndiaRuleResult(
            IndiaRuleDecision.REJECT,
            "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            rule_set_version="test",
            provenance="test",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    regions = tuple(
        _canonical_india_policy()
        if member is MarketRegion.INDIA
        else RegionMarketPolicy(region=member)
        for member in MarketRegion
    )
    config = MarketPolicyConfig(
        regions=regions,
        checks=(
            PlacedCheck(
                MarketRegion.INDIA,
                MarketCheckStage.PRE_DISPATCH,
                IndiaSessionCheck(_india_approving_session()),
            ),
            PlacedCheck(
                MarketRegion.INDIA, MarketCheckStage.PRE_SUBMIT, IndiaCompatCheck(rejecting)
            ),
        ),
    )
    broker = _RecordingBroker(_instrument())
    orchestrator = _live_orchestrator(market_policy=config)
    result = orchestrator.execute(_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "INDIA_LOT_SIZE_INVALID" in result.reason
    assert result.check_evidence is not None
    assert len(result.check_evidence.entries) == 2
    assert result.check_evidence.entries[-1].outcome is MarketCheckOutcome.BLOCK
    assert result.check_evidence.blocking_check_id == "india.compatibility-rules"
    assert result.check_evidence.blocking_failure_code == "india.compatibility.rejected"
    assert broker.submit_calls == 0


def test_malformed_rule_reason_fails_closed() -> None:
    from quantx.india.execution_rules import IndiaRuleDecision, IndiaRuleResult
    from quantx.india.market_checks import IndiaCompatCheck, IndiaSessionCheck

    def garbage(request):
        return IndiaRuleResult(
            IndiaRuleDecision.REJECT,
            "boom without a rule code",
            rule_set_version="test",
            provenance="test",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    regions = tuple(
        _canonical_india_policy()
        if member is MarketRegion.INDIA
        else RegionMarketPolicy(region=member)
        for member in MarketRegion
    )
    config = MarketPolicyConfig(
        regions=regions,
        checks=(
            PlacedCheck(
                MarketRegion.INDIA,
                MarketCheckStage.PRE_DISPATCH,
                IndiaSessionCheck(_india_approving_session()),
            ),
            PlacedCheck(MarketRegion.INDIA, MarketCheckStage.PRE_SUBMIT, IndiaCompatCheck(garbage)),
        ),
    )
    broker = _RecordingBroker(_instrument())
    orchestrator = _live_orchestrator(market_policy=config)
    result = orchestrator.execute(_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "malformed" in result.reason
    assert "boom" not in result.reason
    assert result.check_evidence is not None
    assert result.check_evidence.entries[-1].outcome is MarketCheckOutcome.UNAVAILABLE
    assert broker.submit_calls == 0


# ---------------------------------------------------------------------------
# Fix 3 — runner evidence validation
# ---------------------------------------------------------------------------


def _lying_evidence_check() -> _ToyCheck:
    class _Liar(_ToyCheck):
        def __call__(self, request):
            result = super().__call__(request)
            false_evidence = MarketCheckEvidence(
                check_id=result.check_id,
                stage=MarketCheckStage.PRE_DISPATCH,
                outcome=MarketCheckOutcome.PASS,
                region=MarketRegion.NORTH_AMERICA,
                family=MarketFamily.EQUITY,
                venue="NYSE",
            )
            return MarketCheckResult(
                result.check_id,
                MarketCheckOutcome.BLOCK,
                "toy.pack.rejected",
                "lying check verdict",
                evidence=false_evidence,
            )

    return _Liar("na.liar", MarketCheckOutcome.BLOCK, [])


@pytest.mark.parametrize(
    "tamper",
    ["outcome", "check_id", "stage", "region"],
)
def test_evidence_mismatch_fails_closed(tamper: str) -> None:
    base = MarketCheckEvidence(
        check_id="na.honest",
        stage=MarketCheckStage.PRE_DISPATCH,
        outcome=MarketCheckOutcome.BLOCK,
        region=MarketRegion.NORTH_AMERICA,
        family=MarketFamily.EQUITY,
        venue="NYSE",
    )
    from dataclasses import replace as _replace

    if tamper == "outcome":
        tampered = _replace(base, outcome=MarketCheckOutcome.PASS)
    elif tamper == "check_id":
        tampered = _replace(base, check_id="na.impostor")
    elif tamper == "stage":
        tampered = _replace(base, stage=MarketCheckStage.PRE_SUBMIT)
    else:
        tampered = _replace(base, region=MarketRegion.EUROPE)

    class _TamperingCheck:
        check_id = "na.honest"

        def __call__(self, request):
            return MarketCheckResult(
                "na.honest",
                MarketCheckOutcome.BLOCK,
                "toy.pack.rejected",
                "tampering check verdict",
                evidence=tampered,
            )

    regions = _regions_with_canonical_india(
        RegionMarketPolicy(
            region=MarketRegion.NORTH_AMERICA,
            requires_pack=True,
            required_stages=frozenset({MarketCheckStage.PRE_DISPATCH}),
        )
    )
    config = MarketPolicyConfig(
        regions=regions,
        checks=(
            PlacedCheck(
                MarketRegion.NORTH_AMERICA, MarketCheckStage.PRE_DISPATCH, _TamperingCheck()
            ),
        ),
    )
    orchestrator = _live_orchestrator(market_policy=config)
    result = orchestrator.execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "malformed" in result.reason
    assert result.check_evidence is not None
    assert result.check_evidence.entries[-1].outcome is MarketCheckOutcome.UNAVAILABLE
    assert result.check_evidence.blocking_failure_code == (MarketCheckFailureCode.MALFORMED_RESULT)


def test_block_with_pass_evidence_fails_closed() -> None:
    regions = _regions_with_canonical_india(
        RegionMarketPolicy(
            region=MarketRegion.NORTH_AMERICA,
            requires_pack=True,
            required_stages=frozenset({MarketCheckStage.PRE_DISPATCH}),
        )
    )
    config = MarketPolicyConfig(
        regions=regions,
        checks=(
            PlacedCheck(
                MarketRegion.NORTH_AMERICA, MarketCheckStage.PRE_DISPATCH, _lying_evidence_check()
            ),
        ),
    )
    orchestrator = _live_orchestrator(market_policy=config)
    result = orchestrator.execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is not None
    assert result.check_evidence.entries[-1].outcome is MarketCheckOutcome.UNAVAILABLE


# ---------------------------------------------------------------------------
# Fix 4 — prefix survives later core blocks; Fix 5 — guard ownership
# ---------------------------------------------------------------------------


def test_passed_prefix_survives_session_guard_block() -> None:
    from quantx.execution.session_guard import SessionExecutionGuard

    policy, _ = _toy_policy()
    orchestrator = _live_orchestrator(
        market_policy=policy, session_guard=SessionExecutionGuard(session=_ClosedSession())
    )
    result = orchestrator.execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "closed" in result.reason
    assert result.check_evidence is not None
    assert [entry.check_id for entry in result.check_evidence.entries] == ["NORTH_AMERICA.pre-a"]
    assert result.check_evidence.short_circuited is False


def test_replacing_pack_cannot_disable_session_guard() -> None:
    from quantx.execution.session_guard import SessionExecutionGuard

    policy, _ = _toy_policy(replaces_session_guard=True)
    orchestrator = _live_orchestrator(
        market_policy=policy, session_guard=SessionExecutionGuard(session=_ClosedSession())
    )
    result = orchestrator.execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "closed" in result.reason
    assert result.check_evidence is not None
    assert [entry.check_id for entry in result.check_evidence.entries] == ["NORTH_AMERICA.pre-a"]
