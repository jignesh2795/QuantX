"""Authoritative historical-data quality contract for QuantX research and replay.

The quality gate separates structural usability from completeness evidence.
It never repairs, sorts, fabricates, or silently infers missing market data.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId

from .calendar import HistoricalCalendar
from .data import HistoricalObservation


class DataQualityStatus(StrEnum):
    """Structural quality of historical input.

    COMPLETE/INCOMPLETE/BLOCKED remain aliases for the former replay-facing
    vocabulary so existing callers continue to resolve to the same canonical
    enum members.
    """

    VALID = "VALID"
    VALID_WITH_WARNINGS = "VALID_WITH_WARNINGS"
    DEGRADED = "DEGRADED"
    REJECTED = "REJECTED"

    COMPLETE = "VALID"
    INCOMPLETE = "DEGRADED"
    BLOCKED = "REJECTED"


class CompletenessStatus(StrEnum):
    """Degree to which completeness is established by explicit evidence."""

    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class DataIssueType(StrEnum):
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    GAP = "GAP"
    INSTRUMENT_MISMATCH = "INSTRUMENT_MISMATCH"
    MISSING_EXPECTED_TIMESTAMP = "MISSING_EXPECTED_TIMESTAMP"
    UNEXPECTED_TIMESTAMP = "UNEXPECTED_TIMESTAMP"
    INVALID_INPUT = "INVALID_INPUT"
    NO_DATA = "NO_DATA"
    CALENDAR_UNKNOWN = "CALENDAR_UNKNOWN"


HistoricalValue = HistoricalObservation | Candle


@dataclass(frozen=True, slots=True)
class DataIssue:
    issue_type: DataIssueType
    message: str
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class HistoricalDataQuality:
    """Machine-readable evidence about one historical data collection."""

    quality: DataQualityStatus
    completeness: CompletenessStatus
    observation_count: int
    expected_count: int | None
    missing_timestamps: tuple[datetime, ...]
    unexpected_timestamps: tuple[datetime, ...]
    duplicate_timestamps: tuple[datetime, ...]
    out_of_order: bool
    issues: tuple[DataIssue, ...]
    calendar_version: str | None = None
    calendar_unknown_timestamps: tuple[datetime, ...] = ()

    @property
    def status(self) -> DataQualityStatus:
        """Compatibility view using the former replay-facing vocabulary."""

        if self.quality in {
            DataQualityStatus.VALID,
            DataQualityStatus.VALID_WITH_WARNINGS,
        }:
            return DataQualityStatus.COMPLETE
        if self.quality is DataQualityStatus.DEGRADED:
            return DataQualityStatus.INCOMPLETE
        return DataQualityStatus.BLOCKED

    @property
    def can_replay(self) -> bool:
        """Whether replay is structurally permitted.

        DEGRADED input is replayable only when the caller explicitly opts into
        incomplete/degraded-fidelity replay. REJECTED input is never replayable.
        """

        return self.quality is not DataQualityStatus.REJECTED

    @property
    def is_complete(self) -> bool:
        return self.completeness is CompletenessStatus.COMPLETE


class HistoricalDataQualityGate:
    """Validate historical input without repairing or fabricating data."""

    def validate(
        self,
        observations: Iterable[HistoricalValue],
        *,
        expected_instrument: InstrumentId | None = None,
        expected_interval_seconds: int | None = None,
        expected_timestamps: Iterable[datetime] | None = None,
        calendar: HistoricalCalendar | None = None,
    ) -> HistoricalDataQuality:
        values = tuple(observations)
        expected = (
            None if expected_timestamps is None else tuple(expected_timestamps)
        )

        issues: list[DataIssue] = []
        observed_timestamps: list[datetime] = []
        duplicate_timestamps: set[datetime] = set()
        seen_timestamps: set[datetime] = set()
        calendar_unknown_timestamps: set[datetime] = set()
        previous_timestamp: datetime | None = None
        out_of_order = False

        for value in values:
            if not isinstance(value, (HistoricalObservation, Candle)):
                issues.append(
                    DataIssue(
                        DataIssueType.INVALID_INPUT,
                        "observations must be canonical historical observations",
                    )
                )
                continue

            timestamp = value.timestamp
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                issues.append(
                    DataIssue(
                        DataIssueType.INVALID_TIMESTAMP,
                        "timestamp must be timezone-aware",
                        timestamp,
                    )
                )
                continue

            observed_timestamps.append(timestamp)
            if timestamp in seen_timestamps:
                duplicate_timestamps.add(timestamp)
                issues.append(
                    DataIssue(
                        DataIssueType.DUPLICATE,
                        "duplicate observation timestamp",
                        timestamp,
                    )
                )
            seen_timestamps.add(timestamp)

            if (
                expected_instrument is not None
                and value.instrument != expected_instrument
            ):
                issues.append(
                    DataIssue(
                        DataIssueType.INSTRUMENT_MISMATCH,
                        "observation instrument does not match expected instrument",
                        timestamp,
                    )
                )

            if previous_timestamp is not None:
                if timestamp < previous_timestamp:
                    out_of_order = True
                    issues.append(
                        DataIssue(
                            DataIssueType.OUT_OF_ORDER,
                            "observations are not chronologically ordered",
                            timestamp,
                        )
                    )
                if (
                    expected_interval_seconds is not None
                    and timestamp > previous_timestamp
                    and (timestamp - previous_timestamp).total_seconds()
                    > expected_interval_seconds
                ):
                    if expected_interval_seconds <= 0:
                        raise ValueError("expected_interval_seconds must be positive")

                    gap_detected = True
                    unknown_calendar_timestamps: set[datetime] = set()

                    if calendar is not None:
                        gap_detected = False
                        candidate = previous_timestamp + timedelta(
                            seconds=expected_interval_seconds
                        )
                        while candidate < timestamp:
                            expectation = calendar.historical_timestamp_expected(candidate)
                            if expectation is True:
                                gap_detected = True
                                break
                            if expectation is None:
                                unknown_calendar_timestamps.add(candidate)
                            candidate += timedelta(seconds=expected_interval_seconds)

                        if unknown_calendar_timestamps:
                            calendar_unknown_timestamps.update(
                                unknown_calendar_timestamps
                            )
                            issues.append(
                                DataIssue(
                                    DataIssueType.CALENDAR_UNKNOWN,
                                    "calendar expectation is unknown for one or more gap candidates",
                                    min(unknown_calendar_timestamps),
                                )
                            )

                    if gap_detected:
                        issues.append(
                            DataIssue(
                                DataIssueType.GAP,
                                "historical data gap detected",
                                timestamp,
                            )
                        )
            previous_timestamp = timestamp

        observed_set = set(observed_timestamps)
        missing_timestamps: tuple[datetime, ...] = ()
        unexpected_timestamps: tuple[datetime, ...] = ()

        if expected is not None:
            invalid_expected = tuple(
                value
                for value in expected
                if value.tzinfo is None or value.utcoffset() is None
            )
            if invalid_expected:
                for timestamp in invalid_expected:
                    issues.append(
                        DataIssue(
                            DataIssueType.INVALID_TIMESTAMP,
                            "expected timestamp must be timezone-aware",
                            timestamp,
                        )
                    )
            else:
                expected_set = set(expected)
                missing_timestamps = tuple(sorted(expected_set - observed_set))
                unexpected_timestamps = tuple(sorted(observed_set - expected_set))
                for timestamp in missing_timestamps:
                    issues.append(
                        DataIssue(
                            DataIssueType.MISSING_EXPECTED_TIMESTAMP,
                            "expected timestamp is missing from observations",
                            timestamp,
                        )
                    )
                for timestamp in unexpected_timestamps:
                    issues.append(
                        DataIssue(
                            DataIssueType.UNEXPECTED_TIMESTAMP,
                            "observed timestamp was not in expected set",
                            timestamp,
                        )
                    )

        if not values and expected not in (None, ()):
            issues.append(DataIssue(DataIssueType.NO_DATA, "no observations supplied"))

        blocking_types = {
            DataIssueType.INVALID_INPUT,
            DataIssueType.INVALID_TIMESTAMP,
            DataIssueType.INSTRUMENT_MISMATCH,
        }
        quality = (
            DataQualityStatus.REJECTED
            if any(issue.issue_type in blocking_types for issue in issues)
            else DataQualityStatus.DEGRADED
            if issues
            else DataQualityStatus.VALID
            if expected is not None
            else DataQualityStatus.VALID_WITH_WARNINGS
        )

        if expected is None:
            completeness = CompletenessStatus.UNKNOWN
        elif any(issue.issue_type is DataIssueType.INVALID_TIMESTAMP for issue in issues):
            completeness = CompletenessStatus.UNKNOWN
        elif any(
            issue.issue_type
            in {
                DataIssueType.MISSING_EXPECTED_TIMESTAMP,
                DataIssueType.UNEXPECTED_TIMESTAMP,
                DataIssueType.GAP,
            }
            for issue in issues
        ):
            completeness = CompletenessStatus.INCOMPLETE
        else:
            completeness = CompletenessStatus.COMPLETE

        return HistoricalDataQuality(
            quality=quality,
            completeness=completeness,
            observation_count=len(values),
            expected_count=None if expected is None else len(expected),
            missing_timestamps=missing_timestamps,
            unexpected_timestamps=unexpected_timestamps,
            duplicate_timestamps=tuple(sorted(duplicate_timestamps)),
            out_of_order=out_of_order,
            issues=tuple(issues),
            calendar_version=None if calendar is None else calendar.version,
            calendar_unknown_timestamps=tuple(sorted(calendar_unknown_timestamps)),
        )


def assess_candles(
    candles: Iterable[Candle],
    expected_timestamps: Iterable[datetime] | None = None,
) -> HistoricalDataQuality:
    """Assess canonical candles through the same authoritative quality gate."""

    return HistoricalDataQualityGate().validate(
        candles,
        expected_timestamps=expected_timestamps,
    )


__all__ = [
    "CompletenessStatus",
    "DataIssue",
    "DataIssueType",
    "DataQualityStatus",
    "HistoricalDataQuality",
    "HistoricalDataQualityGate",
    "HistoricalValue",
    "assess_candles",
]
