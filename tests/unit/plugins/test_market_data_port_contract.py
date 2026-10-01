"""Shared MarketDataPort contract coverage for the first production data adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.market_data import Candle, Quote
from quantx.plugins.dhan import (
    DhanInstrumentRef,
    DhanMarketDataAdapter,
    InMemoryDhanTransport,
)
from quantx.plugins.dhan.models import DhanCandleSnapshot, DhanQuoteSnapshot
from quantx.ports.market_data import MarketDataPort

T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
T1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
T2 = datetime(2026, 1, 1, 9, 17, tzinfo=UTC)

INSTRUMENT_ID = InstrumentId("NSE", "TCS")


def _instrument() -> Instrument:
    return Instrument(
        instrument_id=INSTRUMENT_ID,
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def _adapter(
    transport: InMemoryDhanTransport | None = None,
) -> DhanMarketDataAdapter:
    return DhanMarketDataAdapter(
        _instruments={
            INSTRUMENT_ID: (
                _instrument(),
                DhanInstrumentRef("1333", "NSE_EQ", "TCS", "CNC"),
            )
        },
        _transport=transport or InMemoryDhanTransport(),
    )


def _quote(timestamp: datetime = T0, **overrides) -> DhanQuoteSnapshot:
    values = {
        "security_id": "1333",
        "exchange_segment": "NSE_EQ",
        "observed_at": timestamp,
        "last_price": Decimal("100"),
        "bid_price": Decimal("99"),
        "ask_price": Decimal("100"),
        "bid_size": Decimal("10"),
        "ask_size": Decimal("12"),
    }
    values.update(overrides)
    return DhanQuoteSnapshot(**values)


def _candle(timestamp: datetime = T0, **overrides) -> DhanCandleSnapshot:
    values = {
        "timeframe": "1m",
        "timestamp": timestamp,
        "open": Decimal("99"),
        "high": Decimal("101"),
        "low": Decimal("98"),
        "close": Decimal("100"),
        "volume": Decimal("1000"),
    }
    values.update(overrides)
    return DhanCandleSnapshot(**values)


def test_adapter_satisfies_market_data_port_contract() -> None:
    adapter = _adapter()

    assert isinstance(adapter, MarketDataPort)


def test_quote_contract_preserves_canonical_instrument_and_timestamp() -> None:
    adapter = _adapter(
        InMemoryDhanTransport(
            quote_snapshots={("1333", "NSE_EQ"): _quote()},
        )
    )

    quote = adapter.quote(INSTRUMENT_ID)

    assert isinstance(quote, Quote)
    assert quote.instrument == INSTRUMENT_ID
    assert quote.timestamp == T0


def test_quote_missing_observation_is_explicit() -> None:
    assert _adapter().quote(INSTRUMENT_ID) is None


def test_candle_contract_preserves_identity_and_bounds() -> None:
    adapter = _adapter(
        InMemoryDhanTransport(
            candle_snapshots={
                ("1333", "NSE_EQ"): (
                    _candle(T0),
                    _candle(T1),
                    _candle(T2),
                )
            }
        )
    )

    candles = tuple(adapter.candles(INSTRUMENT_ID, timeframe="1m", start=T1, end=T2))

    assert all(isinstance(candle, Candle) for candle in candles)
    assert [candle.instrument for candle in candles] == [INSTRUMENT_ID, INSTRUMENT_ID]
    assert [candle.timestamp for candle in candles] == [T1, T2]


def test_candles_are_chronological() -> None:
    adapter = _adapter(
        InMemoryDhanTransport(
            candle_snapshots={
                ("1333", "NSE_EQ"): (
                    _candle(T2),
                    _candle(T0),
                    _candle(T1),
                )
            }
        )
    )

    candles = tuple(adapter.candles(INSTRUMENT_ID, timeframe="1m", start=T0, end=T2))

    assert [candle.timestamp for candle in candles] == [T0, T1, T2]


@pytest.mark.parametrize(
    ("start", "end"),
    (
        (datetime(2026, 1, 1, 9, 15), T1),
        (T0, datetime(2026, 1, 1, 9, 16)),
    ),
)
def test_candle_contract_rejects_naive_time_bounds(start: datetime, end: datetime) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _adapter().candles(INSTRUMENT_ID, timeframe="1m", start=start, end=end)


def test_candle_contract_rejects_backwards_range() -> None:
    with pytest.raises(ValueError, match="must not precede"):
        _adapter().candles(INSTRUMENT_ID, timeframe="1m", start=T2, end=T0)


def test_streaming_capability_is_explicitly_rejected() -> None:
    adapter = _adapter()

    with pytest.raises(ValueError, match="streaming is not supported"):
        adapter.subscribe((INSTRUMENT_ID,))

    with pytest.raises(ValueError, match="streaming is not supported"):
        adapter.unsubscribe((INSTRUMENT_ID,))


def test_vendor_sdk_import_isolated_from_market_data_port_and_adapter() -> None:
    import quantx.plugins.dhan.market_data as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "dhanhq" not in source
