"""Deterministic chronological replay over quality-validated historical observations.

Replay is payload-neutral: sequencing and point-in-time resolution use only
the observation instrument and timestamp, so quote-backed and candle-backed
observations replay unchanged with no Candle-to-Quote conversion.

A replay consumes either one HistoricalDataSeries or an explicit sequence of
HistoricalDataSeries (one per instrument). Each constituent series keeps the
single-instrument HistoricalDataSeries contract and is validated
independently; multi-series observations are merged into one deterministic
chronological stream. Equal timestamps across different instruments are
distinct observations, never duplicates.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
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


MultiSeries = tuple[HistoricalDataSeries, ...]


class HistoricalReplay:
    """Replay observations only after enforcing data quality and optional point-in-time rules."""

    def __init__(
        self,
        series: HistoricalDataSeries | Sequence[HistoricalDataSeries],
        *,
        validator: HistoricalDataQualityGate | None = None,
        quality_gate: HistoricalDataQualityGate | None = None,
        allow_incomplete: bool = False,
        point_in_time_resolver: PointInTimeContextResolver | None = None,
        expected_instrument: InstrumentId | None = None,
        expected_interval_seconds: int | None = None,
    ) -> None:
        if isinstance(series, HistoricalDataSeries):
            series_tuple: MultiSeries = (series,)
        elif isinstance(series, Sequence):
            series_tuple = tuple(series)
        else:
            raise TypeError(
                "replay requires a HistoricalDataSeries or a sequence of HistoricalDataSeries"
            )
        if not series_tuple:
            raise ValueError("replay requires at least one HistoricalDataSeries")
        for entry in series_tuple:
            if not isinstance(entry, HistoricalDataSeries):
                raise TypeError("every multi-series entry must be a HistoricalDataSeries")
        self._series: MultiSeries = series_tuple
        self._validator = validator or quality_gate or HistoricalDataQualityGate()
        self._allow_incomplete = allow_incomplete
        self._point_in_time_resolver = point_in_time_resolver
        self._expected_instrument = expected_instrument
        self._expected_interval_seconds = expected_interval_seconds
        self._quality: HistoricalDataQuality | None = None

    @property
    def quality(self) -> HistoricalDataQuality:
        if self._quality is None:
            if len(self._series) == 1:
                observations = tuple(self._series[0])
                self._quality = self._validator.validate(
                    observations,
                    expected_instrument=self._expected_instrument,
                    expected_interval_seconds=self._expected_interval_seconds,
                )
                return self._quality
            if self._expected_instrument is not None:
                raise ValueError(
                    "expected_instrument is ambiguous for multi-series replay; "
                    "each constituent series is validated independently"
                )
            first_blocked: HistoricalDataQuality | None = None
            first_incomplete: HistoricalDataQuality | None = None
            first_quality: HistoricalDataQuality | None = None
            for constituent in self._series:
                assessed = self._validator.validate(
                    tuple(constituent),
                    expected_instrument=None,
                    expected_interval_seconds=self._expected_interval_seconds,
                )
                if first_quality is None:
                    first_quality = assessed
                if assessed.status is DataQualityStatus.BLOCKED:
                    if first_blocked is None:
                        first_blocked = assessed
                elif assessed.status is DataQualityStatus.INCOMPLETE:
                    if first_incomplete is None:
                        first_incomplete = assessed
            if first_blocked is not None:
                self._quality = first_blocked
            elif first_incomplete is not None:
                self._quality = first_incomplete
            else:
                assert first_quality is not None
                self._quality = first_quality
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

    def _merge_observations(self) -> tuple[HistoricalObservation, ...]:
        merged: list[HistoricalObservation] = []
        for constituent in self._series:
            merged.extend(constituent)
        return tuple(
            sorted(
                merged,
                key=lambda item: (
                    item.timestamp,
                    item.sequence,
                    str(item.instrument),
                ),
            )
        )

    def frames(self) -> tuple[ReplayFrame, ...]:
        self._ensure_replayable()
        frames: list[ReplayFrame] = []
        for index, item in enumerate(self._merge_observations()):
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
