"""Conservative policy for broker NOT_FOUND evidence on pending reservations.

NOT_FOUND is evidence, not a resolution. This module decides whether absence
evidence is even *eligible* for operator attention; it never resolves a
reservation by itself and automated recovery never calls it to complete
anything.

Eligibility requires ALL of:

A. an authoritative NOT_FOUND broker lookup result;
B. a configured minimum pending age (observation/wait condition) elapsed;
C. a secondary absence confirmation, when the adapter exposes such a check.

If the secondary check is unavailable (``None``) while required, or the
pending age is below the minimum, the result is explicitly non-definitive:
the reservation remains PENDING. In particular, a single immediate NOT_FOUND
never establishes definitive non-receipt, because absence observations
cannot prove a network order was never received.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from quantx.integrations.reconciliation.broker_evidence import (
    BrokerOrderEvidenceStatus,
)


@dataclass(frozen=True, slots=True)
class NotFoundResolutionPolicy:
    """Bounded, deterministic eligibility for NOT_FOUND absence evidence."""

    min_pending_age: timedelta = timedelta(hours=1)
    require_secondary_absence: bool = True

    def __post_init__(self) -> None:
        if self.min_pending_age < timedelta(0):
            raise ValueError("min_pending_age must not be negative")


@dataclass(frozen=True, slots=True)
class NotFoundResolution:
    """Eligibility verdict for absence evidence; never a state transition."""

    eligible: bool
    reason: str


def evaluate_not_found_resolution(
    *,
    evidence_status: BrokerOrderEvidenceStatus,
    pending_age: timedelta,
    secondary_absence_confirmed: bool | None,
    policy: NotFoundResolutionPolicy | None = None,
) -> NotFoundResolution:
    """Judge whether NOT_FOUND evidence meets the conservative bar.

    ``secondary_absence_confirmed`` is ``True``/``False`` when the adapter
    exposes a secondary absence check, or ``None`` when it does not. Any
    non-NOT_FOUND evidence, insufficient age, missing required secondary
    confirmation, or negative secondary result stays non-eligible.
    """
    active = policy or NotFoundResolutionPolicy()
    if evidence_status is not BrokerOrderEvidenceStatus.NOT_FOUND:
        return NotFoundResolution(
            eligible=False,
            reason="no authoritative NOT_FOUND evidence; absence is not established",
        )
    if pending_age < active.min_pending_age:
        return NotFoundResolution(
            eligible=False,
            reason="NOT_FOUND observed but minimum pending age has not elapsed",
        )
    if active.require_secondary_absence:
        if secondary_absence_confirmed is None:
            return NotFoundResolution(
                eligible=False,
                reason="secondary absence check unavailable; absence stays non-definitive",
            )
        if not secondary_absence_confirmed:
            return NotFoundResolution(
                eligible=False,
                reason="secondary absence check did not confirm absence",
            )
    return NotFoundResolution(
        eligible=True,
        reason="authoritative NOT_FOUND with elapsed wait and confirmed absence",
    )


__all__ = [
    "NotFoundResolution",
    "NotFoundResolutionPolicy",
    "evaluate_not_found_resolution",
]
