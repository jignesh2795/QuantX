"""Composition boundary for the sanctioned LIVE execution stack.

Slice C is currently fail-closed: the previous caller-provided risk-input
callable is not an authoritative broker-evidence boundary. Until complete
account-wide risk authorities and durable admission controls are wired into
the single execution path, this factory refuses to return a LIVE stack.
"""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.clock import Clock
from quantx.domain.errors import ValidationError
from quantx.domain.instruments import MarketRegion
from quantx.domain.policy_verification import MarketPackPolicyVerifier
from quantx.domain.risk import (
    LiveRiskLimitsError,
    PreTradeRiskEngine,
    RiskLimits,
    require_live_risk_limits,
)
from quantx.execution.trading_gate import DurableTradingGate
from quantx.ports.market_checks import (
    MarketCheckStage,
    MarketPolicyConfig,
    RegionMarketPolicy,
)

from .execution import ExecutionOrchestrator
from .production import ProductionRuntime

_LIMITS_REQUIRED_REASON = (
    "LIVE risk limits require explicit positive limits for order notional, "
    "position notional, realized daily loss, unrealized loss and snapshot age"
)

_LIVE_EVIDENCE_UNAVAILABLE_REASON = (
    "LIVE risk evidence authority set unavailable; production LIVE composition is blocked"
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
    """Explicit deployment policy inputs accepted by the LIVE composition root.

    No provider-supplied risk-input callable is accepted. Until the evidence
    authorities and durable admission controls are wired end-to-end, even a
    well-typed config is refused by the factory.
    """

    risk_limits: RiskLimits
    risk_engine: PreTradeRiskEngine
    clock: Clock
    market_policy: MarketPolicyConfig
    policy_verifier: MarketPackPolicyVerifier


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
    """Refuse LIVE composition until the authoritative Slice C controls exist.

    The legacy input-provider field has been removed from configuration. The
    evidence source, P&L/position completeness, broker margin authority,
    durable pending-scope guard, and durable concurrency admission must all be
    implemented and integrated before a production execution stack can be
    constructed.
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
        require_live_risk_limits(config.risk_limits)
    except LiveRiskLimitsError:
        raise LiveExecutionCompositionError(_LIMITS_REQUIRED_REASON) from None

    # This intentionally fails before touching durable gate state.
    raise LiveExecutionCompositionError(_LIVE_EVIDENCE_UNAVAILABLE_REASON)
