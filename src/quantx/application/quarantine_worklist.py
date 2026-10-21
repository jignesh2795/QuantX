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
  observation identity, and bounded by a caller-supplied limit with an opaque
  continuation cursor for evidence beyond the first page;
- items expose only the bounded quarantine record. Untrusted text must be
  rendered through :func:`render_quarantine_worklist_item`, which neutralizes
  control characters; no raw broker payload, credential, or unbounded
  exception text is reproduced here.

Resolving an item requires a separately authorized operator action; this
module intentionally provides no acknowledge/resolve/retry surface.
"""

from __future__ import annotations

import base64
import binascii
import json
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from quantx.execution.receipts.quarantine import (
    QuarantinedSubmissionObservation,
    QuarantineEvidenceDecodeError,
    QuarantineEvidenceTooLarge,
)
from quantx.ports.persistence import SubmissionQuarantineRepository

DEFAULT_WORKLIST_LIMIT = 100
MAX_WORKLIST_LIMIT = 1000
_MAX_ERROR_LENGTH = 512
_MAX_DISPLAY_FIELD_LENGTH = 1024
_MAX_RENDER_LENGTH = 4096
_MAX_CURSOR_LENGTH = 512
_CURSOR_VERSION = 1
_CURSOR_FIELDS = frozenset({"version", "observed_at", "observation_id"})


def _display_text(value: object, *, max_length: int = _MAX_DISPLAY_FIELD_LENGTH) -> str:
    """Neutralize terminal control characters in an untrusted display value."""
    try:
        text = str(value)
    except Exception:
        text = f"<{type(value).__name__}>"
    text = text[:max_length]
    escaped = "".join(
        {
            "\n": "\\n",
            "\r": "\\r",
            "\t": "\\t",
        }.get(
            character,
            (
                character
                if 0x20 <= ord(character) <= 0x7E
                or 0xA0 <= ord(character) <= 0x2027
                or ord(character) >= 0x202A
                else (
                    f"\\x{ord(character):02x}"
                    if ord(character) <= 0xFF
                    else f"\\u{ord(character):04x}"
                )
            ),
        )
        for character in text
    )
    if len(escaped) > max_length:
        return f"{escaped[: max_length - 3]}..."
    return escaped


def _bounded_error(message: str) -> str:
    """Keep an operator-facing failure reason bounded and display-safe."""
    return _display_text(message, max_length=_MAX_ERROR_LENGTH)


def _encode_cursor(observation: QuarantinedSubmissionObservation) -> str:
    payload = json.dumps(
        {
            "observation_id": str(observation.observation_id),
            "observed_at": observation.observed_at.isoformat(),
            "version": _CURSOR_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def _decode_cursor(cursor: str) -> tuple[datetime, str]:
    if type(cursor) is not str or not cursor.strip() or len(cursor) > _MAX_CURSOR_LENGTH:
        raise ValueError("worklist cursor must be a bounded non-empty string")
    try:
        decoded = base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True)
        data = json.loads(decoded)
    except (UnicodeEncodeError, binascii.Error, TypeError, ValueError) as exc:
        raise ValueError("worklist cursor is invalid") from exc
    if type(data) is not dict or set(data) != _CURSOR_FIELDS:
        raise ValueError("worklist cursor is invalid")
    if type(data["version"]) is not int or data["version"] != _CURSOR_VERSION:
        raise ValueError("worklist cursor is invalid")
    observed_at = data["observed_at"]
    observation_id = data["observation_id"]
    if type(observed_at) is not str or type(observation_id) is not str:
        raise ValueError("worklist cursor is invalid")
    try:
        parsed_at = datetime.fromisoformat(observed_at)
        parsed_id = UUID(observation_id)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("worklist cursor is invalid") from exc
    if parsed_at.tzinfo is None or parsed_at.utcoffset() is None:
        raise ValueError("worklist cursor is invalid")
    return parsed_at, str(parsed_id)


def render_quarantine_worklist_item(item: QuarantineWorklistItem) -> str:
    """Render one item for a terminal with all untrusted text neutralized.

    Persisted evidence is not modified. Newlines, carriage returns, tabs,
    ANSI escape bytes, NUL, and all other C0/C1 control characters are shown
    as printable escape sequences, so broker-derived text cannot inject
    terminal commands or forge additional worklist entries.
    """
    if not isinstance(item, QuarantineWorklistItem):
        raise ValueError("worklist renderer requires a QuarantineWorklistItem")
    observation = item.observation
    fields = (
        ("state", item.state.value),
        ("kind", observation.kind.value),
        ("observation_id", str(observation.observation_id)),
        ("client_order_id", str(observation.client_order_id)),
        ("observed_at", observation.observed_at.isoformat()),
        ("reason", observation.reason),
        ("request_correlation_id", observation.request_correlation_id),
        ("source", observation.source),
        ("broker_order_id", observation.broker_order_id),
        ("outcome", observation.outcome),
        ("order_status", observation.order_status),
    )
    rendered = "\n".join(f"{name}: {_display_text(value)}" for name, value in fields)
    if len(rendered) > _MAX_RENDER_LENGTH:
        return f"{rendered[: _MAX_RENDER_LENGTH - 3]}..."
    return rendered


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
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, QuarantineWorklistStatus):
            raise ValueError("worklist status must be a QuarantineWorklistStatus")
        if not isinstance(self.items, tuple):
            raise ValueError("worklist items must be a tuple")
        if any(not isinstance(item, QuarantineWorklistItem) for item in self.items):
            raise ValueError("worklist items must be QuarantineWorklistItem values")
        if type(self.truncated) is not bool:
            raise ValueError("worklist truncation flag must be a boolean")
        if self.next_cursor is not None:
            if type(self.next_cursor) is not str or not self.next_cursor.strip():
                raise ValueError("worklist cursor must be a non-empty string")
            if len(self.next_cursor) > _MAX_CURSOR_LENGTH:
                raise ValueError("worklist cursor must be bounded")
        if self.status is QuarantineWorklistStatus.OK:
            if self.error is not None:
                raise ValueError("a successful worklist read cannot carry an error")
            if not self.items and (self.truncated or self.next_cursor is not None):
                raise ValueError("an empty worklist cannot be truncated or paginated")
            if self.truncated != (self.next_cursor is not None):
                raise ValueError("worklist cursor and truncation flag must agree")
            return
        if self.items:
            raise ValueError("an unavailable worklist cannot expose items")
        if self.truncated:
            raise ValueError("an unavailable worklist cannot report truncation")
        if self.next_cursor is not None:
            raise ValueError("an unavailable worklist cannot carry a cursor")
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

    def read(
        self,
        *,
        limit: int = DEFAULT_WORKLIST_LIMIT,
        cursor: str | None = None,
    ) -> QuarantineWorklist:
        """Return one bounded, ordered page of unresolved evidence.

        ``limit`` bounds operator-visible output. ``cursor`` is the opaque
        ``next_cursor`` from the previous page; its ordering key is
        ``(observed_at, observation_id)``, so pages never overlap and do not
        rely on rowid or offset. ``truncated`` is true exactly when a
        ``next_cursor`` is returned. Invalid limits and cursors fail closed
        before any store access.
        """
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("worklist limit must be an integer")
        if limit < 1 or limit > MAX_WORKLIST_LIMIT:
            raise ValueError(f"worklist limit must be between 1 and {MAX_WORKLIST_LIMIT}")
        cursor_key = _decode_cursor(cursor) if cursor is not None else None
        try:
            observations = self._quarantine.list_all()
            if not isinstance(observations, tuple):
                raise TypeError("quarantine repository returned a non-tuple result")
            if any(
                not isinstance(observation, QuarantinedSubmissionObservation)
                for observation in observations
            ):
                raise TypeError("quarantine repository returned an invalid observation")
            ordered = tuple(
                sorted(
                    observations,
                    key=lambda observation: (
                        observation.observed_at,
                        str(observation.observation_id),
                    ),
                )
            )
            keys = [
                (observation.observed_at, str(observation.observation_id))
                for observation in ordered
            ]
            if len(set(keys)) != len(keys):
                raise ValueError("quarantine repository returned duplicate observation identities")
            start = bisect_right(keys, cursor_key) if cursor_key is not None else 0
            page = ordered[start : start + limit]
            truncated = start + limit < len(ordered)
            items = tuple(QuarantineWorklistItem(observation=observation) for observation in page)
            return QuarantineWorklist(
                status=QuarantineWorklistStatus.OK,
                items=items,
                truncated=truncated,
                next_cursor=_encode_cursor(page[-1]) if truncated else None,
            )
        except QuarantineEvidenceDecodeError as exc:
            return QuarantineWorklist(
                status=QuarantineWorklistStatus.UNAVAILABLE,
                error=_bounded_error(f"quarantine evidence could not be decoded: {exc}"),
            )
        except QuarantineEvidenceTooLarge as exc:
            return QuarantineWorklist(
                status=QuarantineWorklistStatus.UNAVAILABLE,
                error=_bounded_error(str(exc)),
            )
        except Exception as exc:
            return QuarantineWorklist(
                status=QuarantineWorklistStatus.UNAVAILABLE,
                error=_bounded_error(f"quarantine evidence read failed: {type(exc).__name__}"),
            )


__all__ = [
    "DEFAULT_WORKLIST_LIMIT",
    "MAX_WORKLIST_LIMIT",
    "QuarantineEvidenceState",
    "QuarantineWorklist",
    "QuarantineWorklistItem",
    "QuarantineWorklistReadService",
    "QuarantineWorklistStatus",
    "render_quarantine_worklist_item",
]
