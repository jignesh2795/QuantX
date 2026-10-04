"""Vendor-neutral broker-order lookup evidence.

A broker order lookup has three distinct outcomes that must never be
conflated:

FOUND:
    The broker returned an order observation that can be reconciled
    (including an UNKNOWN-status observation, which stays non-definitive
    downstream).

NOT_FOUND:
    The broker explicitly and authoritatively reports that the requested
    correlation/order does not exist.

UNKNOWN:
    Timeout, transport exception, unavailable endpoint, malformed or
    ambiguous response, or any case where the adapter cannot safely
    distinguish absence from temporary unavailability.

Generic lookup failure (``None``, exceptions, malformed data) MUST map to
UNKNOWN, never to NOT_FOUND. NOT_FOUND is evidence, not a resolution: a
separate conservative policy decides whether absence evidence is sufficient
for anything, and automated recovery never resolves from it alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .orders import OrderObservation


class BrokerOrderEvidenceStatus(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class BrokerOrderEvidence:
    """One authoritative broker-order lookup outcome."""

    status: BrokerOrderEvidenceStatus
    observation: OrderObservation | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        if self.status is BrokerOrderEvidenceStatus.FOUND and self.observation is None:
            raise ValueError("FOUND broker-order evidence requires an observation")
        if (
            self.status is not BrokerOrderEvidenceStatus.FOUND
            and self.observation is not None
        ):
            raise ValueError("non-FOUND broker-order evidence must not carry an observation")

    @classmethod
    def found(cls, observation: OrderObservation) -> BrokerOrderEvidence:
        return cls(status=BrokerOrderEvidenceStatus.FOUND, observation=observation)

    @classmethod
    def not_found(cls, reason: str) -> BrokerOrderEvidence:
        if not reason.strip():
            raise ValueError("NOT_FOUND broker-order evidence requires a reason")
        return cls(status=BrokerOrderEvidenceStatus.NOT_FOUND, reason=reason)

    @classmethod
    def unknown(cls, reason: str) -> BrokerOrderEvidence:
        if not reason.strip():
            raise ValueError("UNKNOWN broker-order evidence requires a reason")
        return cls(status=BrokerOrderEvidenceStatus.UNKNOWN, reason=reason)


__all__ = ["BrokerOrderEvidence", "BrokerOrderEvidenceStatus"]
