"""Market-pack pre-trade-check pipeline: selection, ordering and evidence.

Covers the neutral contract (ports/market_checks.py) and its wiring
through ExecutionOrchestrator without touching broker submission,
execution/recovery internals, or India-owned result classes from core.
"""

from __future__ import annotations

import ast
import importlib
import json
import sys
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
    MarketRuleCheckEvidence,
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
    """Test-only untrusted pack check with a fixed verdict and call recording.

    Trust is registry-owned, so this check is always untrusted: its reasons
    fall back to runner static messages and its codes are rewritten to the
    framework-owned pack codes.
    """

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
            "toy.pack.unapproved-code",
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
    assert result.reason == "NORTH_AMERICA.pre-a blocked the request"
    assert [call for call in calls] != []
    assert result.check_evidence is not None
    assert [entry.check_id for entry in result.check_evidence.entries] == ["NORTH_AMERICA.pre-a"]
    assert result.check_evidence.blocking_check_id == "NORTH_AMERICA.pre-a"
    assert result.check_evidence.blocking_failure_code == (MarketCheckFailureCode.PACK_BLOCKED)


def test_toy_pb_block_runs_after_broker_checks_before_submit() -> None:
    policy, calls = _toy_policy(pre_submit_outcome=MarketCheckOutcome.BLOCK)
    broker = _RecordingBroker(_us_instrument())
    orchestrator = _live_orchestrator(market_policy=policy)
    result = orchestrator.execute(_us_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "NORTH_AMERICA.pre-b blocked the request"
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

    with pytest.raises(ValueError, match="identifier grammar"):
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
                "toy.pack.unapproved-code",
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
                "toy.pack.unapproved-code",
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


# ---------------------------------------------------------------------------
# Trust policy: untrusted reasons, codes, identifiers
# ---------------------------------------------------------------------------


def _untrusted_check(reason: str, code: str = "toy.pack.unapproved-code"):
    class _Untrusted:
        check_id = "na.untrusted"

        def __call__(self, request):
            return MarketCheckResult(
                "na.untrusted",
                MarketCheckOutcome.BLOCK,
                code,
                reason,
            )

    return _Untrusted()


def _untrusted_policy(check) -> MarketPolicyConfig:
    regions = _regions_with_canonical_india(
        RegionMarketPolicy(
            region=MarketRegion.NORTH_AMERICA,
            requires_pack=True,
            required_stages=frozenset({MarketCheckStage.PRE_DISPATCH}),
        )
    )
    return MarketPolicyConfig(
        regions=regions,
        checks=(PlacedCheck(MarketRegion.NORTH_AMERICA, MarketCheckStage.PRE_DISPATCH, check),),
    )


def test_untrusted_arbitrary_reason_replaced() -> None:
    config = _untrusted_policy(
        _untrusted_check("account overdrawn by internal ledger XJ-99, contact ops"),
    )
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "na.untrusted blocked the request"
    assert "XJ-99" not in result.reason


def test_untrusted_traceback_reason_replaced() -> None:
    config = _untrusted_policy(
        _untrusted_check('boom\nTraceback (most recent call last):\n  File "x.py", line 1'),
    )
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "na.untrusted blocked the request"
    assert "Traceback" not in result.reason
    assert "x.py" not in result.reason


def test_untrusted_filename_reason_replaced() -> None:
    config = _untrusted_policy(_untrusted_check('see File "secrets/vault.py" for details'))
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "na.untrusted blocked the request"
    assert "vault.py" not in result.reason


def test_trusted_b3_reason_still_replaced() -> None:
    class _TrustedB3:
        check_id = "na.trusted"

        def __call__(self, request):
            return MarketCheckResult(
                "na.trusted", MarketCheckOutcome.BLOCK, "toy.pack.unapproved-code", "B3 outage"
            )

    config = _untrusted_policy(_TrustedB3())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "na.trusted blocked the request"
    assert "B3" not in result.reason


def test_self_declared_trust_is_ignored() -> None:
    """A generic check self-declaring ``reasons_sanitized`` gains nothing:
    registry membership, not self-declaration, authorizes trusted reasons."""

    class _SelfTrusted:
        check_id = "na.self-trusted"
        reasons_sanitized = True

        def __call__(self, request):
            return MarketCheckResult(
                "na.self-trusted",
                MarketCheckOutcome.BLOCK,
                "toy.pack.unapproved-code",
                "clean-looking internal ledger note XJ-99",
            )

    config = _untrusted_policy(_SelfTrusted())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "na.self-trusted blocked the request"
    assert "XJ-99" not in result.reason


def test_generic_own_clean_code_is_rewritten() -> None:
    """A generic check's declared-and-returned code is never public: the
    runner rewrites it to the framework-owned pack-blocked code."""

    class _OwnCode:
        check_id = "na.own-code"

        def __call__(self, request):
            return MarketCheckResult(
                "na.own-code", MarketCheckOutcome.BLOCK, "na.my-own-clean-code", "clean reason"
            )

    config = _untrusted_policy(_OwnCode())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "na.my-own-clean-code" not in (result.check_evidence.blocking_failure_code or "")
    assert result.check_evidence.blocking_failure_code == MarketCheckFailureCode.PACK_BLOCKED
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "na.my-own-clean-code" not in payload


def test_batch_code_failure_code_never_exposed() -> None:
    class _BatchCode:
        check_id = "na.batch-code"

        def __call__(self, request):
            return MarketCheckResult(
                "na.batch-code", MarketCheckOutcome.BLOCK, "B3.internal-override", "clean reason"
            )

    config = _untrusted_policy(_BatchCode())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "B3" not in (result.check_evidence.blocking_failure_code or "")
    assert result.check_evidence.blocking_failure_code == MarketCheckFailureCode.PACK_BLOCKED
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "B3" not in payload


def test_malformed_failure_code_characters_rewritten() -> None:
    class _WeirdCode:
        check_id = "na.weird"

        def __call__(self, request):
            return MarketCheckResult("na.weird", MarketCheckOutcome.BLOCK, "has space", "clean")

    config = _untrusted_policy(_WeirdCode())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "has space" not in (result.check_evidence.blocking_failure_code or "")
    assert result.check_evidence.blocking_failure_code == MarketCheckFailureCode.PACK_BLOCKED


def test_trusted_id_impersonation_gets_no_trust() -> None:
    """A caller-defined class registered under a trusted identity (even in
    the INDIA region at the correct stage) is not the approved
    implementation: it is treated as generic — static fallback reason and
    framework-owned rewritten code — and the impersonated identity's
    registered codes never surface."""

    class _RogueIndia:
        check_id = "india.session-calendar"

        def __call__(self, request):
            return MarketCheckResult(
                "india.session-calendar",
                MarketCheckOutcome.BLOCK,
                "india.session-calendar.rejected",
                "india session/calendar blocked the request: XJ-77 evaluator text",
            )

    regions = tuple(
        _canonical_india_policy()
        if member is MarketRegion.INDIA
        else RegionMarketPolicy(region=member)
        for member in MarketRegion
    )
    config = MarketPolicyConfig(
        regions=regions,
        checks=(PlacedCheck(MarketRegion.INDIA, MarketCheckStage.PRE_DISPATCH, _RogueIndia()),),
    )
    result = _live_orchestrator(market_policy=config).execute(_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "india.session-calendar blocked the request"
    assert "XJ-77" not in result.reason
    assert result.check_evidence.blocking_failure_code == MarketCheckFailureCode.PACK_BLOCKED
    assert result.check_evidence.blocking_failure_code != "india.session-calendar.rejected"
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "india.session-calendar.rejected" not in payload


def test_generic_exception_keeps_framework_code() -> None:
    """A generic check exception retains the framework-owned
    EVALUATION_FAILED code; it is not reclassified for being undeclared."""

    class _Exploding:
        check_id = "na.exploding"

        def __call__(self, request):
            raise RuntimeError("pack infrastructure unavailable")

    config = _untrusted_policy(_Exploding())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence.blocking_failure_code == (MarketCheckFailureCode.EVALUATION_FAILED)


@pytest.mark.parametrize(
    "bad_id", ["has space", "line\nbreak", "tab\there", "a/b", "x:y", "B3-evil"]
)
def test_invalid_check_id_rejected_at_registration(bad_id: str) -> None:
    class _BadId:
        check_id = bad_id

        def __call__(self, request):
            return None

    with pytest.raises(ValueError, match="identifier grammar"):
        PlacedCheck(MarketRegion.NORTH_AMERICA, MarketCheckStage.PRE_DISPATCH, _BadId())


@pytest.mark.parametrize(
    "good_id",
    ["india.session-calendar", "india.compatibility-rules", "NORTH_AMERICA.pre-a", "dup", "a"],
)
def test_valid_check_ids_accepted(good_id: str) -> None:
    from quantx.ports.market_checks import is_valid_check_id

    assert is_valid_check_id(good_id) is True


def test_raw_string_outcome_fails_closed() -> None:
    class _RawOutcome:
        check_id = "na.raw"

        def __call__(self, request):
            return MarketCheckResult("na.raw", "BLOCK", "toy.pack.unapproved-code", "clean reason")

    config = _untrusted_policy(_RawOutcome())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is not None
    assert result.check_evidence.blocking_failure_code == (MarketCheckFailureCode.MALFORMED_RESULT)


def test_raw_string_stage_fails_closed() -> None:
    class _RawStage:
        check_id = "na.rawstage"

        def __call__(self, request):
            evidence = MarketCheckEvidence(
                check_id="na.rawstage",
                stage="pre_dispatch",
                outcome=MarketCheckOutcome.BLOCK,
                region=MarketRegion.NORTH_AMERICA,
                family=MarketFamily.EQUITY,
                venue="NYSE",
            )
            return MarketCheckResult(
                "na.rawstage",
                MarketCheckOutcome.BLOCK,
                "toy.pack.unapproved-code",
                "clean",
                evidence=evidence,
            )

    config = _untrusted_policy(_RawStage())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is not None
    assert result.check_evidence.entries[-1].outcome is MarketCheckOutcome.UNAVAILABLE


def test_mismatched_result_check_id_fails_closed() -> None:
    class _Impostor:
        check_id = "na.impostor"

        def __call__(self, request):
            return MarketCheckResult(
                "na.someone-else", MarketCheckOutcome.BLOCK, "toy.pack.unapproved-code", "clean"
            )

    config = _untrusted_policy(_Impostor())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is not None
    assert result.check_evidence.blocking_check_id == "na.impostor"
    assert result.check_evidence.blocking_failure_code == (MarketCheckFailureCode.MALFORMED_RESULT)


def test_synthesized_evidence_serializes() -> None:
    config = _untrusted_policy(_untrusted_check("boom"))
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.check_evidence is not None
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert json.loads(payload)["blocking_failure_code"] == "market-check.pack-blocked"
    assert json.loads(payload)["entries"][0]["outcome"] == "BLOCK"


def test_skipped_stage_code_and_serialization() -> None:
    policy, _ = _toy_policy(optional_submit=True)
    broker = _RecordingBroker(_us_instrument())
    result = _live_orchestrator(market_policy=policy).execute(_us_request(), broker=broker)

    assert result.check_evidence is not None
    skipped = [
        entry
        for entry in result.check_evidence.entries
        if entry.outcome is MarketCheckOutcome.SKIPPED
    ]
    assert len(skipped) == 1
    assert skipped[0].stage_status_code == "market-check.stage-skipped-by-policy"
    assert result.check_evidence.blocking_check_id is None
    assert result.check_evidence.blocking_failure_code is None
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert '"stage_status_code": "market-check.stage-skipped-by-policy"' in payload


def test_ordinary_evidence_rejects_skipped_code() -> None:
    from quantx.ports.market_checks import SKIPPED_STAGE_STATUS_CODE

    with pytest.raises(ValueError, match="only skipped evidence"):
        MarketCheckEvidence(
            check_id="x",
            stage=MarketCheckStage.PRE_DISPATCH,
            outcome=MarketCheckOutcome.PASS,
            region=MarketRegion.NORTH_AMERICA,
            family=MarketFamily.EQUITY,
            venue="NYSE",
            stage_status_code=SKIPPED_STAGE_STATUS_CODE,
        )
    with pytest.raises(ValueError, match="skipped-stage status code"):
        MarketCheckEvidence(
            check_id="x",
            stage=MarketCheckStage.PRE_DISPATCH,
            outcome=MarketCheckOutcome.SKIPPED,
            region=MarketRegion.NORTH_AMERICA,
            family=MarketFamily.EQUITY,
            venue="NYSE",
            stage_status_code="something-else",
        )


# ---------------------------------------------------------------------------
# Registration-snapshot identity binding
# ---------------------------------------------------------------------------


def test_dynamic_check_id_change_fails_closed() -> None:
    """A check whose identifier changes after registration fails closed
    against the registered snapshot; the malformed id never surfaces."""

    class _Shifting:
        check_id = "na.shifted-at-runtime"

        def __call__(self, request):
            return MarketCheckResult(
                "na.impostor-after-registration",
                MarketCheckOutcome.BLOCK,
                "toy.pack.unapproved-code",
                "clean reason",
            )

    config = _untrusted_policy(_Shifting())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is not None
    assert result.check_evidence.entries[-1].outcome is MarketCheckOutcome.UNAVAILABLE
    assert result.check_evidence.blocking_check_id == "na.shifted-at-runtime"
    assert result.check_evidence.blocking_failure_code == (MarketCheckFailureCode.MALFORMED_RESULT)
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "na.impostor-after-registration" not in payload


# ---------------------------------------------------------------------------
# Evidence payload text policy (rule checks, provenance, versions)
# ---------------------------------------------------------------------------


def _compat_policy(rule_evaluator) -> MarketPolicyConfig:
    from quantx.india.market_checks import IndiaCompatCheck, IndiaSessionCheck

    regions = tuple(
        _canonical_india_policy()
        if member is MarketRegion.INDIA
        else RegionMarketPolicy(region=member)
        for member in MarketRegion
    )
    return MarketPolicyConfig(
        regions=regions,
        checks=(
            PlacedCheck(
                MarketRegion.INDIA,
                MarketCheckStage.PRE_DISPATCH,
                IndiaSessionCheck(_india_approving_session()),
            ),
            PlacedCheck(
                MarketRegion.INDIA, MarketCheckStage.PRE_SUBMIT, IndiaCompatCheck(rule_evaluator)
            ),
        ),
    )


def test_rule_level_banned_text_sanitized() -> None:
    """An allow-listed aggregate rejection with a banned rule-level reason
    blocks with the approved reason; serialized evidence carries only the
    fixed withheld text."""
    from quantx.india.execution_rules import IndiaRuleCheck, IndiaRuleDecision, IndiaRuleResult

    def evaluator(request):
        return IndiaRuleResult(
            IndiaRuleDecision.REJECT,
            "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            checks=(
                IndiaRuleCheck("lot", False, "B3 bucket mismatch for unit 42"),
                IndiaRuleCheck("tick", True, "tick size ok"),
            ),
            rule_set_version="test",
            provenance="test",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    broker = _RecordingBroker(_instrument())
    result = _live_orchestrator(market_policy=_compat_policy(evaluator)).execute(
        _request(), broker=broker
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "INDIA_LOT_SIZE_INVALID" in result.reason
    assert broker.submit_calls == 0
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "B3" not in payload
    assert '"reason": "india rule check failed (details withheld)"' in payload
    assert '"reason": "india rule check passed"' in payload


def test_rule_level_untrusted_text_sanitized() -> None:
    """Clean-looking but unapproved rule-level text is replaced by the fixed
    withheld message; the allow-listed aggregate reason is preserved."""
    from quantx.india.execution_rules import IndiaRuleCheck, IndiaRuleDecision, IndiaRuleResult

    def evaluator(request):

        return IndiaRuleResult(
            IndiaRuleDecision.REJECT,
            "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            checks=(IndiaRuleCheck("lot", False, "internal margin ledger XJ-99 note"),),
            rule_set_version="test",
            provenance="test",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    broker = _RecordingBroker(_instrument())
    result = _live_orchestrator(market_policy=_compat_policy(evaluator)).execute(
        _request(), broker=broker
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "INDIA_LOT_SIZE_INVALID" in result.reason
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "XJ-99" not in payload
    assert '"reason": "india rule check failed (details withheld)"' in payload


def test_evidence_provenance_metadata_gated() -> None:
    """Banned provenance/version metadata is dropped from public evidence."""
    from quantx.india.execution_rules import IndiaRuleCheck, IndiaRuleDecision, IndiaRuleResult

    def evaluator(request):
        return IndiaRuleResult(
            IndiaRuleDecision.REJECT,
            "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            checks=(IndiaRuleCheck("lot", False, "INDIA_LOT_SIZE_INVALID: nope"),),
            rule_set_version="rules-v1",
            provenance='File "secret.py" leak',
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    broker = _RecordingBroker(_instrument())
    result = _live_orchestrator(market_policy=_compat_policy(evaluator)).execute(
        _request(), broker=broker
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is not None
    compat_entries = [
        entry
        for entry in result.check_evidence.entries
        if entry.check_id == "india.compatibility-rules"
    ]
    assert len(compat_entries) == 1
    assert compat_entries[0].provenance is None
    assert compat_entries[0].rule_set_version == "rules-v1"
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "secret.py" not in payload


def test_session_rejection_untrusted_text_normalized() -> None:
    """A session evaluator returning clean but unapproved text is normalized
    to the static template without interpolating the evaluator text."""

    from quantx.india.domain import IndianExchange, IndianSegment
    from quantx.india.session_calendar import IndiaSessionDecision, IndiaSessionResult

    def closed(request):
        return IndiaSessionResult(
            IndiaSessionDecision.BLOCK,
            "venue ops note XJ-42: session halted",
            calendar_version="test-calendar-v1",
            provenance="test-calendar",
            evaluated_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
            calendar_evaluated=True,
        )

    from quantx.india.market_checks import india_market_policy

    config = india_market_policy(session_evaluator=closed)
    result = _live_orchestrator(market_policy=config).execute(_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "india session/calendar blocked the request"
    assert "XJ-42" not in result.reason


def test_session_rejection_approved_message_preserved() -> None:
    """The approved plain session rejection stays intelligible."""

    from quantx.india.domain import IndianExchange, IndianSegment
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

    from quantx.india.market_checks import india_market_policy

    config = india_market_policy(session_evaluator=closed)
    result = _live_orchestrator(market_policy=config).execute(_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert (
        result.reason
        == "india session/calendar blocked the request: india trading session is closed"
    )


# ---------------------------------------------------------------------------
# Trusted-identity impersonation (binding enforcement)
# ---------------------------------------------------------------------------


def test_impersonation_wrong_region_is_untrusted() -> None:
    """A generic check registered in NORTH_AMERICA under the trusted India
    session identity gets no trust: static reason, framework code."""

    class _ImpostorSession:
        check_id = "india.session-calendar"

        def __call__(self, request):
            return MarketCheckResult(
                "india.session-calendar",
                MarketCheckOutcome.BLOCK,
                "india.session-calendar.rejected",
                "india session/calendar blocked the request",
            )

    config = _untrusted_policy(_ImpostorSession())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "india.session-calendar blocked the request"
    assert result.check_evidence.blocking_failure_code == MarketCheckFailureCode.PACK_BLOCKED
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "india.session-calendar.rejected" not in payload


def test_impersonation_compat_identity_is_untrusted() -> None:
    """A generic check attempting to impersonate the India compatibility
    identity receives only safe static output."""

    class _ImpostorCompat:
        check_id = "india.compatibility-rules"

        def __call__(self, request):
            return MarketCheckResult(
                "india.compatibility-rules",
                MarketCheckOutcome.BLOCK,
                "india.compatibility.rejected",
                "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            )

    config = _untrusted_policy(_ImpostorCompat())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "india.compatibility-rules blocked the request"
    assert "INDIA_LOT_SIZE_INVALID" not in result.reason
    assert result.check_evidence.blocking_failure_code == MarketCheckFailureCode.PACK_BLOCKED
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "INDIA_LOT_SIZE_INVALID" not in payload


def test_impersonation_wrong_stage_is_untrusted() -> None:
    """The India compatibility identity is bound to PRE_SUBMIT: the same
    caller-defined class placed at PRE_DISPATCH in INDIA is untrusted."""

    class _ImpostorStage:
        check_id = "india.compatibility-rules"

        def __call__(self, request):
            return MarketCheckResult(
                "india.compatibility-rules",
                MarketCheckOutcome.BLOCK,
                "india.compatibility.rejected",
                "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            )

    regions = tuple(
        _canonical_india_policy()
        if member is MarketRegion.INDIA
        else RegionMarketPolicy(region=member)
        for member in MarketRegion
    )
    config = MarketPolicyConfig(
        regions=regions,
        checks=(PlacedCheck(MarketRegion.INDIA, MarketCheckStage.PRE_DISPATCH, _ImpostorStage()),),
    )
    result = _live_orchestrator(market_policy=config).execute(_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "india.compatibility-rules blocked the request"
    assert "INDIA_LOT_SIZE_INVALID" not in result.reason
    assert result.check_evidence.blocking_failure_code == MarketCheckFailureCode.PACK_BLOCKED


# ---------------------------------------------------------------------------
# Wrong-type metadata fail-closed behavior
# ---------------------------------------------------------------------------


def _evidence_with_metadata(provenance, rule_set_version) -> MarketCheckEvidence:
    """Build evidence carrying wrong-typed metadata without constructor
    validation (dataclasses do not enforce annotations at runtime)."""
    evidence = MarketCheckEvidence(
        check_id="na.meta",
        stage=MarketCheckStage.PRE_DISPATCH,
        outcome=MarketCheckOutcome.BLOCK,
        region=MarketRegion.NORTH_AMERICA,
        family=MarketFamily.EQUITY,
        venue="NYSE",
    )
    object.__setattr__(evidence, "provenance", provenance)
    object.__setattr__(evidence, "rule_set_version", rule_set_version)
    return evidence


@pytest.mark.parametrize(
    "provenance,version",
    [
        (123, "v1"),
        ("prov", 456),
        (1.5, None),
        (None, b"bytes-version"),
        (["list"], {"dict": 1}),
    ],
)
def test_wrong_type_metadata_fails_closed(provenance, version) -> None:
    class _BadMetadata:
        check_id = "na.meta"

        def __call__(self, request):
            return MarketCheckResult(
                "na.meta",
                MarketCheckOutcome.BLOCK,
                "toy.pack.unapproved-code",
                "clean reason",
                evidence=_evidence_with_metadata(provenance, version),
            )

    config = _untrusted_policy(_BadMetadata())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is not None
    assert result.check_evidence.entries[-1].outcome is MarketCheckOutcome.UNAVAILABLE
    assert result.check_evidence.blocking_failure_code == (MarketCheckFailureCode.MALFORMED_RESULT)
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert json.loads(payload)["blocking_failure_code"] == "market-check.malformed-result"


# ---------------------------------------------------------------------------
# India rule-name grammar normalization
# ---------------------------------------------------------------------------


def test_india_rule_name_unapproved_normalized() -> None:
    """Clean but unapproved rule names collapse to the fixed ``india-rule``
    identity; the allow-listed aggregate reason is preserved."""

    def evaluator(request):
        from quantx.india.execution_rules import (
            IndiaRuleCheck,
            IndiaRuleDecision,
            IndiaRuleResult,
        )

        return IndiaRuleResult(
            IndiaRuleDecision.REJECT,
            "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            checks=(
                IndiaRuleCheck("Lot-Size XJ-9", False, "INDIA_LOT_SIZE_INVALID: bad lot"),
                IndiaRuleCheck("tick", True, "tick size ok"),
            ),
            rule_set_version="rules-v1",
            provenance="test-venue",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    broker = _RecordingBroker(_instrument())
    result = _live_orchestrator(market_policy=_compat_policy(evaluator)).execute(
        _request(), broker=broker
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "INDIA_LOT_SIZE_INVALID" in result.reason
    assert broker.submit_calls == 0
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "Lot-Size" not in payload
    assert "XJ-9" not in payload
    assert '"name": "india-rule"' in payload
    assert '"name": "tick"' in payload


def test_generic_evidence_metadata_never_serialized() -> None:
    """A generic check's consistent evidence is normalized: clean-looking
    but unapproved metadata and rule facts never reach serialization."""

    class _ChattyEvidence:
        check_id = "na.chatty"

        def __call__(self, request):
            evidence = MarketCheckEvidence(
                check_id="na.chatty",
                stage=MarketCheckStage.PRE_DISPATCH,
                outcome=MarketCheckOutcome.BLOCK,
                region=MarketRegion.NORTH_AMERICA,
                family=MarketFamily.EQUITY,
                venue="NYSE",
                rule_set_version="private-rules-v9",
                provenance="internal-desk-note",
                compatibility_evaluated=True,
                rule_checks=(
                    MarketRuleCheckEvidence("desk_rule", False, "desk threshold breached"),
                ),
            )
            return MarketCheckResult(
                "na.chatty",
                MarketCheckOutcome.BLOCK,
                "toy.pack.unapproved-code",
                "clean",
                evidence=evidence,
            )

    config = _untrusted_policy(_ChattyEvidence())
    result = _live_orchestrator(market_policy=config).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is not None
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "private-rules-v9" not in payload
    assert "internal-desk-note" not in payload
    assert "desk_rule" not in payload
    assert "desk threshold breached" not in payload
    assert '"check_id": "na.chatty"' in payload
    assert '"outcome": "BLOCK"' in payload


# ---------------------------------------------------------------------------
# Implementation-identity binding (module-string spoofing)
# ---------------------------------------------------------------------------


def _india_pre_dispatch_policy(*checks) -> MarketPolicyConfig:
    """India policy whose PRE_DISPATCH stage runs the given checks in order."""
    regions = tuple(
        _canonical_india_policy()
        if member is MarketRegion.INDIA
        else RegionMarketPolicy(region=member)
        for member in MarketRegion
    )
    return MarketPolicyConfig(
        regions=regions,
        checks=tuple(
            PlacedCheck(MarketRegion.INDIA, MarketCheckStage.PRE_DISPATCH, check)
            for check in checks
        ),
    )


def test_spoofed_module_identity_gains_no_trust() -> None:
    """A caller-defined class that spoofs an approved ``__module__`` stays
    untrusted: the runner compares the class object itself, so an
    approved-looking module string proves nothing. It gets the static public
    reason and a framework-owned failure code, and neither the India reason
    nor failure-code allow-list becomes available to it."""

    class _SpoofedModule:
        check_id = "india.session-calendar"

        def __call__(self, request):
            return MarketCheckResult(
                "india.session-calendar",
                MarketCheckOutcome.BLOCK,
                "india.session-calendar.rejected",
                "india session/calendar blocked the request: XJ-77 evaluator text",
            )

    _SpoofedModule.__module__ = "quantx.india.market_checks"

    from quantx.ports.market_checks import is_trusted_check

    assert (
        is_trusted_check(
            "india.session-calendar",
            _SpoofedModule(),
            region=MarketRegion.INDIA,
            stage=MarketCheckStage.PRE_DISPATCH,
        )
        is False
    )

    config = _india_pre_dispatch_policy(_SpoofedModule())
    result = _live_orchestrator(market_policy=config).execute(_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "india.session-calendar blocked the request"
    assert "XJ-77" not in result.reason
    assert result.check_evidence.blocking_failure_code == MarketCheckFailureCode.PACK_BLOCKED
    assert result.check_evidence.blocking_failure_code != "india.session-calendar.rejected"
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "india.session-calendar.rejected" not in payload


def test_hijacked_approved_attribute_gains_no_trust(monkeypatch) -> None:
    """Repointing the approved module attribute at a caller-defined class
    fails closed: the core cross-checks that the resolved class really is
    defined in the approved module before comparing identity."""
    import quantx.india.market_checks as india_checks
    from quantx.ports.market_checks import is_trusted_check

    class _Hijacked:
        check_id = "india.session-calendar"

        def __call__(self, request):
            raise AssertionError("an untrusted check must never be trusted")

    monkeypatch.setattr(india_checks, "IndiaSessionCheck", _Hijacked)
    try:
        assert (
            is_trusted_check(
                "india.session-calendar",
                _Hijacked(),
                region=MarketRegion.INDIA,
                stage=MarketCheckStage.PRE_DISPATCH,
            )
            is False
        )
    finally:
        # Drop any resolution cached while the approved name pointed at the
        # hijacked class so the approved adapter stays trusted afterwards.
        importlib.import_module("quantx.ports.market_checks")._approved_implementation.cache_clear()


def test_subclass_of_approved_implementation_gains_no_trust() -> None:
    """Trust is class-object identity, not inheritance: a subclass of the
    approved adapter is still an unreviewed implementation."""
    from quantx.india.market_checks import IndiaSessionCheck
    from quantx.ports.market_checks import is_trusted_check

    class _DerivedSessionCheck(IndiaSessionCheck):
        pass

    assert (
        is_trusted_check(
            "india.session-calendar",
            _DerivedSessionCheck(_india_approving_session()),
            region=MarketRegion.INDIA,
            stage=MarketCheckStage.PRE_DISPATCH,
        )
        is False
    )


def test_approved_implementations_remain_trusted() -> None:
    """The identity binding is satisfied by the real approved adapters, and
    a placement that does not match the binding is still untrusted."""
    from quantx.india.market_checks import IndiaCompatCheck, IndiaSessionCheck
    from quantx.ports.market_checks import is_trusted_check

    assert (
        is_trusted_check(
            "india.session-calendar",
            IndiaSessionCheck(_india_approving_session()),
            region=MarketRegion.INDIA,
            stage=MarketCheckStage.PRE_DISPATCH,
        )
        is True
    )
    assert (
        is_trusted_check(
            "india.compatibility-rules",
            IndiaCompatCheck(lambda request: None),
            region=MarketRegion.INDIA,
            stage=MarketCheckStage.PRE_SUBMIT,
        )
        is True
    )
    assert (
        is_trusted_check(
            "india.session-calendar",
            IndiaSessionCheck(_india_approving_session()),
            region=MarketRegion.NORTH_AMERICA,
            stage=MarketCheckStage.PRE_DISPATCH,
        )
        is False
    )


# ---------------------------------------------------------------------------
# Immutable trust registries
# ---------------------------------------------------------------------------


class _RegistryMutator:
    """Untrusted check that tries to widen the core trust registries."""

    check_id = "na.registry-mutator"

    def __init__(self) -> None:
        self.refused: list[str] = []

    def __call__(self, request) -> MarketCheckResult:
        core = importlib.import_module("quantx.ports.market_checks")
        binding = core.TRUSTED_CHECK_BINDINGS["india.session-calendar"]
        attempts = (
            (
                "failure-codes-add-identity",
                lambda: core.TRUSTED_FAILURE_CODES.__setitem__(
                    "na.later", frozenset({"na.attacker-code"})
                ),
            ),
            (
                "failure-codes-add-code",
                lambda: core.TRUSTED_FAILURE_CODES["india.session-calendar"].add(
                    "na.attacker-code"
                ),
            ),
            (
                "bindings-add-identity",
                lambda: core.TRUSTED_CHECK_BINDINGS.__setitem__("na.later", binding),
            ),
            ("bindings-pop", lambda: core.TRUSTED_CHECK_BINDINGS.pop("india.session-calendar")),
            ("bindings-widen-region", lambda: binding.regions.add(MarketRegion.NORTH_AMERICA)),
            (
                "bindings-rebind-implementation",
                lambda: binding.implementation.__setattr__("module", "attacker"),
            ),
        )
        for label, attempt in attempts:
            try:
                attempt()
            except (TypeError, AttributeError, KeyError):
                self.refused.append(label)
        return MarketCheckResult(self.check_id, MarketCheckOutcome.PASS, None, "registries widened")


def test_registry_mutation_refused_and_registries_unchanged() -> None:
    """A generic check cannot widen the trust registries: every mutation is
    refused and the approved India registries keep exactly their codes."""
    from quantx.ports.market_checks import TRUSTED_FAILURE_CODES, trusted_failure_codes

    mutator = _RegistryMutator()
    result = _live_orchestrator(market_policy=_untrusted_policy(mutator)).execute(_us_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "broker adapter" in result.reason
    assert mutator.refused == [
        "failure-codes-add-identity",
        "failure-codes-add-code",
        "bindings-add-identity",
        "bindings-pop",
        "bindings-widen-region",
        "bindings-rebind-implementation",
    ]
    assert trusted_failure_codes("na.later") is None
    assert "na.later" not in TRUSTED_FAILURE_CODES
    assert "na.attacker-code" not in set().union(*TRUSTED_FAILURE_CODES.values())
    assert trusted_failure_codes("india.session-calendar") == frozenset(
        {
            "india.session-calendar.evaluation-failed",
            "india.session-calendar.evidence-missing",
            "india.session-calendar.rejected",
        }
    )


def test_registry_mutation_does_not_confer_trust_on_later_check() -> None:
    """The later check runs after the mutator in the same stage and still
    acquires no trusted reason or failure-code permission."""
    mutator = _RegistryMutator()

    class _Later:
        check_id = "na.later"

        def __call__(self, request) -> MarketCheckResult:
            return MarketCheckResult(
                "na.later",
                MarketCheckOutcome.BLOCK,
                "na.attacker-code",
                "clean internal desk note XJ-31",
            )

    config = _india_pre_dispatch_policy(mutator, _Later())
    result = _live_orchestrator(market_policy=config).execute(_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "na.later blocked the request"
    assert "XJ-31" not in result.reason
    assert result.check_evidence.blocking_failure_code == MarketCheckFailureCode.PACK_BLOCKED
    assert result.check_evidence.blocking_check_id == "na.later"
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "na.attacker-code" not in payload


def _closed_session_evaluator():
    from quantx.india.domain import IndianExchange, IndianSegment
    from quantx.india.session_calendar import IndiaSessionDecision, IndiaSessionResult

    def closed(request) -> IndiaSessionResult:
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

    return closed


def test_approved_india_behavior_survives_registry_mutator() -> None:
    """Approved India reasons and codes stay reachable after an untrusted
    check has attempted registry writes."""
    from quantx.india.market_checks import india_market_policy

    base = india_market_policy(session_evaluator=_closed_session_evaluator())
    config = MarketPolicyConfig(
        regions=base.regions,
        checks=(
            PlacedCheck(MarketRegion.INDIA, MarketCheckStage.PRE_DISPATCH, _RegistryMutator()),
            *base.checks,
        ),
    )
    result = _live_orchestrator(market_policy=config).execute(_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert (
        result.reason
        == "india session/calendar blocked the request: india trading session is closed"
    )
    assert result.check_evidence.blocking_failure_code == "india.session-calendar.rejected"


def test_execution_ignores_rebound_registry_aliases(monkeypatch) -> None:
    """The runner resolves trust through core accessors that read the
    private immutable registry, so rebinding the public module aliases
    cannot change what a check is authorized to return."""
    from quantx.india.market_checks import IndiaSessionCheck
    from quantx.ports.market_checks import trusted_failure_codes

    core = importlib.import_module("quantx.ports.market_checks")
    monkeypatch.setattr(core, "TRUSTED_FAILURE_CODES", {"india.session-calendar": frozenset()})
    monkeypatch.setattr(core, "TRUSTED_CHECK_BINDINGS", {})

    assert trusted_failure_codes("india.session-calendar") == frozenset(
        {
            "india.session-calendar.evaluation-failed",
            "india.session-calendar.evidence-missing",
            "india.session-calendar.rejected",
        }
    )

    config = _india_pre_dispatch_policy(IndiaSessionCheck(_closed_session_evaluator()))
    result = _live_orchestrator(market_policy=config).execute(_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence.blocking_failure_code == "india.session-calendar.rejected"


# ---------------------------------------------------------------------------
# Approved India codes must not license arbitrary trailing text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason",
    [
        "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25 "
        "and desk note XJ-99 applied",
        "INDIA_QUANTITY_INVALID: quantity must be a positive number "
        "(override granted by the trading desk)",
        "INDIA_RULE_DATA_UNAVAILABLE: venue rule scope is unknown pending internal review XJ-99",
        "INDIA_SESSION_SCOPE_MISMATCH: calendar exchange does not match "
        "request market - escalation XJ-99",
        "INDIA_PRICE_BAND_INVALID: price 120 is outside [90, 110]; see the desk note",
    ],
)
def test_approved_code_with_unapproved_suffix_is_withheld(reason: str) -> None:
    """An approved rule code does not license arbitrary trailing text: the
    message must match the code's trusted template exactly, so the suffix
    reaches neither the public reason nor the serialized evidence."""
    from quantx.india.execution_rules import IndiaRuleCheck, IndiaRuleDecision, IndiaRuleResult

    def evaluator(request):
        return IndiaRuleResult(
            IndiaRuleDecision.REJECT,
            reason,
            checks=(IndiaRuleCheck("quantity", False, reason),),
            rule_set_version="rules-v1",
            provenance="test-venue",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    broker = _RecordingBroker(_instrument())
    result = _live_orchestrator(market_policy=_compat_policy(evaluator)).execute(
        _request(), broker=broker
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "india rule evidence is malformed"
    for fragment in ("XJ-99", "trading desk", "escalation", "desk note"):
        assert fragment not in result.reason
    assert broker.submit_calls == 0
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    for fragment in ("XJ-99", "trading desk", "escalation", "desk note"):
        assert fragment not in payload
    assert '"reason": "india rule check failed (details withheld)"' in payload


def test_approved_lot_size_message_stays_byte_identical() -> None:
    """The established INDIA_LOT_SIZE_INVALID rejection format is preserved
    byte for byte for a valid message."""
    from quantx.india.execution_rules import IndiaRuleDecision, IndiaRuleResult

    def evaluator(request):
        return IndiaRuleResult(
            IndiaRuleDecision.REJECT,
            "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            rule_set_version="rules-v1",
            provenance="test-venue",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    broker = _RecordingBroker(_instrument())
    result = _live_orchestrator(market_policy=_compat_policy(evaluator)).execute(
        _request(), broker=broker
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert (
        result.reason == "india execution rules rejected the request: "
        "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25"
    )
    assert broker.submit_calls == 0


# ---------------------------------------------------------------------------
# Unapproved-but-clean trusted evidence values
# ---------------------------------------------------------------------------


def _unapproved_values_evaluator(version: str, provenance: str):
    from quantx.india.execution_rules import IndiaRuleCheck, IndiaRuleDecision, IndiaRuleResult

    def evaluator(request):
        return IndiaRuleResult(
            IndiaRuleDecision.REJECT,
            "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            checks=(IndiaRuleCheck("quantity", False, "quantity is not lot aligned"),),
            rule_set_version=version,
            provenance=provenance,
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    return evaluator


@pytest.mark.parametrize(
    "version,provenance,version_dropped,provenance_dropped",
    [
        (
            "rules v1 (draft)",
            "internal desk note for the NSE equity rule book",
            True,
            True,
        ),
        ("rules-v1", "provenance written as a sentence with spaces", False, True),
        ("RULES-V1-" + "FINAL-LONGSUFFIX" * 4, "test-venue", True, False),
    ],
)
def test_clean_but_unapproved_metadata_is_dropped(
    version: str, provenance: str, version_dropped: bool, provenance_dropped: bool
) -> None:
    """Provenance and rule-set versions must match their token schemas: a
    clean-looking sentence is still unreviewed text and is dropped, while
    the evidence structure and approved values survive."""
    config = _compat_policy(_unapproved_values_evaluator(version, provenance))
    result = _live_orchestrator(market_policy=config).execute(
        _request(), broker=_RecordingBroker(_instrument())
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "INDIA_LOT_SIZE_INVALID" in result.reason
    assert result.check_evidence is not None
    entry = result.check_evidence.entries[-1]
    assert entry.check_id == "india.compatibility-rules"
    assert entry.outcome is MarketCheckOutcome.BLOCK
    assert entry.rule_checks[0].name == "quantity"
    assert (entry.rule_set_version is None) is version_dropped
    assert (entry.provenance is None) is provenance_dropped
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert '"check_id": "india.compatibility-rules"' in payload
    for fragment in ("desk note", "FINAL-LONGSUFFIX", "draft"):
        assert fragment not in payload


def test_unapproved_rule_name_collapses_and_approved_values_survive() -> None:
    """A clean arbitrary snake_case rule name is not a recognized rule and
    collapses to the fixed identity, while approved names, the approved
    version token, and the fixed rule reasons keep the structure intact."""
    from quantx.india.execution_rules import IndiaRuleCheck, IndiaRuleDecision, IndiaRuleResult

    def evaluator(request):
        return IndiaRuleResult(
            IndiaRuleDecision.REJECT,
            "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            checks=(
                IndiaRuleCheck("quantity", False, "quantity is not lot aligned"),
                IndiaRuleCheck("desk_internal_risk_rule", False, "internal desk threshold"),
            ),
            rule_set_version="rules-v1",
            provenance="test-venue",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    result = _live_orchestrator(market_policy=_compat_policy(evaluator)).execute(
        _request(), broker=_RecordingBroker(_instrument())
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is not None
    entry = result.check_evidence.entries[-1]
    assert [check.name for check in entry.rule_checks] == ["quantity", "india-rule"]
    assert entry.rule_set_version == "rules-v1"
    assert entry.provenance == "test-venue"
    assert [check.reason for check in entry.rule_checks] == [
        "india rule check failed (details withheld)",
        "india rule check failed (details withheld)",
    ]
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "desk_internal_risk_rule" not in payload
    assert "internal desk threshold" not in payload
    assert '"name": "quantity"' in payload


def test_approved_rule_code_prefix_with_unapproved_reason_suffix_withheld() -> None:
    """A rule fact whose reason heads an approved code but appends
    unapproved text keeps the entry structure while withholding the text."""
    from quantx.india.execution_rules import IndiaRuleCheck, IndiaRuleDecision, IndiaRuleResult

    def evaluator(request):
        return IndiaRuleResult(
            IndiaRuleDecision.REJECT,
            "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            checks=(
                IndiaRuleCheck(
                    "quantity",
                    False,
                    "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25 "
                    "per desk note XJ-99",
                ),
            ),
            rule_set_version="rules-v1",
            provenance="test-venue",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    result = _live_orchestrator(market_policy=_compat_policy(evaluator)).execute(
        _request(), broker=_RecordingBroker(_instrument())
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is not None
    entry = result.check_evidence.entries[-1]
    assert entry.rule_checks[0].name == "quantity"
    assert entry.rule_checks[0].reason == "india rule check failed (details withheld)"
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "XJ-99" not in payload


def test_binding_object_writes_do_not_widen_trust(monkeypatch) -> None:
    """Frozen dataclasses still accept ``object.__setattr__`` writes, so
    the core never hands out its canonical binding objects: writes against
    the public view — including pointing the implementation at a resolvable
    caller-defined class — leave the registry unchanged and the rogue
    untrusted end to end."""
    from quantx.ports.market_checks import is_trusted_check, trusted_check_binding

    class _EvilCompat:
        check_id = "india.compatibility-rules"

        def __call__(self, request) -> MarketCheckResult:
            return MarketCheckResult(
                "india.compatibility-rules",
                MarketCheckOutcome.BLOCK,
                "india.compatibility.rejected",
                "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            )

    # Make the rogue resolvable as a module attribute, so that only the
    # binding — not resolution — stands between it and trust.
    monkeypatch.setattr(sys.modules[__name__], "_EvilCompat", _EvilCompat, raising=False)
    core = importlib.import_module("quantx.ports.market_checks")
    evil = core.TrustedCheckImplementation(_EvilCompat.__module__, "_EvilCompat")

    binding = core.TRUSTED_CHECK_BINDINGS["india.compatibility-rules"]
    object.__setattr__(binding, "stage", MarketCheckStage.PRE_DISPATCH)
    object.__setattr__(binding, "implementation", evil)

    assert trusted_check_binding("india.compatibility-rules").stage is (MarketCheckStage.PRE_SUBMIT)
    assert (
        is_trusted_check(
            "india.compatibility-rules",
            _EvilCompat(),
            region=MarketRegion.INDIA,
            stage=MarketCheckStage.PRE_SUBMIT,
        )
        is False
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
                _ToyCheck("na.pass", MarketCheckOutcome.PASS, []),
            ),
            PlacedCheck(MarketRegion.INDIA, MarketCheckStage.PRE_SUBMIT, _EvilCompat()),
        ),
    )
    broker = _RecordingBroker(_instrument())
    result = _live_orchestrator(market_policy=config).execute(_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "india.compatibility-rules blocked the request"
    assert "INDIA_LOT_SIZE_INVALID" not in result.reason
    assert result.check_evidence.blocking_check_id == "india.compatibility-rules"
    assert result.check_evidence.blocking_failure_code == MarketCheckFailureCode.PACK_BLOCKED
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert "india.compatibility.rejected" not in payload


# ---------------------------------------------------------------------------
# Malformed evidence fails closed (runtime shape contract)
# ---------------------------------------------------------------------------


def _na_block_evidence(**overrides) -> MarketCheckEvidence:
    """Structurally consistent BLOCK evidence for the toy region and stage."""
    values: dict = {
        "check_id": "na.malformed",
        "stage": MarketCheckStage.PRE_DISPATCH,
        "outcome": MarketCheckOutcome.BLOCK,
        "region": MarketRegion.NORTH_AMERICA,
        "family": MarketFamily.EQUITY,
        "venue": "NYSE",
    }
    values.update(overrides)
    return MarketCheckEvidence(**values)


def _evidence_check(evidence: MarketCheckEvidence):
    class _Malformed:
        check_id = "na.malformed"

        def __call__(self, request) -> MarketCheckResult:
            return MarketCheckResult(
                "na.malformed",
                MarketCheckOutcome.BLOCK,
                "toy.pack.unapproved-code",
                "clean",
                evidence=evidence,
            )

    return _Malformed()


def _run_na_evidence(evidence: MarketCheckEvidence):
    config = _untrusted_policy(_evidence_check(evidence))
    return _live_orchestrator(market_policy=config).execute(_us_request())


def _assert_malformed(result, *absent: str) -> str:
    """Malformed evidence must synthesize a safe entry: BLOCKED with an
    UNAVAILABLE entry and the framework-owned MALFORMED_RESULT code, and
    none of the given fragments may reach the serialized payload."""
    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is not None
    entry = result.check_evidence.entries[-1]
    assert entry.outcome is MarketCheckOutcome.UNAVAILABLE
    assert entry.session_evaluated is False
    assert entry.compatibility_evaluated is False
    assert result.check_evidence.blocking_failure_code == (MarketCheckFailureCode.MALFORMED_RESULT)
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    for fragment in absent:
        assert fragment not in payload
    return payload


@pytest.mark.parametrize("rule_checks", [None, 123, ["quantity"]])
def test_non_tuple_rule_checks_fail_closed(rule_checks) -> None:
    """A non-tuple rule_checks container cannot be iterated as facts: the
    runner synthesizes safe evidence instead of raising."""
    result = _run_na_evidence(_na_block_evidence(rule_checks=rule_checks))
    _assert_malformed(result)


@pytest.mark.parametrize("entry", ["not-a-fact", 123, None])
def test_malformed_rule_check_entries_fail_closed(entry) -> None:
    """Entries that are not rule-check facts are rejected; the aggregate
    reason never reaches the public record."""
    result = _run_na_evidence(_na_block_evidence(rule_checks=(entry,)))
    _assert_malformed(result, "not-a-fact")


@pytest.mark.parametrize("field,value", [("name", 123), ("reason", 123)])
def test_non_string_rule_fact_text_fails_closed(field, value) -> None:
    """Non-string fact text must fail closed before the banned-text scan,
    which would otherwise raise on a non-string input."""
    fact = MarketRuleCheckEvidence("quantity", True, "tick size ok")
    object.__setattr__(fact, field, value)
    result = _run_na_evidence(_na_block_evidence(rule_checks=(fact,)))
    _assert_malformed(result)


@pytest.mark.parametrize("passed", [1, 0, "yes", None])
def test_non_bool_passed_fails_closed_generic(passed) -> None:
    """A truthy/falsey non-Boolean verdict is not a verdict: the entry is
    rejected and no contradictory fact serializes."""
    fact = MarketRuleCheckEvidence("quantity", passed, "tick size ok")
    result = _run_na_evidence(_na_block_evidence(rule_checks=(fact,)))
    payload = _assert_malformed(result)
    assert '"rule_checks": []' in payload


@pytest.mark.parametrize("passed", [1, 0, "yes", None])
def test_india_evaluator_non_bool_passed_fails_closed(passed) -> None:
    """A non-Boolean verdict from the India evaluator cannot serialize a
    contradictory public fact, even when the reason itself is approved."""
    from quantx.india.execution_rules import IndiaRuleCheck, IndiaRuleDecision, IndiaRuleResult

    def evaluator(request):
        return IndiaRuleResult(
            IndiaRuleDecision.REJECT,
            "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            checks=(
                IndiaRuleCheck(
                    "quantity",
                    passed,
                    "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
                ),
            ),
            rule_set_version="rules-v1",
            provenance="test-venue",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    broker = _RecordingBroker(_instrument())
    result = _live_orchestrator(market_policy=_compat_policy(evaluator)).execute(
        _request(), broker=broker
    )

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.check_evidence is not None
    assert result.check_evidence.entries[-1].outcome is MarketCheckOutcome.UNAVAILABLE
    assert result.check_evidence.blocking_failure_code == (MarketCheckFailureCode.MALFORMED_RESULT)
    assert broker.submit_calls == 0
    payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
    assert '"rule_checks": []' in payload


def test_naive_evaluated_at_rejected() -> None:
    """A timezone-naive timestamp cannot reach serialized evidence."""
    evidence = _na_block_evidence()
    object.__setattr__(evidence, "evaluated_at", datetime(2026, 1, 1, 9, 30))
    result = _run_na_evidence(evidence)
    _assert_malformed(result)


@pytest.mark.parametrize("field", ["session_evaluated", "compatibility_evaluated"])
def test_non_bool_session_flags_rejected(field) -> None:
    """Session flags must be actual Booleans; a truthy string cannot mark
    unevaluated evidence as evaluated."""
    evidence = _na_block_evidence()
    object.__setattr__(evidence, field, "yes")
    result = _run_na_evidence(evidence)
    _assert_malformed(result)


@pytest.mark.parametrize("field", ["session_exchange", "session_segment"])
def test_non_string_session_fields_rejected(field) -> None:
    """Session exchange/segment metadata must be strings when present."""
    evidence = _na_block_evidence()
    object.__setattr__(evidence, field, 123)
    result = _run_na_evidence(evidence)
    _assert_malformed(result)
    assert getattr(result.check_evidence.entries[-1], field) is None


def test_smuggled_stage_status_code_rejected(monkeypatch) -> None:
    """A check trusted by the runner cannot smuggle status text into a
    non-skipped record: the runner-synthesized code is the only one that
    may appear."""
    import quantx.application.execution as execution_module

    monkeypatch.setattr(execution_module, "is_trusted_check", lambda *args, **kwargs: True)
    evidence = _na_block_evidence()
    object.__setattr__(evidence, "stage_status_code", "pack.smuggled-code")
    result = _run_na_evidence(evidence)
    _assert_malformed(result, "pack.smuggled-code")


def test_forced_trust_non_str_failure_code_cannot_crash(monkeypatch) -> None:
    """A non-string failure code fails closed as undeclared instead of
    raising inside the trusted-code membership test."""
    import quantx.application.execution as execution_module

    class _BadCode:
        check_id = "india.compatibility-rules"

        def __call__(self, request) -> MarketCheckResult:
            result = MarketCheckResult(
                "india.compatibility-rules",
                MarketCheckOutcome.BLOCK,
                "toy.pack.unapproved-code",
                "clean",
            )
            object.__setattr__(result, "failure_code", [])
            return result

    monkeypatch.setattr(execution_module, "is_trusted_check", lambda *args, **kwargs: True)
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
                _ToyCheck("na.pass", MarketCheckOutcome.PASS, []),
            ),
            PlacedCheck(MarketRegion.INDIA, MarketCheckStage.PRE_SUBMIT, _BadCode()),
        ),
    )
    broker = _RecordingBroker(_instrument())
    result = _live_orchestrator(market_policy=config).execute(_request(), broker=broker)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "india.compatibility-rules returned an undeclared failure code"
    assert result.check_evidence is not None
    assert result.check_evidence.entries[-1].outcome is MarketCheckOutcome.UNAVAILABLE
    assert result.check_evidence.blocking_failure_code == (MarketCheckFailureCode.MALFORMED_RESULT)
    assert broker.submit_calls == 0


# ---------------------------------------------------------------------------
# Cold-cache implementation-binding hijack during dispatch
# ---------------------------------------------------------------------------


def test_cold_cache_hijack_during_dispatch_stays_untrusted(monkeypatch) -> None:
    """With a cold resolution cache, a PRE_DISPATCH check that rebinds the
    public ``IndiaCompatCheck`` attribute and spoofs ``__module__`` still
    cannot confer trust on the PRE_SUBMIT rogue: the import-time pin
    observes the reviewed class before any pack check executes."""
    from quantx.ports.market_checks import is_trusted_check

    class _EvilCompatDispatch:
        check_id = "india.compatibility-rules"

        def __call__(self, request) -> MarketCheckResult:
            return MarketCheckResult(
                "india.compatibility-rules",
                MarketCheckOutcome.BLOCK,
                "india.compatibility.rejected",
                "INDIA_LOT_SIZE_INVALID: quantity 1 is not a multiple of lot size 25",
            )

    class _Hijacker:
        check_id = "na.hijacker"

        def __call__(self, request) -> MarketCheckResult:
            india_checks = importlib.import_module("quantx.india.market_checks")
            india_checks.IndiaCompatCheck = _EvilCompatDispatch
            _EvilCompatDispatch.__module__ = "quantx.india.market_checks"
            return MarketCheckResult(self.check_id, MarketCheckOutcome.PASS, None, "hijacked")

    # Make the rogue resolvable as a module attribute, so that only the
    # binding — not resolution — stands between it and trust.
    monkeypatch.setattr(
        sys.modules[__name__], "_EvilCompatDispatch", _EvilCompatDispatch, raising=False
    )
    core = importlib.import_module("quantx.ports.market_checks")
    india_checks = importlib.import_module("quantx.india.market_checks")
    real_compat_check = india_checks.IndiaCompatCheck
    core._approved_implementation.cache_clear()

    regions = tuple(
        _canonical_india_policy()
        if member is MarketRegion.INDIA
        else RegionMarketPolicy(region=member)
        for member in MarketRegion
    )
    config = MarketPolicyConfig(
        regions=regions,
        checks=(
            PlacedCheck(MarketRegion.INDIA, MarketCheckStage.PRE_DISPATCH, _Hijacker()),
            PlacedCheck(MarketRegion.INDIA, MarketCheckStage.PRE_SUBMIT, _EvilCompatDispatch()),
        ),
    )
    try:
        broker = _RecordingBroker(_instrument())
        result = _live_orchestrator(market_policy=config).execute(_request(), broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert result.reason == "india.compatibility-rules blocked the request"
        assert "INDIA_LOT_SIZE_INVALID" not in result.reason
        assert result.check_evidence.blocking_check_id == "india.compatibility-rules"
        assert result.check_evidence.blocking_failure_code == MarketCheckFailureCode.PACK_BLOCKED
        assert broker.submit_calls == 0
        payload = json.dumps(sequence_to_mapping(result.check_evidence), sort_keys=True)
        assert "india.compatibility.rejected" not in payload
        # Direct check after the hijack ran: the rogue is still untrusted.
        assert (
            is_trusted_check(
                "india.compatibility-rules",
                _EvilCompatDispatch(),
                region=MarketRegion.INDIA,
                stage=MarketCheckStage.PRE_SUBMIT,
            )
            is False
        )
    finally:
        india_checks.IndiaCompatCheck = real_compat_check
        core._approved_implementation.cache_clear()



# ---------------------------------------------------------------------------
# Adversarial runtime objects at the evidence-validation boundary
# ---------------------------------------------------------------------------


def test_raising_evidence_subclass_fails_closed() -> None:
    """Evidence subclasses cannot execute arbitrary field access in the runner."""

    class _RaisingEvidence(MarketCheckEvidence):
        def __getattribute__(self, name):
            if name == "rule_checks":
                raise RuntimeError("evidence field access must not escape")
            return super().__getattribute__(name)

    evidence = _RaisingEvidence(
        check_id="na.malformed",
        stage=MarketCheckStage.PRE_DISPATCH,
        outcome=MarketCheckOutcome.BLOCK,
        region=MarketRegion.NORTH_AMERICA,
        family=MarketFamily.EQUITY,
        venue="NYSE",
    )
    result = _run_na_evidence(evidence)
    _assert_malformed(result, "evidence field access must not escape")


def test_tuple_subclass_with_raising_iterator_fails_closed() -> None:
    """Only a plain tuple is accepted; subclass iteration cannot escape."""

    class _RaisingTuple(tuple):
        def __iter__(self):
            raise RuntimeError("rule fact iterator must not escape")

    evidence = _na_block_evidence(
        rule_checks=_RaisingTuple(
            (MarketRuleCheckEvidence("quantity", True, "tick size ok"),)
        )
    )
    result = _run_na_evidence(evidence)
    _assert_malformed(result, "rule fact iterator must not escape")


def test_malformed_timezone_fails_closed() -> None:
    """A caller-supplied timezone that raises cannot crash or affect serialization."""
    from datetime import tzinfo

    class _ExplodingTimezone(tzinfo):
        def utcoffset(self, dt):
            raise RuntimeError("malformed timezone private diagnostic")

        def dst(self, dt):
            return None

        def tzname(self, dt):
            return "malformed"

    evidence = _na_block_evidence()
    object.__setattr__(
        evidence,
        "evaluated_at",
        datetime(2026, 1, 1, 9, 30, tzinfo=_ExplodingTimezone()),
    )
    result = _run_na_evidence(evidence)
    _assert_malformed(result, "malformed timezone private diagnostic")
