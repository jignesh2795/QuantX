"""Compose the sanctioned LIVE execution stack from explicit deployment inputs.

The application layer owns the LIVE execution invariants; a deployment owns
the evidence it feeds them. This factory is the one supported way to assemble
a LIVE-capable ``ExecutionOrchestrator`` over a validated ``ProductionRuntime``.
It builds every guard this slice can require and refuses to build when a
required input is absent or mistyped, so LIVE protection is never degraded to
an optional layer by a convenience default.

It does not make the orchestrator safe by itself: the orchestrator still
accepts arbitrary callables when it is constructed directly, risk inputs are
supplied by the caller, and the trusted clock is a later slice. What this
factory guarantees is that the stack it returns is disarmed, durably gated,
quarantine-backed, risk-evaluated, and market-policy-complete for India.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
from quantx.ports.market_checks import MarketCheckStage, MarketPolicyConfig

from .execution import ExecutionOrchestrator
from .live_risk import LivePreTradeRiskEvaluator, LiveRiskEvaluationInputs
from .production import ProductionRuntime

_LIMITS_REQUIRED_REASON = (
    "LIVE risk limits require explicit positive limits for order notional, "
    "position notional, daily loss and snapshot age"
)


class LiveExecutionCompositionError(ValidationError):
    """Raised when a LIVE stack cannot be built from the supplied inputs.

    Messages are fixed text: a composition failure names the missing or
    mistyped requirement and never a supplied value.
    """


@dataclass(frozen=True, slots=True, kw_only=True)
class LiveExecutionConfig:
    """Explicit mandatory inputs for :func:`build_live_execution`.

    There are no defaults. A deployment must supply its risk limits, a risk
    engine, the per-request risk evidence provider, the market policy that
    carries both India check stages, and the trusted policy verifier.
    """

    risk_limits: RiskLimits
    risk_engine: PreTradeRiskEngine
    risk_inputs_for_request: Callable[[ApprovedExecutionRequest], LiveRiskEvaluationInputs]
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
    """
    if type(runtime) is not ProductionRuntime:
        raise LiveExecutionCompositionError("runtime must be a ProductionRuntime")
    if type(config) is not LiveExecutionConfig:
        raise LiveExecutionCompositionError("live execution config must be a LiveExecutionConfig")
    if type(config.risk_limits) is not RiskLimits:
        raise LiveExecutionCompositionError("risk_limits must be a RiskLimits")
    if type(config.risk_engine) is not PreTradeRiskEngine:
        raise LiveExecutionCompositionError("risk_engine must be a PreTradeRiskEngine")
    if not callable(config.risk_inputs_for_request):
        raise LiveExecutionCompositionError("risk_inputs_for_request must be callable")
    if type(config.market_policy) is not MarketPolicyConfig:
        raise LiveExecutionCompositionError("market_policy must be a MarketPolicyConfig")
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
    evaluator = LivePreTradeRiskEvaluator(
        engine=config.risk_engine,
        limits=limits,
        inputs_for_request=config.risk_inputs_for_request,
    )
    orchestrator = ExecutionOrchestrator(
        trading_gate=gate,
        application_runtime=runtime.application,
        unit_of_work=runtime.unit_of_work,
        live_risk_evaluator=evaluator,
        market_policy=config.market_policy,
        submission_quarantine=quarantine,
        policy_verifier=config.policy_verifier,
        live_region_allowlist=frozenset({MarketRegion.INDIA}),
    )
    return LiveExecutionStack(orchestrator=orchestrator, gate=gate)
