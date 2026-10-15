"""Strategy intermediate representation, evaluation, and immutable context APIs."""
from .context import StrategyContext
from .engine_snapshot import (
    EngineEvidenceAdapter,
    EngineStateSnapshot,
    EvidenceAvailability,
    EvidenceCollection,
    OpenOrderFact,
    PositionFact,
    TemporalIntegrityError,
    build_engine_snapshot,
    prior_candle_history,
    unavailable_engine_snapshot,
)
from .ir import StrategyIR
from .runtime import ExecutableStrategy, StrategyRuntime
from .typed_params import TypedParams

__all__ = [
    "EngineEvidenceAdapter",
    "EngineStateSnapshot",
    "EvidenceAvailability",
    "EvidenceCollection",
    "ExecutableStrategy",
    "OpenOrderFact",
    "PositionFact",
    "StrategyContext",
    "StrategyIR",
    "StrategyRuntime",
    "TemporalIntegrityError",
    "TypedParams",
    "build_engine_snapshot",
    "prior_candle_history",
    "unavailable_engine_snapshot",
]
