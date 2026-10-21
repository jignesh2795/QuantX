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
  single-pass continuation cursor for evidence beyond the first page;
- items expose only the bounded quarantine record. Untrusted text must be
  rendered through :func:`render_quarantine_worklist_item`, which neutralizes
  control characters, bidirectional and other invisible Unicode format
  characters, and lone surrogates; no raw broker payload, credential, or
  unbounded exception text is reproduced here.

This is a bounded inspection view over one readable snapshot, not a guarantee
of complete inventory at arbitrary table sizes. The underlying adapter reports
an explicit ``UNAVAILABLE`` above its row and per-row bounds; it never presents
a truncated or over-bound store as a partial or empty worklist.

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
    QuarantineEvidenceUnavailable,
    neutralize_display_text,
)
from quantx.ports.persistence import QuarantineEvidenceReader

DEFAULT_WORKLIST_LIMIT = 100
MAX_WORKLIST_LIMIT = 1000
_MAX_ERROR_LENGTH = 512
_MAX_DISPLAY_FIELD_LENGTH = 1024
_MAX_RENDER_LENGTH = 4096
_MAX_CURSOR_LENGTH = 512
_CURSOR_VERSION = 1
_CURSOR_FIELDS = frozenset({"version", "observed_at", "observation_id"})


class _CursorAttributionError(ValueError):
    """A well-formed cursor does not belong to the evidence just read.

    Raised for a cursor whose ordering anchor is absent from the readable
    set -- a reused cursor from another database or inspection run, or one
    whose anchor was removed by a source mutation. The caller must restart
    from the initial cursor; silently continuing would present a partial view.
    """


def _display_text(value: object, *, max_length: int = _MAX_DISPLAY_FIELD_LENGTH) -> str:
    """Neutralize untrusted display text through the shared evidence renderer."""
    return neutralize_display_text(value, max_length=max_length)


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
    ANSI escape bytes, NUL, all other C0/C1 control characters, Unicode
    line/paragraph separators, bidirectional formatting/isolate controls
    (including U+200F, U+202E, and U+2066), every other invisible Unicode
    format character (category ``Cf``, such as U+200B, U+2060, and U+FEFF),
    and lone surrogates are shown as printable escape sequences, so
    broker-derived text cannot inject terminal commands, reorder surrounding
    text, hide characters, forge additional worklist entries, or break the
    terminal encoder. Zero-width non-joiner and zero-width joiner (U+200C and
    U+200D) are deliberately retained: several scripts and emoji sequences
    need them to render correctly.
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
    """List unresolved quarantined submissions without changing anything.

    This is a bounded inspection view over one read-only evidence store, not a
    complete-inventory or live-monitoring service. See the module docstring for
    the row and payload bounds and for the operator escalation procedure.
    """

    def __init__(self, *, quarantine: QuarantineEvidenceReader) -> None:
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

        Cursor lifetime is one inspection pass against one unchanged store.
        Every call reads a fresh snapshot, so a pass requires a quiesced or
        offline source: after any source mutation (including deletions) the
        operator must restart from the initial cursor rather than mixing pages
        from different snapshots. A well-formed cursor whose ordering anchor is
        absent from the readable evidence -- a cursor from another database or
        an earlier run, or one invalidated by mutation -- is rejected with
        ``ValueError`` instead of silently continuing from an arbitrary offset.
        A cursor is deliberately not bound to a database identity; verifying
        that the open store is the intended evidence store stays an operator
        responsibility (``SqliteDatabase.path`` exposes the resolved path).

        The same logical observation identity appearing more than once -- for
        example two stored rows whose persisted UUID renderings normalize to
        one identity, or one identity recorded under different timestamps --
        is ambiguous evidence and returns ``UNAVAILABLE``. Duplicates are
        detected on the logical identity alone; the timestamp remains part of
        the ordering and pagination key.
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
            logical_ids = [str(observation.observation_id) for observation in ordered]
            if len(set(logical_ids)) != len(logical_ids):
                # The ordering key includes the timestamp, so a repeated
                # logical identity under a different timestamp would otherwise
                # pass as two distinct observations. One logical observation
                # cannot be two pieces of evidence: present nothing rather
                # than a worklist that double-counts the same submission.
                return QuarantineWorklist(
                    status=QuarantineWorklistStatus.UNAVAILABLE,
                    error=_bounded_error(
                        "quarantine evidence contains duplicate logical observation identities"
                    ),
                )
            keys = [
                (observation.observed_at, logical_ids[index])
                for index, observation in enumerate(ordered)
            ]
            unique_keys = set(keys)
            if cursor_key is not None and cursor_key not in unique_keys:
                raise _CursorAttributionError(
                    "worklist cursor does not match the readable evidence in this store; "
                    "restart the inspection pass from the initial cursor"
                )
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
        except _CursorAttributionError:
            raise
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
        except QuarantineEvidenceUnavailable as exc:
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
