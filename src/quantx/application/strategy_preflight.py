"""Fail-closed event-time capability checks for the QX-08 context path."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from quantx.domain.clock import SimulatedClock
from quantx.execution.paper.broker import PaperBroker
from quantx.execution.paper.executor import PaperOrderExecutor
from quantx.execution.paper.latency import LatencyModel
from quantx.execution.paper_engine import PaperExecutionEngine


class EventTimeSupport(StrEnum):
    """Whether an execution driver can keep effective facts on its event-time cut."""

    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class EventTimeAssessment:
    support: EventTimeSupport
    reason: str

    def require_supported(self) -> None:
        if self.support is not EventTimeSupport.SUPPORTED:
            raise ValueError(f"strategy event-time preflight {self.support.value}: {self.reason}")


def assess_rehearsal_event_time_support(executor: object) -> EventTimeAssessment:
    """Admit only the built-in paper executor with a known zero-latency model."""
    if type(executor) is not PaperOrderExecutor:
        return EventTimeAssessment(
            EventTimeSupport.UNKNOWN,
            "custom paper executor has not declared event-time-coherent support",
        )
    broker = cast(PaperOrderExecutor, executor).broker
    if type(broker) is not PaperBroker:
        return EventTimeAssessment(
            EventTimeSupport.UNKNOWN,
            "custom paper broker has not declared event-time-coherent support",
        )
    latency = cast(PaperBroker, broker).latency
    if type(latency) is not LatencyModel:
        return EventTimeAssessment(
            EventTimeSupport.UNKNOWN,
            "custom latency model has not declared event-time-coherent support",
        )
    if latency.order_to_market_ms != 0 or latency.market_to_fill_ms != 0:
        return EventTimeAssessment(
            EventTimeSupport.UNSUPPORTED,
            "nonzero paper execution latency is unsupported for the QX-08 context path",
        )
    return EventTimeAssessment(EventTimeSupport.SUPPORTED, "built-in zero-latency paper path")


def assess_backtest_event_time_support(
    engine: object,
    *,
    internally_composed: bool,
    configured_latency_ms: int,
) -> EventTimeAssessment:
    """Check the backtest clock/latency pair without inspecting private engine state."""
    if configured_latency_ms < 0:
        return EventTimeAssessment(EventTimeSupport.UNSUPPORTED, "negative latency is invalid")
    if internally_composed:
        if type(engine) is not PaperExecutionEngine:
            return EventTimeAssessment(
                EventTimeSupport.UNKNOWN,
                "internally composed executor is not the canonical paper engine",
            )
        if type(cast(PaperExecutionEngine, engine).clock) is not SimulatedClock:
            return EventTimeAssessment(
                EventTimeSupport.UNKNOWN,
                "canonical paper engine is not driven by a SimulatedClock",
            )
        if configured_latency_ms != 0:
            return EventTimeAssessment(
                EventTimeSupport.UNSUPPORTED,
                "nonzero paper execution latency is unsupported for the QX-08 context path",
            )
        return EventTimeAssessment(
            EventTimeSupport.SUPPORTED,
            "service-owned SimulatedClock with zero configured latency",
        )

    declared = getattr(engine, "event_time_support", EventTimeSupport.UNKNOWN)
    if declared is not EventTimeSupport.SUPPORTED:
        support = declared if isinstance(declared, EventTimeSupport) else EventTimeSupport.UNKNOWN
        return EventTimeAssessment(
            support,
            "injected execution engine must explicitly declare EventTimeSupport.SUPPORTED",
        )
    if configured_latency_ms != 0:
        return EventTimeAssessment(
            EventTimeSupport.UNSUPPORTED,
            "nonzero configured latency is unsupported for the QX-08 context path",
        )
    return EventTimeAssessment(EventTimeSupport.SUPPORTED, "injected engine explicitly declared support")
