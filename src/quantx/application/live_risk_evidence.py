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
from quantx.domain.value_objects import InstrumentId, Money


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


class LiveRiskPositionPnlProvenance(StrEnum):
    """Origin of a row-level position P&L value."""

    BROKER_REPORTED = "broker_reported"


class LiveRiskPositionPnlUnavailableReason(StrEnum):
    """Why a position P&L collection cannot be treated as complete."""

    NOT_COLLECTED = "not_collected"
    POSITION_BOOK_UNAVAILABLE = "position_book_unavailable"
    POSITION_INSTRUMENT_UNMAPPED = "position_instrument_unmapped"
    POSITION_QUANTITY_UNAVAILABLE = "position_quantity_unavailable"
    POSITION_REALIZED_PNL_UNAVAILABLE = "position_realized_pnl_unavailable"
    POSITION_UNREALIZED_PNL_UNAVAILABLE = "position_unrealized_pnl_unavailable"
    POSITION_CLIENT_ID_MISMATCH = "position_client_id_mismatch"


@dataclass(frozen=True, slots=True)
class LiveRiskPositionPnlObservation:
    """One broker-reported position row, not an account-level P&L value.

    source_position_key is unique only within the collected batch. It is an
    opaque row reference, not a durable position identity. An unmapped row is
    retained with instrument_id=None so a later consumer cannot mistake a
    partial mapped set for the complete position book.
    """

    source_position_key: str
    broker_client_id: str | None
    instrument_id: InstrumentId | None
    net_quantity: Decimal | None
    product_type: str | None
    position_type: str | None
    realized_pnl: Money | None
    unrealized_pnl: Money | None
    observed_at: datetime
    provenance: LiveRiskPositionPnlProvenance = LiveRiskPositionPnlProvenance.BROKER_REPORTED

    def __post_init__(self) -> None:
        if type(self.source_position_key) is not str or not self.source_position_key.strip():
            raise ValueError("position P&L source key must not be empty")
        if self.broker_client_id is not None and (
            type(self.broker_client_id) is not str or not self.broker_client_id.strip()
        ):
            raise ValueError("position P&L broker client id must be non-empty when present")
        if self.instrument_id is not None and type(self.instrument_id) is not InstrumentId:
            raise ValueError("position P&L instrument id must be canonical")
        if self.net_quantity is not None and (
            type(self.net_quantity) is not Decimal or not self.net_quantity.is_finite()
        ):
            raise ValueError("position P&L net quantity must be a finite Decimal")
        for name in ("product_type", "position_type"):
            value = getattr(self, name)
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError(f"position P&L {name} must be non-empty when present")
        for name in ("realized_pnl", "unrealized_pnl"):
            value = getattr(self, name)
            if value is not None and (
                type(value) is not Money
                or type(value.amount) is not Decimal
                or not value.amount.is_finite()
                or type(value.currency) is not str
                or not value.currency.strip()
            ):
                raise ValueError(f"position P&L {name} must be finite Money")
        if type(self.observed_at) is not datetime:
            raise ValueError("position P&L observation instant must be a datetime")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("position P&L observation instant must be timezone-aware")
        if type(self.provenance) is not LiveRiskPositionPnlProvenance:
            raise ValueError("position P&L provenance must be explicit")


@dataclass(frozen=True, slots=True)
class LiveRiskPositionPnlCollection:
    """Captured rows from one positions endpoint response.

    complete means every row returned by that positions response was retained,
    canonically mapped, and supplied finite quantity, realized P&L, and
    unrealized P&L values. It does not mean account/day P&L completeness: the
    endpoint may not include closed trades, holdings, or a session baseline.
    An available empty response is a complete collection of zero rows, not a
    statement that account P&L is zero.
    """

    observed_at: datetime | None
    observations: tuple[LiveRiskPositionPnlObservation, ...] = ()
    unavailable_reasons: tuple[LiveRiskPositionPnlUnavailableReason, ...] = (
        LiveRiskPositionPnlUnavailableReason.NOT_COLLECTED,
    )

    def __post_init__(self) -> None:
        if self.observed_at is not None:
            if type(self.observed_at) is not datetime:
                raise ValueError("position P&L collection instant must be a datetime")
            if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
                raise ValueError("position P&L collection instant must be timezone-aware")
        if type(self.observations) is not tuple or any(
            type(value) is not LiveRiskPositionPnlObservation for value in self.observations
        ):
            raise ValueError("position P&L observations must be an immutable typed tuple")
        if type(self.unavailable_reasons) is not tuple or any(
            type(value) is not LiveRiskPositionPnlUnavailableReason
            for value in self.unavailable_reasons
        ):
            raise ValueError("position P&L unavailable reasons must be typed")
        if len(set(self.unavailable_reasons)) != len(self.unavailable_reasons):
            raise ValueError("position P&L unavailable reasons must be unique")
        source_keys = tuple(value.source_position_key for value in self.observations)
        if len(set(source_keys)) != len(source_keys):
            raise ValueError("position P&L source keys must be unique within a batch")
        if self.observed_at is None and self.observations:
            raise ValueError("position P&L rows require a collection instant")
        if self.observed_at is None and not self.unavailable_reasons:
            raise ValueError("an unavailable position P&L collection requires a reason")
        if any(value.observed_at != self.observed_at for value in self.observations):
            raise ValueError("position P&L rows must share the collection instant")
        if not self.unavailable_reasons and any(
            value.instrument_id is None
            or value.net_quantity is None
            or value.realized_pnl is None
            or value.unrealized_pnl is None
            for value in self.observations
        ):
            raise ValueError("a complete position P&L collection requires every row field")

    @property
    def complete(self) -> bool:
        """Whether this batch is complete for its returned rows only."""
        return self.observed_at is not None and not self.unavailable_reasons

    @classmethod
    def not_collected(cls) -> LiveRiskPositionPnlCollection:
        """Create the explicit default for evidence sources with no P&L batch."""
        return cls(
            observed_at=None,
            observations=(),
            unavailable_reasons=(LiveRiskPositionPnlUnavailableReason.NOT_COLLECTED,),
        )


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
    position_pnl_collection: LiveRiskPositionPnlCollection = field(
        default_factory=LiveRiskPositionPnlCollection.not_collected
    )

    def __post_init__(self) -> None:
        if type(self.position_pnl_collection) is not LiveRiskPositionPnlCollection:
            raise ValueError("position P&L collection must use the neutral evidence contract")


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
