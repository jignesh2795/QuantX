"""Indian historical-data normalization adapter."""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId
from quantx.research.calendar import MarketCalendar
from quantx.research.data import HistoricalObservation
from quantx.research.ingest import CanonicalOHLCVNormalizer, RawMarketRecord

from .instrument_catalog import IndianInstrumentCatalog


@dataclass(frozen=True, slots=True)
class IndianHistoricalOHLCVNormalizer:
    """Normalize Indian source records to catalog-resolved canonical identity."""

    catalog: IndianInstrumentCatalog
    instrument_id: InstrumentId
    dataset_id: str
    dataset_version: str
    calendar: MarketCalendar | None = None

    def normalize(self, record: RawMarketRecord) -> HistoricalObservation:
        instrument = self.catalog.resolve(self.instrument_id)
        if instrument is None:
            raise ValueError(f"unknown Indian instrument: {self.instrument_id}")
        if record.instrument != instrument.symbol:
            raise ValueError(
                f"source symbol {record.instrument!r} does not match "
                f"instrument {instrument.symbol!r}"
            )

        observation = CanonicalOHLCVNormalizer(
            dataset_id=self.dataset_id,
            dataset_version=self.dataset_version,
            calendar=self.calendar,
        ).normalize(record)
        snapshot = observation.snapshot
        if not isinstance(snapshot, Candle):
            raise TypeError("historical OHLCV normalization must produce a Candle")

        canonical_snapshot = Candle(
            instrument=instrument.instrument_id,
            timeframe=snapshot.timeframe,
            timestamp=snapshot.timestamp,
            open=snapshot.open,
            high=snapshot.high,
            low=snapshot.low,
            close=snapshot.close,
            volume=snapshot.volume,
        )
        return HistoricalObservation(
            snapshot=canonical_snapshot,
            source_id=observation.source_id,
            dataset_version=observation.dataset_version,
            sequence=observation.sequence,
        )


__all__ = ["IndianHistoricalOHLCVNormalizer"]
