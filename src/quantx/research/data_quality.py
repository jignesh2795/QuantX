"""Deterministic historical candle quality and completeness analysis.

This module answers whether an already available canonical candle
collection is structurally sound and, when the caller supplies an explicit
expected timestamp set, whether it is complete relative to that set. It
never infers a market schedule, repairs data, fabricates observations, or
verifies source files. Completeness without an explicit expectation set is
always reported as unknown.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from quantx.domain.market_data import Candle


class DataQualityStatus(StrEnum):
    VALID = "VALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    DEGRADED = "DEGRADED"
    REJECTED = "REJECTED"


class CompletenessStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class HistoricalDataQuality:
    """Machine-readable evidence about one candle collection."""

    quality: DataQualityStatus
    completeness: CompletenessStatus
    observation_count: int
    expected_count: int | None
    missing_timestamps: tuple[datetime, ...]
    unexpected_timestamps: tuple[datetime, ...]
    duplicate_timestamps: tuple[datetime, ...]
    out_of_order: bool
    issues: tuple[str, ...]


def assess_candles(
    candles: Iterable[Candle],
    expected_timestamps: Iterable[datetime] | None = None,
) -> HistoricalDataQuality:
    """Assess canonical candles without repairing or fabricating anything.

    Timestamps compare as instants, so equivalent moments in different
    offsets match. COMPLETE means complete relative to the explicitly
    supplied expected timestamp set, never globally verified completeness.
    """
    observed = tuple(candles)
    expected = None if expected_timestamps is None else tuple(expected_timestamps)
    for candle in observed:
        if not isinstance(candle, Candle):
            return _rejected(
                len(observed),
                None if expected is None else len(expected),
                "observations must be canonical candles",
            )
    if expected is not None:
        for value in expected:
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                return _rejected(
                    len(observed),
                    len(expected),
                    "expected timestamps must be timezone-aware datetimes",
                )
    observed_times = tuple(candle.timestamp for candle in observed)
    duplicates = _duplicates(observed_times)
    out_of_order = any(
        later < earlier for earlier, later in zip(observed_times, observed_times[1:], strict=False)
    )
    if expected is None:
        return _without_expectations(observed, duplicates, out_of_order)
    missing = tuple(sorted(set(expected) - set(observed_times)))
    unexpected = tuple(sorted(set(observed_times) - set(expected)))
    return _with_expectations(observed, expected, duplicates, out_of_order, missing, unexpected)


def _duplicates(values: tuple[datetime, ...]) -> tuple[datetime, ...]:
    seen: set[datetime] = set()
    repeated: set[datetime] = set()
    for value in values:
        if value in seen:
            repeated.add(value)
        seen.add(value)
    return tuple(sorted(repeated))


def _rejected(
    observation_count: int, expected_count: int | None, issue: str
) -> HistoricalDataQuality:
    return HistoricalDataQuality(
        quality=DataQualityStatus.REJECTED,
        completeness=CompletenessStatus.UNKNOWN,
        observation_count=observation_count,
        expected_count=expected_count,
        missing_timestamps=(),
        unexpected_timestamps=(),
        duplicate_timestamps=(),
        out_of_order=False,
        issues=(issue,),
    )


def _without_expectations(
    observed: tuple[Candle, ...],
    duplicates: tuple[datetime, ...],
    out_of_order: bool,
) -> HistoricalDataQuality:
    issues: list[str] = []
    if duplicates:
        issues.append("duplicate candle timestamps detected")
    if out_of_order:
        issues.append("observations are not in chronological order")
    if not observed:
        issues.append("no observations supplied")
        return HistoricalDataQuality(
            quality=DataQualityStatus.VALID_WITH_WARNINGS,
            completeness=CompletenessStatus.UNKNOWN,
            observation_count=0,
            expected_count=None,
            missing_timestamps=(),
            unexpected_timestamps=(),
            duplicate_timestamps=duplicates,
            out_of_order=out_of_order,
            issues=tuple(issues),
        )
    if issues:
        return HistoricalDataQuality(
            quality=DataQualityStatus.DEGRADED,
            completeness=CompletenessStatus.UNKNOWN,
            observation_count=len(observed),
            expected_count=None,
            missing_timestamps=(),
            unexpected_timestamps=(),
            duplicate_timestamps=duplicates,
            out_of_order=out_of_order,
            issues=tuple(issues),
        )
    return HistoricalDataQuality(
        quality=DataQualityStatus.VALID_WITH_WARNINGS,
        completeness=CompletenessStatus.UNKNOWN,
        observation_count=len(observed),
        expected_count=None,
        missing_timestamps=(),
        unexpected_timestamps=(),
        duplicate_timestamps=(),
        out_of_order=False,
        issues=("expected timestamp set was not supplied; completeness is unknown",),
    )


def _with_expectations(
    observed: tuple[Candle, ...],
    expected: tuple[datetime, ...],
    duplicates: tuple[datetime, ...],
    out_of_order: bool,
    missing: tuple[datetime, ...],
    unexpected: tuple[datetime, ...],
) -> HistoricalDataQuality:
    issues: list[str] = []
    if duplicates:
        issues.append("duplicate candle timestamps detected")
    if out_of_order:
        issues.append("observations are not in chronological order")
    if missing:
        issues.append("expected timestamps are missing from observations")
    if unexpected:
        issues.append("observed timestamps were not present in expected set")
    if not observed and not expected:
        return HistoricalDataQuality(
            quality=DataQualityStatus.VALID,
            completeness=CompletenessStatus.COMPLETE,
            observation_count=0,
            expected_count=0,
            missing_timestamps=(),
            unexpected_timestamps=(),
            duplicate_timestamps=(),
            out_of_order=False,
            issues=(),
        )
    if not observed:
        issues.append("no observations supplied")
    if issues:
        return HistoricalDataQuality(
            quality=DataQualityStatus.DEGRADED,
            completeness=CompletenessStatus.INCOMPLETE,
            observation_count=len(observed),
            expected_count=len(expected),
            missing_timestamps=missing,
            unexpected_timestamps=unexpected,
            duplicate_timestamps=duplicates,
            out_of_order=out_of_order,
            issues=tuple(issues),
        )
    return HistoricalDataQuality(
        quality=DataQualityStatus.VALID,
        completeness=CompletenessStatus.COMPLETE,
        observation_count=len(observed),
        expected_count=len(expected),
        missing_timestamps=(),
        unexpected_timestamps=(),
        duplicate_timestamps=(),
        out_of_order=False,
        issues=(),
    )


__all__ = [
    "CompletenessStatus",
    "DataQualityStatus",
    "HistoricalDataQuality",
    "assess_candles",
]
