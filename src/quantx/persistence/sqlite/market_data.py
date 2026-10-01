"""SQLite-backed vendor-neutral market-data store.

Canonical ``Quote``/``Candle`` values round-trip exactly: decimals are
stored with ``str()`` (never binary floating point) and timestamps are
normalized to UTC so chronological ordering is deterministic. Duplicate
identity with identical content is an idempotent no-op; duplicate identity
with different content is an explicit conflict. Nothing is ever silently
overwritten and nothing is fabricated on read.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from quantx.domain.market_data import Candle, Quote
from quantx.domain.value_objects import InstrumentId

from .database import SqliteDatabase


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("market-data timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _decimal_or_none(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


class SqliteMarketDataStore:
    """Durable canonical market-data storage behind the ``MarketDataStore`` port."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def save_candles(
        self,
        candles: Iterable[Candle],
        *,
        source_id: str,
        dataset_version: str = "",
    ) -> int:
        """Persist candles; identical duplicates are skipped, conflicts raise."""
        _require_source(source_id)
        inserted = 0
        with self._database.transaction() as connection:
            for candle in candles:
                row = (
                    candle.instrument.venue,
                    candle.instrument.symbol,
                    candle.timeframe,
                    _utc_timestamp(candle.timestamp),
                    str(candle.open),
                    str(candle.high),
                    str(candle.low),
                    str(candle.close),
                    str(candle.volume),
                    source_id,
                    dataset_version,
                )
                existing = connection.execute(
                    "SELECT open, high, low, close, volume "
                    "FROM market_candles "
                    "WHERE instrument_venue = ? AND instrument_symbol = ? "
                    "AND timeframe = ? AND timestamp = ? "
                    "AND source_id = ? AND dataset_version = ?",
                    row[:4] + row[9:],
                ).fetchone()
                if existing is None:
                    connection.execute(
                        "INSERT INTO market_candles "
                        "(instrument_venue, instrument_symbol, timeframe, timestamp, "
                        "open, high, low, close, volume, source_id, dataset_version) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        row,
                    )
                    inserted += 1
                elif tuple(existing) != row[4:9]:
                    raise ValueError(
                        "conflicting market candle already stored for "
                        f"{candle.instrument} {candle.timeframe} "
                        f"{candle.timestamp.isoformat()}"
                    )
        return inserted

    def get_candles(
        self,
        instrument: InstrumentId,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        source_id: str | None = None,
        dataset_version: str | None = None,
    ) -> tuple[Candle, ...]:
        """Return stored candles for one instrument/timeframe in [start, end]."""
        if not timeframe.strip():
            raise ValueError("timeframe must not be empty")
        start_text = _utc_timestamp(start)
        end_text = _utc_timestamp(end)
        if end_text < start_text:
            raise ValueError("candle end must not precede start")
        query = (
            "SELECT instrument_venue, instrument_symbol, timeframe, timestamp, "
            "open, high, low, close, volume, source_id, dataset_version "
            "FROM market_candles "
            "WHERE instrument_venue = ? AND instrument_symbol = ? AND timeframe = ? "
            "AND timestamp >= ? AND timestamp <= ?"
        )
        arguments: list[object] = [
            instrument.venue,
            instrument.symbol,
            timeframe,
            start_text,
            end_text,
        ]
        if source_id is not None:
            query += " AND source_id = ?"
            arguments.append(source_id)
        if dataset_version is not None:
            query += " AND dataset_version = ?"
            arguments.append(dataset_version)
        query += " ORDER BY timestamp ASC, source_id ASC, dataset_version ASC"
        with self._database.transaction() as connection:
            rows = connection.execute(query, tuple(arguments)).fetchall()
        return tuple(
            Candle(
                instrument=InstrumentId(row[0], row[1]),
                timeframe=row[2],
                timestamp=datetime.fromisoformat(row[3]),
                open=Decimal(row[4]),
                high=Decimal(row[5]),
                low=Decimal(row[6]),
                close=Decimal(row[7]),
                volume=Decimal(row[8]),
            )
            for row in rows
        )

    def save_quotes(
        self,
        quotes: Iterable[Quote],
        *,
        source_id: str,
        dataset_version: str = "",
    ) -> int:
        """Persist quotes; identical duplicates are skipped, conflicts raise."""
        _require_source(source_id)
        inserted = 0
        with self._database.transaction() as connection:
            for quote in quotes:
                row = (
                    quote.instrument.venue,
                    quote.instrument.symbol,
                    _utc_timestamp(quote.timestamp),
                    _decimal_or_none(quote.bid),
                    _decimal_or_none(quote.ask),
                    _decimal_or_none(quote.last),
                    _decimal_or_none(quote.bid_size),
                    _decimal_or_none(quote.ask_size),
                    source_id,
                    dataset_version,
                )
                existing = connection.execute(
                    "SELECT bid, ask, last, bid_size, ask_size "
                    "FROM market_quotes "
                    "WHERE instrument_venue = ? AND instrument_symbol = ? "
                    "AND timestamp = ? AND source_id = ? AND dataset_version = ?",
                    (row[0], row[1], row[2], row[8], row[9]),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        "INSERT INTO market_quotes "
                        "(instrument_venue, instrument_symbol, timestamp, "
                        "bid, ask, last, bid_size, ask_size, source_id, dataset_version) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        row,
                    )
                    inserted += 1
                elif tuple(existing) != row[3:8]:
                    raise ValueError(
                        "conflicting market quote already stored for "
                        f"{quote.instrument} {quote.timestamp.isoformat()}"
                    )
        return inserted

    def get_quotes(
        self,
        instrument: InstrumentId,
        *,
        start: datetime,
        end: datetime,
        source_id: str | None = None,
        dataset_version: str | None = None,
    ) -> tuple[Quote, ...]:
        """Return stored quotes for one instrument in [start, end]."""
        start_text = _utc_timestamp(start)
        end_text = _utc_timestamp(end)
        if end_text < start_text:
            raise ValueError("quote end must not precede start")
        query = (
            "SELECT instrument_venue, instrument_symbol, timestamp, "
            "bid, ask, last, bid_size, ask_size, source_id, dataset_version "
            "FROM market_quotes "
            "WHERE instrument_venue = ? AND instrument_symbol = ? "
            "AND timestamp >= ? AND timestamp <= ?"
        )
        arguments: list[object] = [
            instrument.venue,
            instrument.symbol,
            start_text,
            end_text,
        ]
        if source_id is not None:
            query += " AND source_id = ?"
            arguments.append(source_id)
        if dataset_version is not None:
            query += " AND dataset_version = ?"
            arguments.append(dataset_version)
        query += " ORDER BY timestamp ASC, source_id ASC, dataset_version ASC"
        with self._database.transaction() as connection:
            rows = connection.execute(query, tuple(arguments)).fetchall()
        return tuple(
            Quote(
                instrument=InstrumentId(row[0], row[1]),
                timestamp=datetime.fromisoformat(row[2]),
                bid=None if row[3] is None else Decimal(row[3]),
                ask=None if row[4] is None else Decimal(row[4]),
                last=None if row[5] is None else Decimal(row[5]),
                bid_size=None if row[6] is None else Decimal(row[6]),
                ask_size=None if row[7] is None else Decimal(row[7]),
            )
            for row in rows
        )


def _require_source(source_id: str) -> None:
    if not source_id.strip():
        raise ValueError("market-data source_id must not be empty")


__all__ = ["SqliteMarketDataStore"]
