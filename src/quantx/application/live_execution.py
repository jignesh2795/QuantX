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
transport, client identity, or observation-time provenance.

Authority mode accepts no source instance and no catalog. It requires the
account and broker connection this process registered in
``ProductionRuntime.registry``, and the evidence source must come from that
connection's own adapter: the only accepted construction path is the adapter's
``build_live_risk_evidence_binding``. The factory derives the catalog from the
registered adapter, mints the grant the authority consumes, and never returns
the catalog, so a caller cannot declare a construction path next to a genuine
broker connection. A connection whose adapter exposes no construction path gets
a composition error, never a quietly degraded LIVE stack. What this factory
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
)
from .live_risk_sources import (
    LiveRiskEvidenceSourceCatalog,
    LiveRiskEvidenceSourceGrant,
    live_risk_evidence_catalog_for,
)
from .production import ProductionRuntime

_LIMITS_REQUIRED_REASON = (
    "LIVE risk limits require explicit positive limits for order notional, "
    "position notional, daily loss and snapshot age"
)

_NON_INDIA_PLACEMENT_REASON = (
    "market_policy must not place checks for a non-India region: LIVE execution is India-only"
)

_REGISTRY_REQUIRED_REASON = (
    "authority mode requires the account and broker connection this process registered"
)

_UNREGISTERED_SOURCE_REASON = (
    "authority mode requires a risk evidence construction path on the registered broker adapter"
)

_AUTHORITY_IDENTITY_REQUIRED_REASON = (
    "authority mode requires the registered account and broker connection"
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
    policy and trusted policy verifier, plus one evidence mode:

    * ``risk_inputs_for_request`` for explicitly non-authoritative callback
      mode; or
    * the account and broker connection this process registered, for authority
      mode.

    There is deliberately no field for a source instance and no field for a
    catalog: authority mode takes its construction path from the registered
    connection's own adapter, so a caller cannot declare a source or an
    allowlist next to a genuine broker connection. The identity inputs are
    rejected in callback mode. No default identity, evidence source, or
    authorization is selected here.
    """

    risk_limits: RiskLimits
    risk_engine: PreTradeRiskEngine
    clock: Clock
    market_policy: MarketPolicyConfig
    policy_verifier: MarketPackPolicyVerifier
    risk_inputs_for_request: (
        Callable[[ApprovedExecutionRequest], LiveRiskEvaluationInputs] | None
    ) = None
    expected_account_id: AccountId | None = None
    expected_broker_connection_id: BrokerConnectionId | None = None


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


def _authority_catalog_and_grant(
    runtime: ProductionRuntime,
    config: LiveExecutionConfig,
) -> tuple[LiveRiskEvidenceSourceCatalog, LiveRiskEvidenceSourceGrant]:
    """Resolve the registered connection and the construction path it owns.

    The catalog is derived from the registered adapter, is never accepted from
    the caller, and is never returned to a caller of this factory.
    """
    if config.expected_account_id is None and config.expected_broker_connection_id is None:
        raise LiveExecutionCompositionError(_AUTHORITY_IDENTITY_REQUIRED_REASON)
    if type(config.expected_account_id) is not AccountId:
        raise LiveExecutionCompositionError("expected_account_id must be an AccountId")
    if type(config.expected_broker_connection_id) is not BrokerConnectionId:
        raise LiveExecutionCompositionError(
            "expected_broker_connection_id must be a BrokerConnectionId"
        )
    registered = runtime.registry.get(config.expected_broker_connection_id)
    if registered is None or not registered.enabled:
        raise LiveExecutionCompositionError(_REGISTRY_REQUIRED_REASON)
    if registered.ref.account_id != config.expected_account_id:
        raise LiveExecutionCompositionError(_REGISTRY_REQUIRED_REASON)
    catalog = live_risk_evidence_catalog_for(registered)
    if catalog is None:
        raise LiveExecutionCompositionError(_UNREGISTERED_SOURCE_REASON)
    grant = catalog.grant(registered)
    if grant is None:
        raise LiveExecutionCompositionError(_UNREGISTERED_SOURCE_REASON)
    return catalog, grant


def build_live_execution(
    runtime: ProductionRuntime,
    config: LiveExecutionConfig,
) -> LiveExecutionStack:
    """Build one disarmed, fully guarded LIVE execution stack.

    Validation runs before construction, so invalid configuration writes no
    durable state. In authority mode that validation includes the account/
    connection registry lookup and the catalog's construction-path grant, so a
    source this process did not register stops the build instead of becoming a
    runtime surprise. When building the gate, the factory overwrites any
    enabled state left by a prior process with a durably disarmed state before
    returning. Each new process therefore requires an explicit operator enable
    after startup. If disarming cannot be persisted, construction raises and
    returns no stack.

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
    authority_identity_supplied = (
        config.expected_account_id is not None or config.expected_broker_connection_id is not None
    )
    catalog: LiveRiskEvidenceSourceCatalog | None = None
    grant: LiveRiskEvidenceSourceGrant | None = None
    if has_callback:
        if not callable(config.risk_inputs_for_request):
            raise LiveExecutionCompositionError("risk_inputs_for_request must be callable")
        if authority_identity_supplied:
            raise LiveExecutionCompositionError(
                "authority identity inputs are rejected in callback mode"
            )
    else:
        catalog, grant = _authority_catalog_and_grant(runtime, config)
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
        if catalog is None or grant is None:  # pragma: no cover - validated above
            raise LiveExecutionCompositionError(_UNREGISTERED_SOURCE_REASON)
        authority = LiveRiskEvidenceAuthority(
            grant=grant,
            catalog=catalog,
            registry=runtime.registry,
            limits=limits,
            clock=config.clock,
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
