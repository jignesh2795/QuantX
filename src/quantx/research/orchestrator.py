"""Controlled research-run orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

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
        series: HistoricalDataSeries,
        result_factory: Callable[[int], ResearchResult],
        frame_runner: FrameRunner | None = None,
        allow_incomplete: bool = False,
        manifest: ResearchArtifactManifest | None = None,
    ) -> ResearchRunOutcome:
        effective_manifest = manifest or ResearchArtifactManifest(run_fingerprint="no-manifest")
        preflight = self._preflight.check(effective_manifest)
        if preflight.status is not PreflightStatus.READY:
            return ResearchRunOutcome(None, preflight.status, DataQualityStatus.BLOCKED, 0)

        quality = self._quality_gate.validate(tuple(series))
        if quality.status is DataQualityStatus.BLOCKED:
            return ResearchRunOutcome(None, preflight.status, quality.status, 0)
        if quality.status is DataQualityStatus.INCOMPLETE and not allow_incomplete:
            return ResearchRunOutcome(None, preflight.status, quality.status, 0)

        replay = HistoricalReplay(series, allow_incomplete=allow_incomplete)
        callback = frame_runner or (lambda _frame: None)
        replayed = replay.run(callback)
        result = result_factory(replayed)
        self._store.save_result(result)
        return ResearchRunOutcome(result, preflight.status, quality.status, replayed)
