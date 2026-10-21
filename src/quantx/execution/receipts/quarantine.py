"""Non-authoritative quarantined submission evidence.

A submission whose outcome is uncertain, or whose broker receipt is not
bound to the approved request, must not enter the canonical receipt store,
complete idempotency, or affect accounting or lifecycle facts. The evidence
must also not silently disappear: reconciliation needs enough sanitized,
typed identity to resolve the outcome later. This module defines that
durable, strictly non-authoritative observation record.

Records here are deliberately minimal: request correlation, source/adapter
identity, observed broker order id, observed outcome/status vocabulary
values, an observation timestamp, a typed reason category, and a stable
observation identity supporting idempotent writes. Secrets, access tokens,
raw transport payloads, and unsanitized exception messages must never be
stored: callers pass static sanitized reasons, and every untrusted
broker-supplied field is validated for exact runtime type and bounded
length before serialization.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

_MAX_TEXT_LENGTH = 256
_MAX_REASON_LENGTH = 512
_MAX_OBSERVATION_ID_DISPLAY = 128
_MAX_DETAIL_LENGTH = 512

# Unicode bidirectional formatting/isolate controls. They are invisible in a
# terminal but can reorder the surrounding text, so an untrusted observation
# field carrying one can spoof a worklist entry. They are always rendered as
# escapes, never as active formatting.
_BIDI_CONTROL_CODEPOINTS = frozenset(
    {
        0x061C,  # ARABIC LETTER MARK
        0x200E,  # LEFT-TO-RIGHT MARK
        0x200F,  # RIGHT-TO-LEFT MARK
        0x202A,  # LEFT-TO-RIGHT EMBEDDING
        0x202B,  # RIGHT-TO-LEFT EMBEDDING
        0x202C,  # POP DIRECTIONAL FORMATTING
        0x202D,  # LEFT-TO-RIGHT OVERRIDE
        0x202E,  # RIGHT-TO-LEFT OVERRIDE
        0x2066,  # LEFT-TO-RIGHT ISOLATE
        0x2067,  # RIGHT-TO-LEFT ISOLATE
        0x2068,  # FIRST STRONG ISOLATE
        0x2069,  # POP DIRECTIONAL ISOLATE
    }
)


def _is_displayable(character: str) -> bool:
    codepoint = ord(character)
    if 0xD800 <= codepoint <= 0xDFFF:  # lone surrogate: not terminal-encodable
        return False
    if codepoint in _BIDI_CONTROL_CODEPOINTS:
        return False
    return 0x20 <= codepoint <= 0x7E or 0xA0 <= codepoint <= 0x2027 or codepoint >= 0x202A


def neutralize_display_text(value: object, *, max_length: int) -> str:
    """Render untrusted text for a terminal, bounded to ``max_length`` characters.

    Newlines, carriage returns, tabs, C0/C1 controls, Unicode line/paragraph
    separators, bidirectional formatting/isolate controls, and lone surrogates
    are shown as printable escapes, so persisted or broker-derived text cannot
    inject terminal commands, reorder surrounding text, forge worklist entries,
    or make a terminal encoder fail. The persisted value is never modified; only
    this rendered copy is neutralized.
    """
    if isinstance(max_length, bool) or not isinstance(max_length, int) or max_length < 1:
        raise ValueError("max_length must be a positive integer")
    try:
        text = str(value)
    except Exception:
        text = f"<{type(value).__name__}>"
    escaped = "".join(
        {
            "\n": "\\n",
            "\r": "\\r",
            "\t": "\\t",
        }.get(
            character,
            (
                character
                if _is_displayable(character)
                else (
                    f"\\x{ord(character):02x}"
                    if ord(character) <= 0xFF
                    else f"\\u{ord(character):04x}"
                )
            ),
        )
        for character in text[:max_length]
    )
    if len(escaped) > max_length:
        return f"{escaped[: max_length - 3]}..."
    return escaped


def _bounded_identity(value: object) -> str:
    """Render an untrusted row identity safely and boundedly."""
    return neutralize_display_text(value, max_length=_MAX_OBSERVATION_ID_DISPLAY)


def _bounded_detail(detail: str) -> str:
    return " ".join(detail[:_MAX_DETAIL_LENGTH].split())


class QuarantineEvidenceDecodeError(ValueError):
    """A durable quarantined-evidence row could not be decoded.

    Raised by storage adapters listing durable evidence when a stored payload
    is unreadable or violates the record contract. Readers must surface this
    as an explicit unavailable result: a corrupt evidence row is not an empty
    worklist, and it must never be silently skipped. The row identity is
    rendered safely and boundedly so a hostile row key cannot make the
    failure report unbounded or terminal-unsafe.
    """

    def __init__(self, observation_id: object, *, detail: str | None = None) -> None:
        self.observation_id = _bounded_identity(observation_id)
        message = f"quarantined observation {self.observation_id} could not be decoded"
        if detail:
            message = f"{message}: {_bounded_detail(detail)}"
        super().__init__(message)


class QuarantineEvidenceTooLarge(RuntimeError):
    """The durable evidence exceeds the adapter's bounded read contract.

    A reader must surface this as explicitly unavailable. It is never an empty
    worklist and never a silently truncated page: evidence beyond the bounded
    snapshot is not presented as if it did not exist.
    """

    def __init__(self, detail: str, *, observation_id: object | None = None) -> None:
        message = "quarantine evidence exceeds read bounds"
        if observation_id is not None:
            message = f"{message} for observation {_bounded_identity(observation_id)}"
        self.detail = _bounded_detail(detail)
        super().__init__(f"{message}: {self.detail}")


class QuarantineEvidenceUnavailable(RuntimeError):
    """The durable evidence store could not be read at all.

    Storage adapters raise this at the port boundary instead of leaking a
    driver exception. ``detail`` is always a static, bounded description: a
    raw SQLite error can carry file paths or untrusted text and must never be
    reproduced for an operator.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(f"quarantine evidence store could not be read: {_bounded_detail(detail)}")


