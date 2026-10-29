"""Compose the sanctioned LIVE execution stack from explicit deployment inputs.

The application layer owns the LIVE execution invariants; a deployment owns
the evidence it feeds them. This factory is the one supported way to assemble
a LIVE-capable ``ExecutionOrchestrator`` over a validated ``ProductionRuntime``.
It builds every guard this slice can require and refuses to build when a
required input is absent or mistyped, so LIVE protection is never degraded to
an optional layer by a convenience default.

It does not make the orchestrator safe by itself: the orchestrator still
accepts arbitrary callables when it is constructed directly. Callback mode
remains explicitly non-authoritative: type-correct dataclasses and a trusted
clock do not authenticate balances, positions, P&L, account, connection,
transport, client identity, or observation-time provenance. Authority mode
builds an application-owned ``LiveRiskEvidenceAuthority`` over a wired
``LiveRiskEvidenceSource``; even then, LIVE dispatch stays blocked unless the
source declares every field the configured limits require. What this factory
guarantees is that the stack it returns is disarmed, durably gated,
quarantine-backed, risk-evaluated against a composition-injected clock, and
market-policy-complete for India.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.clock import Clock
from quantx.domain.errors import ValidationError
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import MarketRegion
from quantx.domain.policy_verification import MarketPackPolicyVerifier
from quantx.domain.risk import (
    LiveRiskLimitsError,
    PreTradeRiskEngine,
    RiskLimits,
    require_live_risk_limits,
)
from quantx.execution.trading_gate import DurableTradingGate
from quantx.persistence.sqlite import (
    SqliteSubmissionQuarantineRepository,
    SqliteTradingGateStateStore,
)
from quantx.ports.market_checks import (
    MarketCheckStage,
    MarketPolicyConfig,
    RegionMarketPolicy,
)

from .execution import ExecutionOrchestrator
from .live_risk import (
    LivePreTradeRiskEvaluator,
    LiveRiskEvaluationInputs,
    LiveRiskEvidenceAuthority,
    LiveRiskEvidenceSource,
)
from .production import ProductionRuntime

_LIMITS_REQUIRED_REASON = (
    "LIVE risk limits require explicit positive limits for order notional, "
    "position notional, daily loss and snapshot age"
)

_NON_INDIA_PLACEMENT_REASON = (
    "market_policy must not place checks for a non-India region: LIVE execution is India-only"
)


class LiveExecutionCompositionError(ValidationError):
    """Raised when a LIVE stack cannot be built from the supplied inputs.

    Messages are fixed text: a composition failure names the missing or
    mistyped requirement and never a supplied value.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class LiveExecutionConfig:
    """Explicit mandatory inputs for :func:`build_live_execution`.

    A deployment supplies its risk limits, risk engine, trusted clock, market
    policy and trusted policy verifier. It must also supply exactly one evidence
    mode:

    * ``risk_inputs_for_request`` for explicitly non-authoritative callback
      mode; or
    * ``risk_evidence_source`` plus the exact expected account, broker
      connection, broker client id and transport for application-owned
      authority mode.

    The identity inputs are rejected in callback mode. No default identity,
    evidence source, or authorization is selected here.
    """

    risk_limits: RiskLimits
    risk_engine: PreTradeRiskEngine
    clock: Clock
    market_policy: MarketPolicyConfig
    policy_verifier: MarketPackPolicyVerifier
    risk_inputs_for_request: (
        Callable[[ApprovedExecutionRequest], LiveRiskEvaluationInputs] | None
    ) = None
    risk_evidence_source: LiveRiskEvidenceSource | None = None
    expected_account_id: AccountId | None = None
    expected_broker_connection_id: BrokerConnectionId | None = None
    expected_broker_client_id: str | None = None
    expected_transport: object | None = None


@dataclass(frozen=True, slots=True)
class LiveExecutionStack:
    """The composed LIVE execution boundary.

    ``gate`` is the same instance the orchestrator holds, so the operator has
    one control surface: the orchestrator cannot be authorized through a
    different gate than the one returned here.
    """

    orchestrator: ExecutionOrchestrator
    gate: DurableTradingGate


