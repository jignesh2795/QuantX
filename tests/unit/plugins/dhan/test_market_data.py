"""Tests for the Dhan snapshot market-data adapter."""

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
from quantx.plugins.dhan.market_data import DhanMarketDataAdapter
from quantx.plugins.dhan.models import (
    DhanCandleSnapshot,
    DhanInstrumentRef,
    DhanQuoteSnapshot,
)
from quantx.plugins.dhan.transport import InMemoryDhanTransport
from quantx.ports.market_data import MarketDataPort

T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
T1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
T2 = datetime(2026, 1, 1, 9, 17, tzinfo=UTC)


def _instrument() -> Instrument:
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _ref() -> DhanInstrumentRef:
    return DhanInstrumentRef(
        security_id="1333",
        exchange_segment="NSE_EQ",
        trading_symbol="TCS",
        product_type="CNC",
    )


def _adapter(transport: InMemoryDhanTransport | None = None) -> DhanMarketDataAdapter:
    instrument = _instrument()
    return DhanMarketDataAdapter(
        _instruments={instrument.instrument_id: (instrument, _ref())},
        _transport=transport or InMemoryDhanTransport(),
    )


def _quote_snapshot(**overrides) -> DhanQuoteSnapshot:
    values = {
        "security_id": "1333",
        "exchange_segment": "NSE_EQ",
        "observed_at": T0,
        "last_price": Decimal("100"),
        "bid_price": Decimal("99"),
        "ask_price": Decimal("100"),
        "bid_size": Decimal("10"),
        "ask_size": Decimal("12"),
    }
    values.update(overrides)
    return DhanQuoteSnapshot(**values)


def _candle_snapshot(timestamp: datetime, **overrides) -> DhanCandleSnapshot:
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


def test_adapter_conforms_to_market_data_port() -> None:
    adapter = _adapter()

    assert isinstance(adapter, MarketDataPort)


def test_quote_normalizes_all_fields() -> None:
    adapter = _adapter(
        InMemoryDhanTransport(quote_snapshots={("1333", "NSE_EQ"): _quote_snapshot()})
    )
    instrument = InstrumentId("NSE", "TCS")

    quote = adapter.quote(instrument)

    assert quote is not None
    assert quote.instrument == instrument
    assert quote.timestamp == T0
    assert quote.bid == Decimal("99")
    assert quote.ask == Decimal("100")
    assert quote.last == Decimal("100")
    assert quote.bid_size == Decimal("10")
    assert quote.ask_size == Decimal("12")


def test_quote_snapshot_rejects_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _quote_snapshot(observed_at=datetime(2026, 1, 1, 9, 15))


def test_quote_preserves_requested_instrument_identity() -> None:
    adapter = _adapter(
        InMemoryDhanTransport(quote_snapshots={("1333", "NSE_EQ"): _quote_snapshot()})
    )

    quote = adapter.quote(InstrumentId("NSE", "TCS"))

    assert quote is not None
    assert quote.instrument == InstrumentId("NSE", "TCS")


def test_missing_quote_fields_remain_none() -> None:
    snapshot = _quote_snapshot(bid_price=None, ask_price=None, bid_size=None, ask_size=None)
    adapter = _adapter(InMemoryDhanTransport(quote_snapshots={("1333", "NSE_EQ"): snapshot}))

    quote = adapter.quote(InstrumentId("NSE", "TCS"))

    assert quote is not None
    assert quote.bid is None
    assert quote.ask is None
    assert quote.bid_size is None
    assert quote.ask_size is None
    assert quote.last == Decimal("100")


def test_malformed_quote_values_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        _quote_snapshot(last_price=Decimal("-1"))


def test_unknown_instrument_mapping_rejected() -> None:
    adapter = _adapter()

    with pytest.raises(ValueError, match="mapping missing"):
        adapter.quote(InstrumentId("NSE", "INFY"))


def test_candle_normalization_preserves_fields() -> None:
    adapter = _adapter(
        InMemoryDhanTransport(candle_snapshots={("1333", "NSE_EQ"): (_candle_snapshot(T0),)})
    )
    instrument = InstrumentId("NSE", "TCS")

    (candle,) = adapter.candles(instrument, timeframe="1m", start=T0, end=T0)

    assert candle.instrument == instrument
    assert candle.timeframe == "1m"
    assert candle.timestamp == T0
    assert candle.open == Decimal("99")
    assert candle.high == Decimal("101")
    assert candle.low == Decimal("98")
    assert candle.close == Decimal("100")
    assert candle.volume == Decimal("1000")


def test_candles_returned_in_chronological_order() -> None:
    adapter = _adapter(
        InMemoryDhanTransport(
            candle_snapshots={("1333", "NSE_EQ"): (_candle_snapshot(T2), _candle_snapshot(T0))}
        )
    )

    candles = adapter.candles(InstrumentId("NSE", "TCS"), timeframe="1m", start=T0, end=T2)

    assert [candle.timestamp for candle in candles] == [T0, T2]


