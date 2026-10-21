"""Read-only operator worklist over durable quarantined submission evidence.

Quarantined observations are deliberately non-authoritative: they never
complete idempotency, never become canonical receipts, and never affect
accounting. This service is the first consumer of that evidence. It exists so
an operator can see which submissions still need manual reconciliation; it
does not reconcile anything.

Contract:

- reads only; no evidence, reservation, gate, receipt, idempotency, or
  lifecycle state is created, updated, or marked resolved;
- no broker, exchange, transport, or network access -- local durable evidence
  only;
- a read/decoding failure returns an explicit ``UNAVAILABLE`` result, never an
  empty worklist that could be misread as "nothing to reconcile";
- output is deterministically ordered by observation time and stable
  observation identity, and bounded by a caller-supplied limit;
- items expose only the already-sanitized quarantine record, which the write
  path bounded. No raw broker payload, credential, or unbounded exception text
  is reproduced here.

Resolving an item requires a separately authorized operator action; this
module intentionally provides no acknowledge/resolve/retry surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from quantx.execution.receipts.quarantine import (
    QuarantinedSubmissionObservation,
    QuarantineEvidenceDecodeError,
)
from quantx.ports.persistence import SubmissionQuarantineRepository

DEFAULT_WORKLIST_LIMIT = 100
MAX_WORKLIST_LIMIT = 1000
_MAX_ERROR_LENGTH = 512


class QuarantineWorklistStatus(StrEnum):
    """Whether the durable evidence was actually read."""

    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"


class QuarantineEvidenceState(StrEnum):
    """Every quarantined observation is unresolved pending reconciliation."""

    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class QuarantineWorklistItem:
    """One unresolved, non-authoritative quarantined submission observation."""

    observation: QuarantinedSubmissionObservation
    state: QuarantineEvidenceState = QuarantineEvidenceState.UNRESOLVED

    def __post_init__(self) -> None:
        if not isinstance(self.observation, QuarantinedSubmissionObservation):
            raise ValueError("worklist item observation must be a quarantine record")
        if self.state is not QuarantineEvidenceState.UNRESOLVED:
            raise ValueError("quarantined evidence cannot be in a resolved state")


@dataclass(frozen=True, slots=True)
class QuarantineWorklist:
    """Result of one read-only worklist pass.

    ``OK`` with no items means the read succeeded and nothing needs operator
    reconciliation. ``UNAVAILABLE`` means the evidence could not be read, so
    nothing may be concluded about outstanding work.
    """

    status: QuarantineWorklistStatus
    items: tuple[QuarantineWorklistItem, ...] = ()
    error: str | None = None
    truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.status, QuarantineWorklistStatus):
            raise ValueError("worklist status must be a QuarantineWorklistStatus")
        if any(not isinstance(item, QuarantineWorklistItem) for item in self.items):
            raise ValueError("worklist items must be QuarantineWorklistItem values")
        if self.status is QuarantineWorklistStatus.OK:
            if self.error is not None:
                raise ValueError("a successful worklist read cannot carry an error")
            return
        if self.items:
            raise ValueError("an unavailable worklist cannot expose items")
        if self.truncated:
            raise ValueError("an unavailable worklist cannot report truncation")
        if not isinstance(self.error, str) or not self.error.strip():
            raise ValueError("an unavailable worklist requires an error reason")
        if len(self.error) > _MAX_ERROR_LENGTH:
            raise ValueError("worklist error reason must be bounded")

    @property
    def available(self) -> bool:
        return self.status is QuarantineWorklistStatus.OK

    @property
    def requires_operator_reconciliation(self) -> bool:
        """Whether an operator must act; unreadable evidence is never "clear".

        An ``UNAVAILABLE`` read always requires attention: nothing may be
        concluded about outstanding work, so it must not present as a resolved
        or empty queue to an operator or automated caller.
        """
        return self.status is QuarantineWorklistStatus.UNAVAILABLE or bool(self.items)


class QuarantineWorklistReadService:
    """List unresolved quarantined submissions without changing anything."""

    def __init__(self, *, quarantine: SubmissionQuarantineRepository) -> None:
        self._quarantine = quarantine

    def read(self, *, limit: int = DEFAULT_WORKLIST_LIMIT) -> QuarantineWorklist:
        """Return the bounded, ordered worklist of unresolved evidence.

        ``limit`` bounds operator-visible output; ``truncated`` reports
        whether more evidence exists beyond it. Invalid limits fail closed
        before any store access.
        """
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("worklist limit must be an integer")
        if limit < 1 or limit > MAX_WORKLIST_LIMIT:
            raise ValueError(f"worklist limit must be between 1 and {MAX_WORKLIST_LIMIT}")
        try:
            observations = self._quarantine.list_all()
        except QuarantineEvidenceDecodeError as exc:
            return QuarantineWorklist(
                status=QuarantineWorklistStatus.UNAVAILABLE,
                error=(
                    f"quarantine evidence could not be decoded for observation {exc.observation_id}"
                ),
            )
        except Exception as exc:
            return QuarantineWorklist(
                status=QuarantineWorklistStatus.UNAVAILABLE,
                error=f"quarantine evidence read failed: {type(exc).__name__}",
            )

        ordered = tuple(
            sorted(
                observations,
                key=lambda observation: (
                    observation.observed_at,
                    str(observation.observation_id),
                ),
            )
        )
        truncated = len(ordered) > limit
        items = tuple(
            QuarantineWorklistItem(observation=observation) for observation in ordered[:limit]
        )
        return QuarantineWorklist(
            status=QuarantineWorklistStatus.OK,
            items=items,
            truncated=truncated,
        )


__all__ = [
    "DEFAULT_WORKLIST_LIMIT",
    "MAX_WORKLIST_LIMIT",
    "QuarantineEvidenceState",
    "QuarantineWorklist",
    "QuarantineWorklistItem",
    "QuarantineWorklistReadService",
    "QuarantineWorklistStatus",
]