class QuarantineObservationKind(StrEnum):
    """Typed category describing why a submission observation was quarantined."""

    TRANSPORT_UNCERTAIN = "TRANSPORT_UNCERTAIN"
    BROKER_UNKNOWN = "BROKER_UNKNOWN"
    IDENTITY_REJECTED = "IDENTITY_REJECTED"
    MALFORMED_RECEIPT = "MALFORMED_RECEIPT"
    RECEIPT_PERSISTENCE_UNCERTAIN = "RECEIPT_PERSISTENCE_UNCERTAIN"


#: Optional text fields, each of which ``__post_init__`` bounds to
#: ``_MAX_TEXT_LENGTH`` code points (or normalizes to ``None``).
_OPTIONAL_TEXT_FIELDS = (
    "request_correlation_id",
    "source",
    "broker_order_id",
    "outcome",
    "order_status",
)

#: Every key ``to_payload`` serializes. ``client_order_id`` is the sixth
#: bounded text value; ``kind``/``observation_id``/``observed_at``/``reason``
#: have their own bounds.
_PAYLOAD_FIELDS = tuple(
    sorted(
        (
            *_OPTIONAL_TEXT_FIELDS,
            "client_order_id",
            "kind",
            "observation_id",
            "observed_at",
            "reason",
        )
    )
)
_TEXT_PAYLOAD_FIELDS = (*_OPTIONAL_TEXT_FIELDS, "client_order_id")

# ``to_payload`` uses ``json.dumps`` with the stdlib ``ensure_ascii=True``
# default. Every non-ASCII code point is therefore escaped: a BMP code point
# costs six characters (``\uXXXX``) and an astral code point becomes a
# surrogate pair costing twelve. C0 controls, quotes, and backslashes expand
# too, but never beyond that factor.
_JSON_ESCAPE_FACTOR = 12
_MAX_UUID_CHARS = 36
# Widest legal ``datetime.isoformat`` result: a 26-character date-time plus a
# 16-character UTC offset (``9999-12-31T23:59:59.999999+23:59:59.999999``).
_MAX_OBSERVED_AT_CHARS = 42
_MAX_KIND_CHARS = max(
    len(json.dumps(kind.value)) - 2 for kind in QuarantineObservationKind
)  # longest serialized enum value, escapes included
# Braces, the ``"key":`` prefix of every sorted key, and the separating commas.
_JSON_ENVELOPE_CHARS = (
    2 + sum(len(field) + 3 for field in _PAYLOAD_FIELDS) + (len(_PAYLOAD_FIELDS) - 1)
)

