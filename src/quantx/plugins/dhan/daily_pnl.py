"""Failure-closed Dhan realized daily P&L evidence (Slice C2a).

Dhan's verified v2 provider contracts do not establish a complete,
whole-account realized daily P&L authority. ``/positions`` is documented as the
open-position surface for the day (including F&O carry-forward), while
``/trades/{from}/{to}/{page}`` is paginated without a documented total, page
size, or end-of-data marker and carries no realized-P&L or opening-basis field.
Per-trade charge columns and the debit/credit ledger do not define a daily
charge authority. Summing whichever rows happen to be returned would therefore
manufacture a result the provider has not made authoritative.

This source consequently reports explicit ``UNAVAILABLE`` evidence with no
amount and no charges. It never claims ``COMPLETE`` and performs no broker I/O.
The exact provider-semantic reasoning is recorded in
``docs/architecture/58-dhan-realized-daily-pnl-c2a-blocker.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from quantx.domain.risk_evidence import (
    EvidenceStatus,
    RealizedDailyPnlEvidence,
    RealizedPnlSource,
)
from quantx.domain.value_objects import AccountId, BrokerConnectionId

_IST = ZoneInfo("Asia/Kolkata")
_COVERED_SURFACES = ("DHAN_PROVIDER_CONTRACT_AUDIT",)
_SOURCE_VERSION = "dhan-realized-daily-pnl-c2a-v1"
_SOURCE_PROVENANCE = "dhan-v2-portfolio-and-statements-contract-audit"


class DhanRealizedDailyPnlBlocker(StrEnum):
    """Exact reasons the Dhan provider cannot satisfy the C2a contract."""

    OPEN_POSITION_SCOPE = "DHAN_POSITIONS_OPEN_SCOPE_NOT_COMPLETE"
    CLOSED_ACTIVITY = "DHAN_CLOSED_ACTIVITY_NOT_PROVEN"
    TRADE_PAGINATION = "DHAN_TRADE_HISTORY_PAGINATION_UNVERIFIED"
    TRADE_REALIZED_PNL = "DHAN_TRADE_HISTORY_LACKS_REALIZED_PNL"
    CARRY_FORWARD_BASIS = "DHAN_CARRY_FORWARD_BASIS_UNAVAILABLE"
    DAILY_CHARGES = "DHAN_DAILY_CHARGES_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class DhanRealizedDailyPnlSource:
    """Dhan-scoped source that can never report an authoritative daily P&L.

    The source exists so callers receive typed, account-bound evidence instead
    of an absent value or a fabricated zero. ``source`` identifies the
    requested authority family; it does not claim that a broker report was
    obtained. The C1 risk-evidence builder rejects the resulting
    ``UNAVAILABLE`` status before any risk evaluation.
    """

    account_id: AccountId
    connection_id: BrokerConnectionId
    broker_id: str = "dhan"
    version: str = _SOURCE_VERSION
    provenance: str = _SOURCE_PROVENANCE

    def __post_init__(self) -> None:
        if type(self.account_id) is not AccountId:
            raise ValueError("Dhan P&L source account_id must be AccountId")
        if type(self.connection_id) is not BrokerConnectionId:
            raise ValueError("Dhan P&L source connection_id must be BrokerConnectionId")
        if type(self.broker_id) is not str or self.broker_id != "dhan":
            raise ValueError("Dhan P&L source broker_id must be 'dhan'")
        if type(self.version) is not str or not self.version.strip():
            raise ValueError("Dhan P&L source version is required")
        if type(self.provenance) is not str or not self.provenance.strip():
            raise ValueError("Dhan P&L source provenance is required")

    def observe_realized_daily_pnl(
        self,
        *,
        trading_day: date,
        day_start_at: datetime,
        as_of: datetime,
    ) -> RealizedDailyPnlEvidence:
        """Return explicit unavailable evidence bound to the requested session.

        ``as_of`` is the caller's observation instant; trusted-clock freshness
        remains the C1 builder's responsibility. The source only checks that
        the session boundary is coherent in the India exchange timezone.
        """

        if type(trading_day) is not date:
            raise ValueError("Dhan P&L trading_day must be a date")
        _require_aware(day_start_at, "Dhan P&L day_start_at")
        _require_aware(as_of, "Dhan P&L as_of")
        if as_of < day_start_at:
            raise ValueError("Dhan P&L as_of must not precede day_start_at")
        if day_start_at.astimezone(_IST).date() != trading_day:
            raise ValueError("Dhan P&L trading_day must match the IST session date")
        return RealizedDailyPnlEvidence(
            account_id=self.account_id,
            connection_id=self.connection_id,
            broker_id=self.broker_id,
            trading_day=trading_day,
            day_start_at=day_start_at,
            as_of=as_of,
            amount=None,
            charges_daily=None,
            source=RealizedPnlSource.BROKER_REPORTED,
            scope="WHOLE_ACCOUNT",
            completeness=EvidenceStatus.UNAVAILABLE,
            covered_surfaces=_COVERED_SURFACES,
            uncaptured_activity=tuple(blocker.value for blocker in DhanRealizedDailyPnlBlocker),
            version=self.version,
            provenance=self.provenance,
        )


def _require_aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


__all__ = ["DhanRealizedDailyPnlBlocker", "DhanRealizedDailyPnlSource"]
