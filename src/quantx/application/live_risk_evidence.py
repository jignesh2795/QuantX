"""Neutral LIVE risk-evidence contracts.

Every type here is a declaration, never an authorization. A source may
construct all of them, echo any identity value, and claim any supported field;
none of that is trust. Only the application-owned trust boundary in
:mod:`quantx.application.live_risk_sources` can bind a source to an exact
account, connection, broker client and transport, and only
:class:`quantx.application.live_risk.LiveRiskEvidenceAuthority` can turn that
binding into LIVE admission.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.risk import RiskContext, RiskLimits, RiskSnapshot


class LiveRiskEvidenceField(StrEnum):
    """One mandatory risk-evidence value a LIVE evaluation may consume."""

    CASH_BALANCE = "cash_balance"
    AVAILABLE_CASH = "available_cash"
    BLOCKED_CASH = "blocked_cash"
    MARGIN_USED = "margin_used"
    MARGIN_AVAILABLE = "margin_available"
    BUYING_POWER = "buying_power"
    CURRENT_POSITION_EXPOSURE = "current_position_exposure"
    CURRENT_INSTRUMENT_EXPOSURE = "current_instrument_exposure"
    CURRENT_PORTFOLIO_EXPOSURE = "current_portfolio_exposure"
    DAILY_PNL = "daily_pnl"
    EQUITY = "equity"
    HIGH_WATER_MARK = "high_water_mark"


_FINANCIAL_EVIDENCE_FIELDS: tuple[LiveRiskEvidenceField, ...] = (
    LiveRiskEvidenceField.CASH_BALANCE,
    LiveRiskEvidenceField.AVAILABLE_CASH,
    LiveRiskEvidenceField.BLOCKED_CASH,
    LiveRiskEvidenceField.MARGIN_USED,
    LiveRiskEvidenceField.MARGIN_AVAILABLE,
    LiveRiskEvidenceField.BUYING_POWER,
)


def required_live_risk_evidence_fields(limits: RiskLimits) -> frozenset[LiveRiskEvidenceField]:
    """Return the evidence fields the configured LIVE limits actually consume.

    The six account-financial values are always required because the existing
    ``RiskContext`` contract cannot be built without them. Every additional
    field is required only when its check is enabled; a disabled check never
    turns an unavailable value into a requirement.
    """
    required = set(_FINANCIAL_EVIDENCE_FIELDS)
    if limits.max_position_notional is not None:
        required.add(LiveRiskEvidenceField.CURRENT_POSITION_EXPOSURE)
    if limits.max_portfolio_exposure is not None:
        required.add(LiveRiskEvidenceField.CURRENT_PORTFOLIO_EXPOSURE)
    if limits.max_instrument_concentration is not None:
        required.add(LiveRiskEvidenceField.CURRENT_INSTRUMENT_EXPOSURE)
        required.add(LiveRiskEvidenceField.CURRENT_PORTFOLIO_EXPOSURE)
    if limits.max_daily_loss is not None:
        required.add(LiveRiskEvidenceField.DAILY_PNL)
    if limits.max_drawdown is not None:
        required.add(LiveRiskEvidenceField.EQUITY)
        required.add(LiveRiskEvidenceField.HIGH_WATER_MARK)
    return frozenset(required)


@dataclass(frozen=True, slots=True)
class LiveRiskEvidenceObservation:
    """One source observation with the instant the source captured it."""

    value: Decimal
    observed_at: datetime

    def __post_init__(self) -> None:
        if type(self.value) is not Decimal or not self.value.is_finite():
            raise ValueError("risk evidence observation value must be a finite Decimal")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("risk evidence observation instant must be timezone-aware")


@dataclass(frozen=True, slots=True)
class LiveRiskEvidence:
    """One source's evidence candidate before application-owned validation.

    This is deliberately a neutral record, not an authorization. A source may
    construct it, but only :class:`LiveRiskEvidenceAuthority` can bind it to
    the configured account/connection/client/transport and mint admission.
    """

    source_id: str
    broker_client_id: str | None
    account_id: AccountId | None
    broker_connection_id: BrokerConnectionId | None
    transport: object | None
    identity_observed_at: datetime | None
    context: RiskContext | None
    snapshot: RiskSnapshot | None
    observations: Mapping[LiveRiskEvidenceField, LiveRiskEvidenceObservation] = field(
        default_factory=dict
    )
    reference_price: Decimal | None = None
    unavailable_fields: tuple[LiveRiskEvidenceField, ...] = ()
    contradictions: tuple[str, ...] = ()
    message: str = ""


@runtime_checkable
class LiveRiskEvidenceSource(Protocol):
    """Application-wired source of broker-bound LIVE risk evidence.

    ``supported_fields`` declares what the source can ever provide; it is a
    capability declaration, not a trust claim. A source that cannot satisfy the
    configured limits never makes LIVE admission available, and a source that
    claims every field is still only considered when an application-registered
    construction path built it.
    """

    @property
    def source_id(self) -> str: ...

    @property
    def supported_fields(self) -> frozenset[LiveRiskEvidenceField]: ...

    def collect(self, request: ApprovedExecutionRequest) -> LiveRiskEvidence: ...
