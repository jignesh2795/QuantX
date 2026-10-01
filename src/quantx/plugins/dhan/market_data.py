"""Dhan market-data adapter implementing the canonical MarketDataPort.

Only snapshot reads are supported. Dhan streaming market feed would require
async workers, so ``subscribe``/``unsubscribe`` fail closed instead of
pretending to stream. All translation stays inside the plugin boundary.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import Instrument
from quantx.domain.market_data import Candle, Quote
from quantx.domain.value_objects import InstrumentId

from .models import DhanInstrumentRef
from .transport import DhanTransport

_SUPPORTED_TIMEFRAMES = ("1m", "5m", "15m", "25m", "60m", "1d")


@dataclass(slots=True)
class DhanMarketDataAdapter:
    """Snapshot-only Dhan market-data adapter with explicit instrument mapping."""

    _instruments: dict[InstrumentId, tuple[Instrument, DhanInstrumentRef]]
    _transport: DhanTransport

    def quote(self, instrument: InstrumentId) -> Quote | None:
        """Return the latest broker quote snapshot, or None when unavailable."""
        reference = self._resolve(instrument)
        snapshot = self._transport.quote_snapshot(reference.security_id, reference.exchange_segment)
        if snapshot is None:
            return None
        return Quote(
            instrument=instrument,
            timestamp=snapshot.observed_at,
            bid=snapshot.bid_price,
            ask=snapshot.ask_price,
            last=snapshot.last_price,
            bid_size=snapshot.bid_size,
            ask_size=snapshot.ask_size,
        )

    def candles(
        self,
        instrument: InstrumentId,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> tuple[Candle, ...]:
        """Return deterministic historical candles within [start, end]."""
        _require_aware(start, "start")
        _require_aware(end, "end")
        if end < start:
            raise ValueError("candle end must not precede start")
        if timeframe not in _SUPPORTED_TIMEFRAMES:
            raise ValueError(f"unsupported Dhan market-data timeframe: {timeframe}")
        canonical, reference = self._resolve_with_instrument(instrument)
        snapshots = self._transport.candles(
            reference.security_id,
            reference.exchange_segment,
            timeframe=timeframe,
            start=start,
            end=end,
            instrument_type=_sdk_instrument_type(canonical),
        )
        candles = tuple(
            Candle(
                instrument=instrument,
                timeframe=timeframe,
                timestamp=snapshot.timestamp,
                open=snapshot.open,
                high=snapshot.high,
                low=snapshot.low,
                close=snapshot.close,
                volume=snapshot.volume,
            )
            for snapshot in snapshots
            if snapshot.timeframe == timeframe and start <= snapshot.timestamp <= end
        )
        return tuple(sorted(candles, key=lambda candle: candle.timestamp))

    def subscribe(self, instruments: Iterable[InstrumentId]) -> None:
        """Reject streaming explicitly; snapshot reads are the only supported path."""
        raise ValueError("Dhan market-data streaming is not supported; use quote/candles snapshots")

    def unsubscribe(self, instruments: Iterable[InstrumentId]) -> None:
        """Reject streaming explicitly; snapshot reads are the only supported path."""
        raise ValueError("Dhan market-data streaming is not supported; use quote/candles snapshots")

    def _resolve(self, instrument: InstrumentId) -> DhanInstrumentRef:
        try:
            _, reference = self._instruments[instrument]
        except KeyError as exc:
            raise ValueError(f"Dhan instrument mapping missing: {instrument}") from exc
        return reference

    def _resolve_with_instrument(
        self, instrument: InstrumentId
    ) -> tuple[Instrument, DhanInstrumentRef]:
        try:
            return self._instruments[instrument]
        except KeyError as exc:
            raise ValueError(f"Dhan instrument mapping missing: {instrument}") from exc


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"candle {name} must be timezone-aware")


def _sdk_instrument_type(instrument: Instrument) -> str:
    """Map the canonical asset class onto a Dhan historical-data instrument class."""
    if instrument.asset_class is AssetClass.EQUITY:
        return "EQUITY"
    raise ValueError(f"unsupported asset class for Dhan historical data: {instrument.asset_class}")
