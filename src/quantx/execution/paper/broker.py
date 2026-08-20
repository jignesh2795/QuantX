"""Paper venue composing matching, fills, and explicit execution assumptions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .evidence import SimulationEvidence, SimulationEvidenceStatus
from .fills import FillSimulator, MarketSnapshot, SimulatedFill
from .latency import LatencyModel
from .matching import MatchDecision, PaperMatcher
from .order_types import PaperOrderSpec
from .profile import ExecutionProfile, OrderBookSnapshot


@dataclass(frozen=True, slots=True)
class PaperExecutionResult:
    evidence: SimulationEvidence
    match: MatchDecision
    fill: SimulatedFill | None = None
    fill_at_ns: int | None = None


class PaperBroker:
    """Deterministic paper broker; never fabricates unavailable market evidence."""

    def __init__(
        self,
        profile: ExecutionProfile,
        *,
        latency: LatencyModel | None = None,
        matcher: PaperMatcher | None = None,
        simulator: FillSimulator | None = None,
    ) -> None:
        self.profile = profile
        self.latency = latency or LatencyModel(
            order_to_market_ms=profile.latency_ms,
            market_to_fill_ms=0,
        )
        self.matcher = matcher or PaperMatcher()
        self.simulator = simulator or FillSimulator()

    def execute(
        self,
        order: PaperOrderSpec,
        *,
        snapshot: MarketSnapshot | None,
        submitted_at_ns: int,
        order_book: OrderBookSnapshot | None = None,
    ) -> PaperExecutionResult:
        if submitted_at_ns < 0:
            raise ValueError("submitted_at_ns cannot be negative")

        if snapshot is None:
            evidence = SimulationEvidence(
                SimulationEvidenceStatus.INSUFFICIENT,
                "market snapshot is required to determine execution",
            )
            return PaperExecutionResult(
                evidence=evidence,
                match=MatchDecision(False, None, "missing market snapshot"),
            )

        match = self.matcher.evaluate(order, snapshot)
        if not match.executable:
            return PaperExecutionResult(
                evidence=SimulationEvidence(
                    SimulationEvidenceStatus.CONFIRMED,
                    match.reason,
                    source_timestamp_ns=submitted_at_ns,
                ),
                match=match,
            )

        fill_at_ns = self.latency.fill_time_ns(submitted_at_ns)
        fill = self.simulator.simulate(
            side=order.side,
            quantity=order.quantity,
            snapshot=snapshot,
            profile=self.profile,
            order_book=order_book,
        )
        return PaperExecutionResult(
            evidence=SimulationEvidence(
                SimulationEvidenceStatus.CONFIRMED,
                "execution determined from observed market evidence",
                source_timestamp_ns=submitted_at_ns,
            ),
            match=match,
            fill=fill,
            fill_at_ns=fill_at_ns,
        )
