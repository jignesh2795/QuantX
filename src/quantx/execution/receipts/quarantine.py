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


class QuarantineObservationKind(StrEnum):
    """Typed category describing why a submission observation was quarantined."""

    TRANSPORT_UNCERTAIN = "TRANSPORT_UNCERTAIN"
    BROKER_UNKNOWN = "BROKER_UNKNOWN"
    IDENTITY_REJECTED = "IDENTITY_REJECTED"
    MALFORMED_RECEIPT = "MALFORMED_RECEIPT"
    RECEIPT_PERSISTENCE_UNCERTAIN = "RECEIPT_PERSISTENCE_UNCERTAIN"


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
        for field_name in (
            "request_correlation_id",
            "source",
            "broker_order_id",
            "outcome",
            "order_status",
        ):
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

        Only exactly-typed, bounded values survive; any malformed
        broker-supplied field is dropped (kept ``None``) so a hostile
        receipt can never corrupt the durable evidence record. The
        receipt itself is never stored and never becomes authoritative.
        """
        source = getattr(receipt, "source", None)
        broker_order_id = getattr(receipt, "broker_order_id", None)
        outcome = getattr(receipt, "outcome", None)
        order_status = getattr(receipt, "order_status", None)
        outcome_value = outcome.value if isinstance(outcome, StrEnum) else None
        status_value = order_status.value if isinstance(order_status, StrEnum) else None
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
        data = json.loads(payload)
        raw_client_order_id = data["client_order_id"]
        try:
            client_order_id: UUID | str = UUID(raw_client_order_id)
        except ValueError:
            client_order_id = raw_client_order_id
        return cls(
            observation_id=UUID(data["observation_id"]),
            kind=QuarantineObservationKind(data["kind"]),
            client_order_id=client_order_id,
            observed_at=datetime.fromisoformat(data["observed_at"]),
            reason=data["reason"],
            request_correlation_id=data["request_correlation_id"],
            source=data["source"],
            broker_order_id=data["broker_order_id"],
            outcome=data["outcome"],
            order_status=data["order_status"],
        )


__all__ = [
    "QuarantineObservationKind",
    "QuarantinedSubmissionObservation",
]
