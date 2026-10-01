from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.market_data import Candle, MarketDataEvent, MarketDataType, Quote
from quantx.domain.value_objects import InstrumentId


def _instrument() -> InstrumentId:
    return InstrumentId("NSE", "TCS")


def _timestamp() -> datetime:
    return datetime(2026, 1, 1, 9, 15, tzinfo=UTC)


def test_quote_derives_mid_and_spread_from_normalized_fields() -> None:
    quote = Quote(
        instrument=_instrument(),
        timestamp=_timestamp(),
        bid=Decimal("99"),
        ask=Decimal("101"),
        last=Decimal("100"),
        bid_size=Decimal("10"),
        ask_size=Decimal("20"),
    )

    assert quote.mid == Decimal("100")
    assert quote.spread == Decimal("2")


@pytest.mark.parametrize("field", ("bid", "ask", "last", "bid_size", "ask_size"))
def test_quote_rejects_negative_market_data_values(field: str) -> None:
    values = {
        "bid": Decimal("99"),
        "ask": Decimal("100"),
        "last": Decimal("100"),
        "bid_size": Decimal("1"),
        "ask_size": Decimal("1"),
    }
    values[field] = Decimal("-1")

    with pytest.raises(ValueError, match=f"{field} cannot be negative"):
        Quote(
            instrument=_instrument(),
            timestamp=_timestamp(),
            **values,
        )


def test_quote_rejects_inverted_market() -> None:
    with pytest.raises(ValueError, match="bid cannot exceed ask"):
        Quote(
            instrument=_instrument(),
            timestamp=_timestamp(),
            bid=Decimal("101"),
            ask=Decimal("100"),
        )


def test_quote_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="quote timestamp must be timezone-aware"):
        Quote(
            instrument=_instrument(),
            timestamp=datetime(2026, 1, 1, 9, 15),
            last=Decimal("100"),
        )


def test_candle_requires_valid_ohlc_envelope_and_nonnegative_volume() -> None:
    timestamp = _timestamp()

    with pytest.raises(ValueError, match="candle high/low do not contain open/close"):
        Candle(
            instrument=_instrument(),
            timeframe="1m",
            timestamp=timestamp,
            open=Decimal("100"),
            high=Decimal("99"),
            low=Decimal("98"),
            close=Decimal("100"),
        )

    with pytest.raises(ValueError, match="candle volume cannot be negative"):
        Candle(
            instrument=_instrument(),
            timeframe="1m",
            timestamp=timestamp,
            open=Decimal("99"),
            high=Decimal("101"),
            low=Decimal("98"),
            close=Decimal("100"),
            volume=Decimal("-1"),
        )


def test_market_data_event_requires_payload_instrument_identity_match() -> None:
    timestamp = _timestamp()
    quote = Quote(
        instrument=InstrumentId("NSE", "TCS"),
        timestamp=timestamp,
        last=Decimal("100"),
    )

    with pytest.raises(
        ValueError,
        match="market-data event instrument must match its payload",
    ):
        MarketDataEvent(
            data_type=MarketDataType.QUOTE,
            timestamp=timestamp,
            instrument=InstrumentId("NSE", "INFY"),
            payload=quote,
        )


def test_market_data_event_preserves_normalized_quote_contract() -> None:
    timestamp = _timestamp()
    instrument = _instrument()
    quote = Quote(
        instrument=instrument,
        timestamp=timestamp,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )

    event = MarketDataEvent(
        data_type=MarketDataType.QUOTE,
        timestamp=timestamp,
        instrument=instrument,
        payload=quote,
    )

    assert event.data_type is MarketDataType.QUOTE
    assert event.instrument == quote.instrument
    assert event.timestamp == quote.timestamp
    assert event.payload == quote


def test_candle_requires_timeframe_and_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timeframe must not be empty"):
        Candle(
            instrument=_instrument(),
            timeframe=" ",
            timestamp=_timestamp(),
            open=Decimal("99"),
            high=Decimal("101"),
            low=Decimal("98"),
            close=Decimal("100"),
        )

    with pytest.raises(ValueError, match="candle timestamp must be timezone-aware"):
        Candle(
            instrument=_instrument(),
            timeframe="1m",
            timestamp=datetime(2026, 1, 1, 9, 15),
            open=Decimal("99"),
            high=Decimal("101"),
            low=Decimal("98"),
            close=Decimal("100"),
        )
