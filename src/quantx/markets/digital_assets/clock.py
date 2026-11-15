"""Continuous Digital Assets market clock and instrument trading status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from quantx.markets.common.calendar import MarketCalendar, SessionClassification, SessionStatus


class Continuous24x7Calendar(MarketCalendar):
    """Market calendar that is continuously open; it never uses equity sessions."""

    version: str = "digital-assets-continuous-24x7-v1"

    def classify(self, timestamp: datetime) -> SessionClassification:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return SessionClassification(
            timestamp=timestamp,
            status=SessionStatus.OPEN,
            timezone="UTC",
            calendar_version=self.version,
            reason="digital assets market is continuously open",
        )

    def historical_timestamp_expected(self, timestamp: datetime) -> bool | None:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return True


@dataclass(frozen=True, slots=True)
class DigitalAssetMarketStatus:
    """Separation of the continuous market clock from instrument trading status."""

    market_clock_open: bool
    instrument_trading_enabled: bool
    reason: str = ""

    @property
    def can_trade(self) -> bool:
        return self.market_clock_open and self.instrument_trading_enabled


def market_status_for_rule(rule_trading_status: str) -> DigitalAssetMarketStatus:
    normalized = rule_trading_status.strip().upper()
    enabled = normalized == "TRADING"
    reason = "" if enabled else f"instrument trading status is {normalized}"
    return DigitalAssetMarketStatus(
        market_clock_open=True,
        instrument_trading_enabled=enabled,
        reason=reason,
    )


__all__ = [
    "Continuous24x7Calendar",
    "DigitalAssetMarketStatus",
    "market_status_for_rule",
]
