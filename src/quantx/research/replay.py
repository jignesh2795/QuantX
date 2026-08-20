"""Deterministic chronological replay over quality-validated historical observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .data import HistoricalObservation, HistoricalDataSeries
from .quality import DataQualityStatus, HistoricalDataQualityGate


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    observation: HistoricalObservation
    index: int


class ReplayBlockedError(ValueError):
    """Raised when replay is attempted with structurally blocked data."""


class HistoricalReplay:
    """Replay observations only after enforcing the historical data-quality gate."""

    def __init__(
        self,
        series: HistoricalDataSeries,
        *,
        quality_gate: HistoricalDataQualityGate | None = None,
        allow_incomplete: bool = False,
        expected_instrument=None,
        expected_interval_seconds: int | None = None,
    ) -> None:
        self._series = series
        self._quality_gate = quality_gate or HistoricalDataQualityGate()
        self._allow_incomplete = allow_incomplete
        self._expected_instrument = expected_instrument
        self._expected_interval_seconds = expected_interval_seconds
        self._quality = None

    @property
    def quality(self):
        if self._quality is None:
            observations = tuple(self._series)
            self._quality = self._quality_gate.validate(
                observations,
                expected_instrument=self._expected_instrument,
                expected_interval_seconds=self._expected_interval_seconds,
            )
        return self._quality

    def _ensure_replayable(self) -> None:
        quality = self.quality
        if quality.status is DataQualityStatus.BLOCKED:
            raise ReplayBlockedError("historical dataset is blocked by the data-quality gate")
        if quality.status is DataQualityStatus.INCOMPLETE and not self._allow_incomplete:
            raise ReplayBlockedError(
                "historical dataset is incomplete; set allow_incomplete=True to run degraded-fidelity replay"
            )

    def frames(self) -> tuple[ReplayFrame, ...]:
        self._ensure_replayable()
        return tuple(
            ReplayFrame(observation=item, index=index)
            for index, item in enumerate(self._series)
        )

    def run(self, callback: Callable[[ReplayFrame], None]) -> int:
        count = 0
        for frame in self.frames():
            callback(frame)
            count += 1
        return count