def _india_only_market_policy(policy: MarketPolicyConfig) -> MarketPolicyConfig:
    """Derive the India-only policy the sanctioned LIVE stack runs under.

    India keeps the caller's classification and check placements exactly as
    supplied, in registration order. Every other ``MarketRegion`` member
    requires both policy stages with no registered checks, so the
    orchestrator's existing missing-required-stage path blocks a non-India
    LIVE request before risk evaluation, reservation, or broker observations.
    Iterating the enum members locks a newly added region by default instead
    of leaving it core-only. The caller policy is validated before this runs;
    filtering is a second line of defence, not the rejection path.
    """
    regions = tuple(
        policy.policy_for(member)
        if member is MarketRegion.INDIA
        else RegionMarketPolicy(
            region=member,
            requires_pack=True,
            required_stages=frozenset({MarketCheckStage.PRE_DISPATCH, MarketCheckStage.PRE_SUBMIT}),
            replaces_session_guard=False,
        )
        for member in MarketRegion
    )
    checks = tuple(placed for placed in policy.checks if placed.region is MarketRegion.INDIA)
    return MarketPolicyConfig(regions=regions, checks=checks)


def build_live_execution(
    runtime: ProductionRuntime,
    config: LiveExecutionConfig,
) -> LiveExecutionStack:
    """Build one disarmed, fully guarded LIVE execution stack.

    Validation runs before construction, so invalid configuration writes no
    durable state. When building the gate, the factory overwrites any enabled
    state left by a prior process with a durably disarmed state before returning.
    Each new process therefore requires an explicit operator enable after startup.
    If disarming cannot be persisted, construction raises and returns no stack.

    The market policy must require the India pack and place at least one check
    in both India stages. Construction already rejects a core-only India or a
    missing required stage, but an empty required stage is otherwise only
    detected when a request arrives, which is too late to be a build failure.
    The supplied policy is narrowed to India before it reaches the
    orchestrator: every other region requires both stages with no registered
    checks, so a non-India LIVE request is blocked by the market stage.
    """
    if type(runtime) is not ProductionRuntime:
        raise LiveExecutionCompositionError("runtime must be a ProductionRuntime")
    if type(config) is not LiveExecutionConfig:
        raise LiveExecutionCompositionError("live execution config must be a LiveExecutionConfig")
    if type(config.risk_limits) is not RiskLimits:
        raise LiveExecutionCompositionError("risk_limits must be a RiskLimits")
    if type(config.risk_engine) is not PreTradeRiskEngine:
        raise LiveExecutionCompositionError("risk_engine must be a PreTradeRiskEngine")
    if not isinstance(config.clock, Clock):
        raise LiveExecutionCompositionError("clock must be a Clock")
    has_callback = config.risk_inputs_for_request is not None
    has_source = config.risk_evidence_source is not None
    if has_callback == has_source:
        raise LiveExecutionCompositionError(
            "live execution config requires exactly one of risk_inputs_for_request "
            "or risk_evidence_source"
        )
    authority_identity_supplied = any(
        value is not None
        for value in (
            config.expected_account_id,
            config.expected_broker_connection_id,
            config.expected_broker_client_id,
            config.expected_transport,
        )
    )
    if has_callback:
        if not callable(config.risk_inputs_for_request):
            raise LiveExecutionCompositionError("risk_inputs_for_request must be callable")
        if authority_identity_supplied:
            raise LiveExecutionCompositionError(
                "authority identity inputs require risk_evidence_source"
            )
    else:
        if not isinstance(config.risk_evidence_source, LiveRiskEvidenceSource):
            raise LiveExecutionCompositionError(
                "risk_evidence_source must implement LiveRiskEvidenceSource"
            )
        if type(config.expected_account_id) is not AccountId:
            raise LiveExecutionCompositionError("expected_account_id must be an AccountId")
        if type(config.expected_broker_connection_id) is not BrokerConnectionId:
            raise LiveExecutionCompositionError(
                "expected_broker_connection_id must be a BrokerConnectionId"
            )
        expected_client_id = config.expected_broker_client_id
        if not isinstance(expected_client_id, str) or not expected_client_id.strip():
            raise LiveExecutionCompositionError(
                "expected_broker_client_id must be a non-empty string"
            )
        if config.expected_transport is None:
            raise LiveExecutionCompositionError(
                "expected_transport must be supplied in authority mode"
            )
    if type(config.market_policy) is not MarketPolicyConfig:
        raise LiveExecutionCompositionError("market_policy must be a MarketPolicyConfig")
    if any(placed.region is not MarketRegion.INDIA for placed in config.market_policy.checks):
        raise LiveExecutionCompositionError(_NON_INDIA_PLACEMENT_REASON)
    if type(config.policy_verifier) is not MarketPackPolicyVerifier:
        raise LiveExecutionCompositionError("policy_verifier must be a MarketPackPolicyVerifier")
    if config.market_policy.policy_for(MarketRegion.INDIA).requires_pack is not True:
        raise LiveExecutionCompositionError(
            "market_policy must require the India market pack for LIVE execution"
        )
    if not config.market_policy.checks_for(MarketRegion.INDIA, MarketCheckStage.PRE_DISPATCH):
        raise LiveExecutionCompositionError(
            "market_policy must place at least one pre-dispatch check for India"
        )
    if not config.market_policy.checks_for(MarketRegion.INDIA, MarketCheckStage.PRE_SUBMIT):
        raise LiveExecutionCompositionError(
            "market_policy must place at least one pre-submit check for India"
        )
    try:
        limits = require_live_risk_limits(config.risk_limits)
    except LiveRiskLimitsError:
        raise LiveExecutionCompositionError(_LIMITS_REQUIRED_REASON) from None

    gate = DurableTradingGate(SqliteTradingGateStateStore(runtime.database))
    # Persist a fresh disarmed state on every process start; do not inherit
    # authorization that an operator granted to a previous process.
    gate.block("LIVE gate disarmed for new process start")
    quarantine = SqliteSubmissionQuarantineRepository(runtime.database)
    if has_callback:
        evaluator = LivePreTradeRiskEvaluator(
            engine=config.risk_engine,
            limits=limits,
            inputs_for_request=config.risk_inputs_for_request,
            clock=config.clock,
        )
    else:
        source = config.risk_evidence_source
        expected_account_id = config.expected_account_id
        expected_connection_id = config.expected_broker_connection_id
        expected_client_id = config.expected_broker_client_id
        expected_transport = config.expected_transport
        if (
            source is None
            or type(expected_account_id) is not AccountId
            or type(expected_connection_id) is not BrokerConnectionId
            or not isinstance(expected_client_id, str)
            or expected_transport is None
        ):  # pragma: no cover - validated above
            raise LiveExecutionCompositionError("authority evidence inputs are incomplete")
        authority = LiveRiskEvidenceAuthority(
            source=source,
            limits=limits,
            clock=config.clock,
            account_id=expected_account_id,
            broker_connection_id=expected_connection_id,
            expected_broker_client_id=expected_client_id,
            expected_transport=expected_transport,
        )
        evaluator = LivePreTradeRiskEvaluator(
            engine=config.risk_engine,
            limits=limits,
            clock=config.clock,
            authority=authority,
        )
    orchestrator = ExecutionOrchestrator(
        trading_gate=gate,
        application_runtime=runtime.application,
        unit_of_work=runtime.unit_of_work,
        live_risk_evaluator=evaluator,
        market_policy=_india_only_market_policy(config.market_policy),
        submission_quarantine=quarantine,
        policy_verifier=config.policy_verifier,
    )
    return LiveExecutionStack(orchestrator=orchestrator, gate=gate)
