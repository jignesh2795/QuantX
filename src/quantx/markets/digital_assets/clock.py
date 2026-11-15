"""Continuous Digital Assets market clock and instrument trading status."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from quantx.markets.common.calendar import MarketCalendar, SessionClassification, SessionStatus


class Continuous24x7Calendar(MarketCalendar):
    """Market calendar that is continuously open; it never uses equity sessions."""

    version: str = "digital-assets-continuous-24x7-v1"

    def classify(self, timestamp: datetime) -> SessionClassification:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        # Classification advertises UTC; normalize the carried instant too.
        instant = timestamp.astimezone(UTC)
        return SessionClassification(
            timestamp=instant,
            status=SessionStatus.OPEN,
            timezone="UTC",
            calendar_version=self.version,
            reason="digital assets market is continuously open",
        )

    def historical_timestamp_expected(self, timestamp: datetime) -> bool | None:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return True


class DigitalAssetTradingStatus(StrEnum):
    """Normalized trading states supported by the initial spot rule contract."""

    TRADING = "TRADING"
    HALTED = "HALTED"


@dataclass(frozen=True, slots=True)
class DigitalAssetMarketStatus:
    """Separation of the continuous market clock from instrument trading status."""

    market_clock_open: bool
    instrument_trading_enabled: bool
    reason: str = ""

    @property
    def can_trade(self) -> bool:
        return self.market_clock_open and self.instrument_trading_enabled


def market_status_for_rule(
    rule_trading_status: str | DigitalAssetTradingStatus,
) -> DigitalAssetMarketStatus:
    if not isinstance(rule_trading_status, str):
        raise TypeError("rule_trading_status must be a string or DigitalAssetTradingStatus")
    try:
        normalized = DigitalAssetTradingStatus(rule_trading_status.strip().upper())
    except ValueError as exc:
        raise ValueError(
            f"unsupported digital-asset trading status: {rule_trading_status!r}"
        ) from exc
    enabled = normalized is DigitalAssetTradingStatus.TRADING
    reason = "" if enabled else f"instrument trading status is {normalized.value}"
    return DigitalAssetMarketStatus(
        market_clock_open=True,
        instrument_trading_enabled=enabled,
        reason=reason,
    )


__all__ = [
    "Continuous24x7Calendar",
    "DigitalAssetTradingStatus",
    "DigitalAssetMarketStatus",
    "market_status_for_rule",
]