def test_candles_respect_start_end_boundaries() -> None:
    adapter = _adapter(
        InMemoryDhanTransport(
            candle_snapshots={
                ("1333", "NSE_EQ"): (
                    _candle_snapshot(T0),
                    _candle_snapshot(T1),
                    _candle_snapshot(T2),
                )
            }
        )
    )

    candles = adapter.candles(InstrumentId("NSE", "TCS"), timeframe="1m", start=T1, end=T1)

    assert [candle.timestamp for candle in candles] == [T1]


def test_candles_reject_unsupported_timeframe() -> None:
    adapter = _adapter()

    with pytest.raises(ValueError, match="timeframe"):
        adapter.candles(InstrumentId("NSE", "TCS"), timeframe="1w", start=T0, end=T1)


def test_candles_reject_naive_boundaries() -> None:
    adapter = _adapter()
    naive = datetime(2026, 1, 1, 9, 15)

    with pytest.raises(ValueError, match="timezone-aware"):
        adapter.candles(InstrumentId("NSE", "TCS"), timeframe="1m", start=naive, end=T1)


def test_malformed_candle_data_rejected() -> None:
    adapter = _adapter(
        InMemoryDhanTransport(
            candle_snapshots={
                ("1333", "NSE_EQ"): (_candle_snapshot(T0, high=Decimal("90"), low=Decimal("98")),)
            }
        )
    )

    with pytest.raises(ValueError, match="high/low"):
        adapter.candles(InstrumentId("NSE", "TCS"), timeframe="1m", start=T0, end=T0)


def test_subscribe_rejected_explicitly() -> None:
    adapter = _adapter()

    with pytest.raises(ValueError, match="streaming is not supported"):
        adapter.subscribe((InstrumentId("NSE", "TCS"),))


def test_unsubscribe_rejected_explicitly() -> None:
    adapter = _adapter()

    with pytest.raises(ValueError, match="streaming is not supported"):
        adapter.unsubscribe((InstrumentId("NSE", "TCS"),))


def test_no_data_is_never_fabricated() -> None:
    adapter = _adapter()

    assert adapter.quote(InstrumentId("NSE", "TCS")) is None
    assert adapter.candles(InstrumentId("NSE", "TCS"), timeframe="1m", start=T0, end=T1) == ()


def test_vendor_sdk_isolated_to_transport() -> None:
    import quantx.plugins.dhan.market_data as market_data_module

    package = Path(market_data_module.__file__).resolve().parent
    checked = (
        "adapter.py",
        "capabilities.py",
        "host.py",
        "market_data.py",
        "mapping.py",
        "models.py",
        "recovery.py",
        "__init__.py",
    )
    for name in checked:
        source = (package / name).read_text()
        assert "dhanhq" not in source, name


def test_transport_to_port_integration() -> None:
    transport = InMemoryDhanTransport(
        quote_snapshots={("1333", "NSE_EQ"): _quote_snapshot()},
        candle_snapshots={("1333", "NSE_EQ"): (_candle_snapshot(T1),)},
    )
    adapter: MarketDataPort = _adapter(transport)
    instrument = InstrumentId("NSE", "TCS")

    quote = adapter.quote(instrument)
    candles = tuple(adapter.candles(instrument, timeframe="1m", start=T0, end=T2))

    assert quote is not None
    assert quote.last == Decimal("100")
    assert [candle.timestamp for candle in candles] == [T1]


def test_market_data_adapter_threads_read_timeout_to_transport() -> None:
    from dataclasses import dataclass, field

    @dataclass(slots=True)
    class _RecordingTransport:
        seen_timeouts: list[float] = field(default_factory=list)
        _inner: InMemoryDhanTransport = field(default_factory=InMemoryDhanTransport)

        def quote_snapshot(
            self,
            security_id: str,
            exchange_segment: str,
            *,
            timeout: float = 10.0,
        ) -> DhanQuoteSnapshot | None:
            self.seen_timeouts.append(timeout)
            return self._inner.quote_snapshot(security_id, exchange_segment, timeout=timeout)

        def candles(
            self,
            security_id: str,
            exchange_segment: str,
            *,
            timeframe: str,
            start: datetime,
            end: datetime,
            instrument_type: str = "EQUITY",
            timeout: float = 10.0,
        ) -> tuple[DhanCandleSnapshot, ...]:
            self.seen_timeouts.append(timeout)
            return self._inner.candles(
                security_id,
                exchange_segment,
                timeframe=timeframe,
                start=start,
                end=end,
                instrument_type=instrument_type,
                timeout=timeout,
            )

    transport = _RecordingTransport()
    transport._inner = InMemoryDhanTransport(
        quote_snapshots={("1333", "NSE_EQ"): _quote_snapshot()},
        candle_snapshots={("1333", "NSE_EQ"): (_candle_snapshot(T1),)},
    )
    instrument = InstrumentId("NSE", "TCS")
    adapter = DhanMarketDataAdapter(
        _instruments={instrument: (_instrument(), _ref())},
        _transport=transport,
        _read_timeout=3.5,
    )

    assert adapter.quote(instrument) is not None
    assert adapter.candles(instrument, timeframe="1m", start=T0, end=T2) != ()

    assert transport.seen_timeouts == [3.5, 3.5]
