"""Fail-closed Dhan whole-account position-evidence capability assessment.

Dhan exposes separate open-position and demat-holdings surfaces, but its
published contracts do not define a cross-surface merge policy or give the
holdings rows a canonical product identity. Mark data also depends on the
separately subscribed Data APIs. Until these gaps are resolved, this module
reports capability unavailability; it never fabricates a portfolio snapshot.

The detailed provider-contract decision is recorded in
docs/architecture/59-dhan-whole-account-position-evidence-c2b-blocker.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from quantx.domain.risk_evidence import EvidenceStatus
from quantx.domain.value_objects import AccountId, BrokerConnectionId


class DhanWholeAccountPositionEvidenceBlocker(StrEnum):
    """Verified provider-contract gaps preventing a complete canonical book."""

    POSITION_HOLDINGS_OVERLAP_UNDEFINED = "DHAN_POSITION_HOLDINGS_OVERLAP_UNDEFINED"
    HOLDINGS_PRODUCT_IDENTITY_UNAVAILABLE = "DHAN_HOLDINGS_PRODUCT_IDENTITY_UNAVAILABLE"
    CANONICAL_MAPPING_COVERAGE_UNPROVEN = "DHAN_CANONICAL_MAPPING_COVERAGE_UNPROVEN"
    DATA_API_MARK_ENTITLEMENT_REQUIRED = "DHAN_DATA_API_MARK_ENTITLEMENT_REQUIRED"
    MARK_TIMESTAMP_COVERAGE_UNPROVEN = "DHAN_MARK_TIMESTAMP_COVERAGE_UNPROVEN"
    WHOLE_BOOK_COMPLETENESS_UNPROVEN = "DHAN_WHOLE_BOOK_COMPLETENESS_UNPROVEN"


@dataclass(frozen=True, slots=True)
class DhanWholeAccountPositionEvidenceAssessment:
    """Capability assessment, deliberately distinct from a position snapshot.

    assessed_at is the local contract-assessment instant, not a provider
    observation timestamp. This value can never represent a complete book:
    the evidence source has not queried the provider or reconciled any rows.
    """

    account_id: AccountId
    connection_id: BrokerConnectionId
    broker_id: str
    assessed_at: datetime
    status: EvidenceStatus
    blockers: tuple[DhanWholeAccountPositionEvidenceBlocker, ...]
    version: str
    provenance: str

    def __post_init__(self) -> None:
        if type(self.account_id) is not AccountId:
            raise ValueError("position evidence assessment account_id must be AccountId")
        if type(self.connection_id) is not BrokerConnectionId:
            raise ValueError(
                "position evidence assessment connection_id must be BrokerConnectionId"
            )
        if type(self.broker_id) is not str or self.broker_id != "dhan":
            raise ValueError("position evidence assessment broker_id must be 'dhan'")
        _require_aware(self.assessed_at, "position evidence assessed_at")
        if type(self.status) is not EvidenceStatus or self.status is not EvidenceStatus.UNAVAILABLE:
            raise ValueError("Dhan position evidence assessment must remain UNAVAILABLE")
        if type(self.blockers) is not tuple or not self.blockers:
            raise ValueError("position evidence assessment requires explicit blockers")
        if any(
            type(item) is not DhanWholeAccountPositionEvidenceBlocker for item in self.blockers
        ):
            raise ValueError("position evidence assessment blockers must use the canonical enum")
        if type(self.version) is not str or not self.version.strip():
            raise ValueError("position evidence assessment version is required")
        if type(self.provenance) is not str or not self.provenance.strip():
            raise ValueError("position evidence assessment provenance is required")


@dataclass(frozen=True, slots=True)
class DhanWholeAccountPositionEvidenceSource:
    """Dhan-scoped capability audit that does not claim to fetch a position book."""

    account_id: AccountId
    connection_id: BrokerConnectionId
    broker_id: str = "dhan"
    version: str = "dhan-whole-account-position-c2b-v1"
    provenance: str = "dhan-v2-portfolio-and-market-data-contract-audit"

    def __post_init__(self) -> None:
        if type(self.account_id) is not AccountId:
            raise ValueError("Dhan position evidence source account_id must be AccountId")
        if type(self.connection_id) is not BrokerConnectionId:
            raise ValueError(
                "Dhan position evidence source connection_id must be BrokerConnectionId"
            )
        if type(self.broker_id) is not str or self.broker_id != "dhan":
            raise ValueError("Dhan position evidence source broker_id must be 'dhan'")
        if type(self.version) is not str or not self.version.strip():
            raise ValueError("Dhan position evidence source version is required")
        if type(self.provenance) is not str or not self.provenance.strip():
            raise ValueError("Dhan position evidence source provenance is required")

    def assess(self, *, assessed_at: datetime) -> DhanWholeAccountPositionEvidenceAssessment:
        """Return explicit capability blockers without performing broker I/O."""

        _require_aware(assessed_at, "position evidence assessed_at")
        return DhanWholeAccountPositionEvidenceAssessment(
            account_id=self.account_id,
            connection_id=self.connection_id,
            broker_id=self.broker_id,
            assessed_at=assessed_at,
            status=EvidenceStatus.UNAVAILABLE,
            blockers=tuple(DhanWholeAccountPositionEvidenceBlocker),
            version=self.version,
            provenance=self.provenance,
        )


def _require_aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


__all__ = [
    "DhanWholeAccountPositionEvidenceAssessment",
    "DhanWholeAccountPositionEvidenceBlocker",
    "DhanWholeAccountPositionEvidenceSource",
]
