"""Historical-data quality gates for QuantX research and replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .data import HistoricalObservation


class DataQualityStatus(StrEnum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    BLOCKED = "BLOCKED"


class DataIssueType(StrEnum):
    DUPLICATE = "DUPLICATE"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    INVALID_TIMESTAMP = "INVALID_TIMESTAMP"
    GAP = "GAP"
    INSTRUMENT_MISMATCH = "INSTRUMENT_MISMATCH"


@dataclass(frozen=True, slots=True)
class DataIssue:
    issue_type: DataIssueType
    message: str
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    status: DataQualityStatus
    observations_checked: int
    issues: tuple[DataIssue, ...]

    @property
    def can_replay(self) -> bool:
        return self.status is not DataQualityStatus.BLOCKED


class HistoricalDataQualityGate:
    """Validate replay input without silently repairing or fabricating data."""

    def validate(
        self,
        observations: tuple[HistoricalObservation, ...],
        *,
        expected_instrument=None,
        expected_interval_seconds: int | None = None,
    ) -> DataQualityReport:
        issues: list[DataIssue] = []
        previous: HistoricalObservation | None = None
        seen: set[tuple[datetime, int]] = set()

        for observation in observations:
            timestamp = observation.timestamp
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                issues.append(DataIssue(DataIssueType.INVALID_TIMESTAMP, "timestamp must be timezone-aware", timestamp))
                continue

            key = (timestamp, observation.sequence)
            if key in seen:
                issues.append(DataIssue(DataIssueType.DUPLICATE, "duplicate observation", timestamp))
            seen.add(key)

            if expected_instrument is not None and observation.instrument != expected_instrument:
                issues.append(DataIssue(DataIssueType.INSTRUMENT_MISMATCH, "observation instrument does not match replay instrument", timestamp))

            if previous is not None:
                if timestamp < previous.timestamp or (
                    timestamp == previous.timestamp and observation.sequence < previous.sequence
                ):
                    issues.append(DataIssue(DataIssueType.OUT_OF_ORDER, "observations are not chronologically ordered", timestamp))
                if (
                    expected_interval_seconds is not None
                    and timestamp > previous.timestamp
                    and (timestamp - previous.timestamp).total_seconds() > expected_interval_seconds
                ):
                    issues.append(DataIssue(DataIssueType.GAP, "historical data gap detected", timestamp))

            previous = observation

        blocking = any(issue.issue_type in {DataIssueType.INVALID_TIMESTAMP, DataIssueType.INSTRUMENT_MISMATCH} for issue in issues)
        status = DataQualityStatus.BLOCKED if blocking else DataQualityStatus.INCOMPLETE if issues else DataQualityStatus.COMPLETE
        return DataQualityReport(status, len(observations), tuple(issues))