#: One canonical serialized-size contract shared by the writer and the reader.
#:
#: A valid ``QuarantinedSubmissionObservation`` serializes to at most this many
#: characters; the derivation above covers every validated field, JSON
#: structure, UUID text, Unicode escaping, and control-character escaping used
#: by ``to_payload``. The SQLite write boundary rejects a larger serialized
#: payload before it is stored, and the reader's default per-row bound is this
#: same value, so every record the writer accepts is subsequently readable.
MAX_SERIALIZED_PAYLOAD_CHARS = (
    len(_TEXT_PAYLOAD_FIELDS) * (_MAX_TEXT_LENGTH * _JSON_ESCAPE_FACTOR + 2)
    + (_MAX_REASON_LENGTH * _JSON_ESCAPE_FACTOR + 2)
    + (_MAX_KIND_CHARS + 2)
    + (_MAX_UUID_CHARS + 2)
    + (_MAX_OBSERVED_AT_CHARS + 2)
    + _JSON_ENVELOPE_CHARS
)


def _validated_optional_text(value: object) -> str | None:
    """Accept only bounded non-empty plain strings; everything else is None.

    Values in these fields originate from broker responses and must be
    validated before serialization instead of trusted. A wrong runtime
    type (including subclasses and non-string objects) is sanitized to
    ``None`` rather than raising: an observation must stay recordable.
    """
    if value is None:
        return None
    if type(value) is not str:
        return None
    text = value.strip()
    if not text or len(text) > _MAX_TEXT_LENGTH:
        return None
    return text


def _stored_optional_text(data: dict[str, object], field_name: str) -> str | None:
    """Validate one persisted optional field; any deviation is corruption.

    The writer stores only ``None`` or a stripped, non-empty string of at most
    ``_MAX_TEXT_LENGTH`` code points. A persisted payload with any other value
    was not produced by this contract, so the row is reported as undecodable
    instead of being silently normalized into apparently valid evidence.
    """
    value = data[field_name]
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError(f"stored optional field {field_name} must be a string or null")
    if not value or len(value) > _MAX_TEXT_LENGTH or value.strip() != value:
        raise ValueError(f"stored optional field {field_name} is not a bounded canonical string")
    return value


def _safe_getattr(obj: object, name: str) -> object | None:
    """Read an attribute of untrusted broker data without letting it raise.

    Attribute access on a hostile response object can raise (a property or
    descriptor that fails instead of returning a value). Such a field is
    dropped — ``None`` — so the malformed response is still recorded as
    sanitized, non-authoritative evidence instead of failing the
    observation write and forcing the admission safety fault.
    """
    try:
        return getattr(obj, name, None)
    except Exception:
        return None


def _enum_value(value: object) -> str | None:
    """Read a StrEnum member's value without trusting member state.

    A hostile response can carry an uninitialized or value-shadowing
    StrEnum instance whose ``value`` lookup raises. Such a field is
    dropped like any other malformed field instead of failing the
    observation write.
    """
    if not isinstance(value, StrEnum):
        return None
    raw = _safe_getattr(value, "value")
    return raw if isinstance(raw, str) else None


