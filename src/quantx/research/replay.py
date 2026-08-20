"""Deterministic chronological replay over historical observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable

from .data import HistoricalObservation, HistoricalDataSeries


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    observation: HistoricalObservation
    index: int


class HistoricalReplay:
    """Replay observations in timestamp/sequence order without look-ahead."""

    def __init__(self, series: HistoricalDataSeries) -> None:
        self._series = series

    def frames(self) -> tuple[ReplayFrame, ...]:
        return tuple(ReplayFrame(observation=item, index=index) for index, item in enumerate(self._series))

    def run(self, callback: Callable[[ReplayFrame], None]) -> int:
        count = 0
        for frame in self.frames():
            callback(frame)
            count += 1
        return count
