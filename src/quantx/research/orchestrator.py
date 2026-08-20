"""Controlled research-run orchestration.

Coordinates artifact preflight, historical replay, and result persistence while
keeping strategy/replay implementations behind narrow interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .artifacts import ResearchArtifactManifest
from .data import HistoricalDataSeries
from .preflight import PreflightStatus, ResearchPreflightGate
from .quality import DataQualityStatus, HistoricalDataQualityGate
from .replay import HistoricalReplay, ReplayFrame
from .result import ResearchResult
from .storage import ResearchStore


class FrameRunner(Protocol):
    def __call__(self, frame: ReplayFrame) -> None: ...


@dataclass(frozen=True, slots=True)
class ResearchRunOutcome:
    result: ResearchResult | None
    preflight_status: PreflightStatus
    data_quality_status: DataQualityStatus
    replayed_frames: int

    @property
    def runnable(self) -> bool:
        return (
            self.preflight_status is PreflightStatus.READY
            and self.data_quality_status is DataQualityStatus.COMPLETE
        )


class ResearchOrchestrator:
    """Run the research workflow without silently degrading its integrity."""

    def __init__(
        self,
        *,
        preflight: ResearchPreflightGate,
        quality_gate: HistoricalDataQualityGate,
        store: ResearchStore,
    ) -> None:
        self._preflight = preflight
        self._quality_gate = quality_gate
        self._store = store

    def run(
        self,
        *,
        manifest: ResearchArtifactManifest,
        series: HistoricalDataSeries,
        result_factory: Callable[[int, DataQualityStatus], ResearchResult],
        frame_runner: FrameRunner | None = None,
        allow_incomplete: bool = False,
        expected_instrument=None,
        expected_interval_seconds: int | None = None,
    ) -> ResearchRunOutcome:
        preflight = self._preflight.check(manifest)
        if preflight.status is not PreflightStatus.READY:
            return ResearchRunOutcome(None, preflight.status, DataQualityStatus.BLOCKED, 0)

        observations = tuple(series)
        quality = self._quality_gate.validate(
            observations,
            expected_instrument=expected_instrument,
            expected_interval_seconds=expected_interval_seconds,
        )
        if quality.status is DataQualityStatus.BLOCKED:
            return ResearchRunOutcome(None, preflight.status, quality.status, 0)
        if quality.status is DataQualityStatus.INCOMPLETE and not allow_incomplete:
            return ResearchRunOutcome(None, preflight.status, quality.status, 0)

        replay_series = type(series)(observations)
        replay = HistoricalReplay(
            replay_series,
            quality_gate=self._quality_gate,
            allow_incomplete=allow_incomplete,
            expected_instrument=expected_instrument,
            expected_interval_seconds=expected_interval_seconds,
        )
        callback = frame_runner or (lambda _frame: None)
        replayed = replay.run(callback)
        result = result_factory(replayed, quality.status)
        self._store.save_result(result)
        return ResearchRunOutcome(result, preflight.status, quality.status, replayed)
