from datetime import UTC, datetime

import pytest

from quantx.application.strategy_preflight import (
    EventTimeSupport,
    assess_backtest_event_time_support,
    assess_rehearsal_event_time_support,
)
from quantx.domain.clock import SimulatedClock
from quantx.execution.accounting import FillAccounting
from quantx.execution.paper.broker import PaperBroker
from quantx.execution.paper.executor import PaperOrderExecutor
from quantx.execution.paper.latency import LatencyModel
from quantx.execution.paper.profile import ExecutionProfile
from quantx.execution.paper_engine import PaperExecutionEngine, PaperSimulationProfile


def _executor(*, latency_ms: int = 0) -> PaperOrderExecutor:
    profile = ExecutionProfile(profile_id="test", version="1", latency_ms=latency_ms)
    latency = LatencyModel(order_to_market_ms=latency_ms, market_to_fill_ms=0)
    return PaperOrderExecutor(PaperBroker(profile, latency=latency), FillAccounting())


def test_rehearsal_preflight_accepts_builtin_zero_latency_path() -> None:
    assessment = assess_rehearsal_event_time_support(_executor())
    assert assessment.support is EventTimeSupport.SUPPORTED
    assessment.require_supported()


def test_rehearsal_preflight_rejects_nonzero_latency_and_unknown_executor() -> None:
    assert (
        assess_rehearsal_event_time_support(_executor(latency_ms=1)).support
        is EventTimeSupport.UNSUPPORTED
    )
    assert assess_rehearsal_event_time_support(object()).support is EventTimeSupport.UNKNOWN


def test_backtest_preflight_accepts_owned_simulated_clock_only_at_zero_latency() -> None:
    clock = SimulatedClock(datetime(2026, 1, 1, 9, 15, tzinfo=UTC))
    engine = PaperExecutionEngine(clock=clock, profile=PaperSimulationProfile())
    assert (
        assess_backtest_event_time_support(
            engine, internally_composed=True, configured_latency_ms=0
        ).support
        is EventTimeSupport.SUPPORTED
    )
    assert (
        assess_backtest_event_time_support(
            engine, internally_composed=True, configured_latency_ms=1
        ).support
        is EventTimeSupport.UNSUPPORTED
    )


def test_injected_backtest_engine_requires_explicit_typed_capability() -> None:
    class DeclaredEngine:
        event_time_support = EventTimeSupport.SUPPORTED

    class UndeclaredEngine:
        pass

    assert (
        assess_backtest_event_time_support(
            DeclaredEngine(), internally_composed=False, configured_latency_ms=0
        ).support
        is EventTimeSupport.SUPPORTED
    )
    assert (
        assess_backtest_event_time_support(
            UndeclaredEngine(), internally_composed=False, configured_latency_ms=0
        ).support
        is EventTimeSupport.UNKNOWN
    )
    with pytest.raises(ValueError, match="UNKNOWN"):
        assess_backtest_event_time_support(
            UndeclaredEngine(), internally_composed=False, configured_latency_ms=0
        ).require_supported()
