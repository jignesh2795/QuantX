"""Fail-closed event-time capability checks for the QX-08 context path."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

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
    """Require built-in zero latency or an explicit typed custom capability."""
    broker = getattr(executor, "broker", None)
    latency = getattr(broker, "latency", None) if broker is not None else None

    # A known nonzero paper latency is unsupported even if a caller adds a
    # capability marker: the built-in executor will emit future-effective fills.
    if isinstance(latency, LatencyModel) and (
        latency.order_to_market_ms != 0 or latency.market_to_fill_ms != 0
    ):
        return EventTimeAssessment(
            EventTimeSupport.UNSUPPORTED,
            "nonzero paper execution latency is unsupported for the QX-08 context path",
        )

    if (
        type(executor) is PaperOrderExecutor
        and type(broker) is PaperBroker
        and type(latency) is LatencyModel
    ):
        return EventTimeAssessment(
            EventTimeSupport.SUPPORTED,
            "built-in zero-latency paper path",
        )

    declared = getattr(executor, "event_time_support", EventTimeSupport.UNKNOWN)
    if declared is EventTimeSupport.SUPPORTED:
        return EventTimeAssessment(
            EventTimeSupport.SUPPORTED,
            "custom paper executor explicitly declared event-time-coherent support",
        )
    support = declared if isinstance(declared, EventTimeSupport) else EventTimeSupport.UNKNOWN
    return EventTimeAssessment(
        support,
        "custom paper executor must explicitly declare EventTimeSupport.SUPPORTED",
    )


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
        if type(engine.clock) is not SimulatedClock:
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
    return EventTimeAssessment(
        EventTimeSupport.SUPPORTED,
        "injected engine explicitly declared support",
    )
