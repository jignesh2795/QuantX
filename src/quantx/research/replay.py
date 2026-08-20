"""Deterministic chronological replay over quality-validated historical observations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .data import HistoricalObservation, HistoricalDataSeries
from .point_in_time import PointInTimeContext, PointInTimeContextResolver
from .quality import DataQualityStatus, HistoricalDataQualityValidator


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    observation: HistoricalObservation
    index: int
    point_in_time: PointInTimeContext | None = None

    @property
    def executable(self) -> bool | None:
        return None if self.point_in_time is None else self.point_in_time.executable


class ReplayBlockedError(ValueError):
    """Raised when replay is attempted with structurally blocked data."""


class HistoricalReplay:
    """Replay observations only after enforcing data quality and optional point-in-time rules."""

    def __init__(
        self,
        series: HistoricalDataSeries,
        *,
        validator: HistoricalDataQualityValidator | None = None,
        allow_incomplete: bool = False,
        point_in_time_resolver: PointInTimeContextResolver | None = None,
    ) -> None:
        self._series = series
        self._validator = validator or HistoricalDataQualityValidator()
        self._allow_incomplete = allow_incomplete
        self._point_in_time_resolver = point_in_time_resolver
        self._quality = None

    @property
    def quality(self):
        if self._quality is None:
            self._quality = self._validator.validate(self._series)
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
        frames: list[ReplayFrame] = []
        for index, item in enumerate(self._series):
            context = None
            if self._point_in_time_resolver is not None:
                context = self._point_in_time_resolver.resolve(
                    str(item.snapshot.instrument),
                    item.snapshot.timestamp,
                )
            frames.append(ReplayFrame(observation=item, index=index, point_in_time=context))
        return tuple(frames)

    def run(self, callback: Callable[[ReplayFrame], None]) -> int:
        count = 0
        for frame in self.frames():
            callback(frame)
            count += 1
        return count