@dataclass(frozen=True, slots=True)
class QuarantinedSubmissionObservation:
    """One sanitized, non-authoritative submission observation.

    ``observation_id`` is the idempotent-write identity. The same logical
    observation re-recorded with an identical payload is a no-op; a
    conflicting payload for the same identity fails closed in the
    repository. This record never satisfies idempotency completion and is
    never returned as a canonical receipt.
    """

    observation_id: UUID
    kind: QuarantineObservationKind
    client_order_id: UUID | str
    observed_at: datetime
    reason: str
    request_correlation_id: str | None = None
    source: str | None = None
    broker_order_id: str | None = None
    outcome: str | None = None
    order_status: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.observation_id, UUID):
            raise ValueError("observation id must be a UUID")
        if not isinstance(self.kind, QuarantineObservationKind):
            raise ValueError("observation kind must be a QuarantineObservationKind")
        if isinstance(self.client_order_id, bool) or not isinstance(
            self.client_order_id, (UUID, str)
        ):
            raise ValueError("client order id must be a UUID or a string")
        if isinstance(self.client_order_id, str):
            if not self.client_order_id.strip() or len(self.client_order_id) > _MAX_TEXT_LENGTH:
                raise ValueError("client order id must be a non-empty bounded string")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if type(self.reason) is not str:
            raise ValueError("reason must be a string")
        if not self.reason.strip() or len(self.reason) > _MAX_REASON_LENGTH:
            raise ValueError("reason must be a non-empty bounded string")
        for field_name in _OPTIONAL_TEXT_FIELDS:
            value = getattr(self, field_name)
            validated = _validated_optional_text(value)
            if validated != value:
                object.__setattr__(self, field_name, validated)

    @classmethod
    def from_receipt(
        cls,
        *,
        observation_id: UUID,
        kind: QuarantineObservationKind,
        client_order_id: UUID | str,
        request_correlation_id: str | None,
        receipt: object,
        reason: str,
        observed_at: datetime,
    ) -> QuarantinedSubmissionObservation:
        """Extract sanitized observation fields from an untrusted receipt.

        Only exactly-typed, bounded values survive; any malformed or
        raising broker-supplied field access is dropped (kept ``None``)
        so a hostile receipt can never corrupt — or fail — the durable
        evidence record. The receipt itself is never stored and never
        becomes authoritative.
        """
        source = _safe_getattr(receipt, "source")
        broker_order_id = _safe_getattr(receipt, "broker_order_id")
        outcome = _safe_getattr(receipt, "outcome")
        order_status = _safe_getattr(receipt, "order_status")
        outcome_value = _enum_value(outcome)
        status_value = _enum_value(order_status)
        return cls(
            observation_id=observation_id,
            kind=kind,
            client_order_id=client_order_id,
            observed_at=observed_at,
            reason=reason,
            request_correlation_id=_validated_optional_text(request_correlation_id),
            source=_validated_optional_text(source),
            broker_order_id=_validated_optional_text(broker_order_id),
            outcome=outcome_value,
            order_status=status_value,
        )

    def to_payload(self) -> str:
        """Serialize deterministically using only stdlib JSON."""
        payload = {
            "broker_order_id": self.broker_order_id,
            "client_order_id": str(self.client_order_id),
            "kind": self.kind.value,
            "observation_id": str(self.observation_id),
            "observed_at": self.observed_at.isoformat(),
            "order_status": self.order_status,
            "outcome": self.outcome,
            "reason": self.reason,
            "request_correlation_id": self.request_correlation_id,
            "source": self.source,
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_payload(cls, payload: str) -> QuarantinedSubmissionObservation:
        """Decode a payload this contract wrote; reject a malformed stored row.

        A persisted payload is produced only by :meth:`to_payload`, so the
        reader treats any deviation from the documented record shape as
        corruption rather than normalizing it: a wrong-typed, empty, overlong,
        or non-canonical optional value raises ``ValueError`` and the storage
        adapter reports the row as undecodable. Unknown keys are ignored (and
        never surfaced), so a hand-edited row cannot inject display text.

        The writer-side sanitizer (:meth:`from_receipt`) still normalizes
        malformed broker-supplied values to ``None``; that sanitization happens
        before persistence and is a different contract from reading durable
        evidence.
        """
        data = json.loads(payload)
        if type(data) is not dict:
            raise ValueError("stored quarantine payload must be a JSON object")
        raw_client_order_id = data["client_order_id"]
        if type(raw_client_order_id) is not str:
            raise ValueError("stored client order id must be a string")
        try:
            client_order_id: UUID | str = UUID(raw_client_order_id)
        except ValueError:
            client_order_id = raw_client_order_id
        reason = data["reason"]
        if type(reason) is not str:
            raise ValueError("stored reason must be a string")
        return cls(
            observation_id=UUID(data["observation_id"]),
            kind=QuarantineObservationKind(data["kind"]),
            client_order_id=client_order_id,
            observed_at=datetime.fromisoformat(data["observed_at"]),
            reason=reason,
            request_correlation_id=_stored_optional_text(data, "request_correlation_id"),
            source=_stored_optional_text(data, "source"),
            broker_order_id=_stored_optional_text(data, "broker_order_id"),
            outcome=_stored_optional_text(data, "outcome"),
            order_status=_stored_optional_text(data, "order_status"),
        )


__all__ = [
    "MAX_SERIALIZED_PAYLOAD_CHARS",
    "QuarantineEvidenceDecodeError",
    "QuarantineEvidenceTooLarge",
    "QuarantineEvidenceUnavailable",
    "QuarantineObservationKind",
    "QuarantinedSubmissionObservation",
    "neutralize_display_text",
]
