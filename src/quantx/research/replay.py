"""Deterministic chronological replay over quality-validated historical observations.

Replay is payload-neutral: sequencing and point-in-time resolution use only
the observation instrument and timestamp, so quote-backed and candle-backed
observations replay unchanged with no Candle-to-Quote conversion.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from quantx.domain.value_objects import InstrumentId

from .data import HistoricalDataSeries, HistoricalObservation
from .point_in_time import PointInTimeContext, PointInTimeContextResolver
from .quality import DataQualityStatus, HistoricalDataQuality, HistoricalDataQualityGate

HistoricalDataQualityValidator = HistoricalDataQualityGate


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
        validator: HistoricalDataQualityGate | None = None,
        quality_gate: HistoricalDataQualityGate | None = None,
        allow_incomplete: bool = False,
        point_in_time_resolver: PointInTimeContextResolver | None = None,
        expected_instrument: InstrumentId | None = None,
        expected_interval_seconds: int | None = None,
    ) -> None:
        self._series = series
        self._validator = validator or quality_gate or HistoricalDataQualityGate()
        self._allow_incomplete = allow_incomplete
        self._point_in_time_resolver = point_in_time_resolver
        self._expected_instrument = expected_instrument
        self._expected_interval_seconds = expected_interval_seconds
        self._quality: HistoricalDataQuality | None = None

    @property
    def quality(self) -> HistoricalDataQuality:
        if self._quality is None:
            observations = tuple(self._series)
            self._quality = self._validator.validate(
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
                "historical dataset is incomplete; "
                "set allow_incomplete=True to run degraded-fidelity replay"
            )

    def frames(self) -> tuple[ReplayFrame, ...]:
        self._ensure_replayable()
        frames: list[ReplayFrame] = []
        for index, item in enumerate(self._series):
            context = None
            if self._point_in_time_resolver is not None:
                context = self._point_in_time_resolver.resolve(
                    str(item.instrument),
                    item.timestamp,
                )
            frames.append(ReplayFrame(observation=item, index=index, point_in_time=context))
        return tuple(frames)

    def run(self, callback: Callable[[ReplayFrame], None]) -> int:
        count = 0
        for frame in self.frames():
            callback(frame)
            count += 1
        return count
