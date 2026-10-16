"""Strategy runtime evaluation contracts."""

from .compiler import StrategyCompiler
from .callbacks import CallbackFault, OrderUpdateFact, RunHaltRecord, TemporalIntegrityFault
from .context import StrategyContext
from .deployment import StrategyDeploymentRuntime, StrategyExecutionDecision
from .engine_snapshot import (
    EngineEvidenceAdapter,
    EngineStateSnapshot,
    EvidenceAvailability,
    EvidenceCollection,
    OpenOrderFact,
    PositionFact,
    TemporalIntegrityError,
    build_engine_snapshot,
    build_simulated_engine_snapshot,
    prior_candle_history,
    unavailable_engine_snapshot,
)
from .evaluation import StrategyEvaluation, StrategyEvaluationService
from .execution import (
    StrategyExecutionPreparation,
    StrategyExecutionPreparer,
    bind_deployment_context,
)
from .ir import StrategyIR
from .reference import BuyAndHoldStrategy, BuyThenCloseStrategy
from .registry import StrategyRegistry
from .runtime import ExecutableStrategy, StrategyRuntime
from .timers import TimerInvocation, TimerRegistry, UndeliveredTimer
from .typed_params import TypedParams
from quantx.domain.strategy import TimerRequest

__all__ = [
    "BuyAndHoldStrategy",
    "BuyThenCloseStrategy",
    "CallbackFault",
    "EngineEvidenceAdapter",
    "EngineStateSnapshot",
    "EvidenceAvailability",
    "EvidenceCollection",
    "ExecutableStrategy",
    "OpenOrderFact",
    "OrderUpdateFact",
    "PositionFact",
    "StrategyCompiler",
    "StrategyContext",
    "StrategyDeploymentRuntime",
    "StrategyExecutionDecision",
    "StrategyExecutionPreparation",
    "StrategyExecutionPreparer",
    "StrategyEvaluation",
    "StrategyEvaluationService",
    "StrategyIR",
    "StrategyRegistry",
    "StrategyRuntime",
    "TimerInvocation",
    "TimerRegistry",
    "TimerRequest",
    "UndeliveredTimer",
    "RunHaltRecord",
    "TemporalIntegrityFault",
    "TemporalIntegrityError",
    "TypedParams",
    "bind_deployment_context",
    "build_engine_snapshot",
    "build_simulated_engine_snapshot",
    "prior_candle_history",
    "unavailable_engine_snapshot",
]
