"""End-to-end deterministic dataset-to-research proof for R1-C14.

One declared dataset identity is followed through provider retrieval,
ingestion, quality evidence, durable persistence, dataset-scoped read,
provenance binding, and the durable research-run lifecycle, then verified
again after a database reopen:

DatasetVersion -> MarketDataPort -> ingestion -> quality -> MarketDataStore
    -> dataset-backed read -> ResearchProvenance -> ResearchRun
"""

from datetime import UTC, datetime
from decimal import Decimal

from quantx.application.dataset_ingestion import HistoricalDatasetIngestionService
from quantx.application.dataset_research_binding import research_run_spec_from_ingestion
from quantx.application.research_run import ResearchRunApplicationService
from quantx.domain.clock import FixedClock
from quantx.domain.enums import AssetClass
from quantx.domain.instruments import Instrument, MarketContext, MarketFamily, MarketRegion
from quantx.domain.market_data import Candle
from quantx.domain.value_objects import InstrumentId
from quantx.persistence.sqlite import SqliteDatabase
from quantx.persistence.sqlite.market_data import SqliteMarketDataStore
from quantx.persistence.sqlite.research import SqliteResearchRunRepository
from quantx.plugins.dhan import DhanInstrumentRef, DhanMarketDataAdapter, InMemoryDhanTransport
from quantx.plugins.dhan.models import DhanCandleSnapshot
from quantx.research.data_quality import CompletenessStatus, DataQualityStatus
from quantx.research.dataset import DatasetIdentity, DatasetVersion, fingerprint_bytes
from quantx.research.dataset_access import read_candles
from quantx.research.dataset_catalog import FilesystemDatasetCatalog
from quantx.research.result import ResearchResult, ResultQuality
from quantx.research.run import ResearchRunState

T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
T1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
INSTRUMENT = InstrumentId("NSE", "TCS")
RUN_ID = "run-c14-proof-1"


def _instrument() -> Instrument:
    return Instrument(
        instrument_id=INSTRUMENT,
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def _snapshots() -> tuple[DhanCandleSnapshot, DhanCandleSnapshot]:
    return (
        DhanCandleSnapshot(
            timeframe="1m",
            timestamp=T0,
            open=Decimal("99"),
            high=Decimal("101"),
            low=Decimal("98"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        ),
        DhanCandleSnapshot(
            timeframe="1m",
            timestamp=T1,
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("99"),
            close=Decimal("101"),
            volume=Decimal("1100"),
        ),
    )


def _expected_candles() -> tuple[Candle, Candle]:
    return (
        Candle(
            instrument=INSTRUMENT,
            timeframe="1m",
            timestamp=T0,
            open=Decimal("99"),
            high=Decimal("101"),
            low=Decimal("98"),
            close=Decimal("100"),
            volume=Decimal("1000"),
        ),
        Candle(
            instrument=INSTRUMENT,
            timeframe="1m",
            timestamp=T1,
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("99"),
            close=Decimal("101"),
            volume=Decimal("1100"),
        ),
    )


def test_declared_dataset_flows_deterministically_to_durable_research_run(tmp_path) -> None:
    catalog = FilesystemDatasetCatalog(tmp_path / "catalog")
    registered = catalog.register(
        DatasetVersion(
            identity=DatasetIdentity(
                dataset_id="nse-equities",
                version="2026-01",
                source_id="dhan",
                schema_version="1",
                content_fingerprint=fingerprint_bytes(b"declared"),
            )
        )
    )
    market_data = DhanMarketDataAdapter(
        _instruments={
            INSTRUMENT: (
                _instrument(),
                DhanInstrumentRef("1333", "NSE_EQ", "TCS", "CNC"),
            )
        },
        _transport=InMemoryDhanTransport(candle_snapshots={("1333", "NSE_EQ"): _snapshots()}),
    )
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        store = SqliteMarketDataStore(database)
        result = HistoricalDatasetIngestionService(
            catalog=catalog, market_data=market_data, store=store
        ).ingest(
            dataset_id="nse-equities",
            version="2026-01",
            instrument=INSTRUMENT,
            timeframe="1m",
            start=T0,
            end=T1,
            expected_timestamps=(T0, T1),
        )
        assert result.inserted_count == 2
        assert result.dataset_version.identity == registered.identity
        assert result.quality.quality is DataQualityStatus.VALID
        assert result.quality.completeness is CompletenessStatus.COMPLETE
        retrieved = read_candles(
            catalog=catalog,
            store=store,
            dataset_id="nse-equities",
            version="2026-01",
            instrument=INSTRUMENT,
            timeframe="1m",
            start=T0,
            end=T1,
        )
        assert retrieved == _expected_candles()
        bind_inputs = {
            "run_id": RUN_ID,
            "instrument_master_version": "instruments-v1",
            "market_rule_version": "rules-v1",
            "execution_model_version": "model-v1",
            "simulation_profile": "paper-v1",
            "code_revision": "code-v1",
            "configuration_revision": "config-v1",
        }
        spec = research_run_spec_from_ingestion(result, **bind_inputs)
        assert spec.dataset_id == "nse-equities"
        assert spec.dataset_version == "2026-01"
        fingerprint = spec.to_provenance().fingerprint()
        repeated = research_run_spec_from_ingestion(result, **bind_inputs)
        assert repeated.to_provenance().fingerprint() == fingerprint
        run_service = ResearchRunApplicationService(
            repository=SqliteResearchRunRepository(database),
            clock=FixedClock(datetime(2026, 10, 6, 10, 0, tzinfo=UTC)),
        )
        operation_result = ResearchResult(
            spec=spec,
            quality=ResultQuality.COMPLETE_WITH_DETERMINISTIC_DERIVATIONS,
            started_at="2026-10-06T10:00:00+00:00",
            completed_at="2026-10-06T10:05:00+00:00",
            time_range_start="2026-01-01T09:15:00+00:00",
            time_range_end="2026-01-01T15:30:00+00:00",
            metrics=(("inserted_count", Decimal("2")),),
        )
        execution = run_service.execute(spec, lambda: operation_result)
        assert execution.run.state is ResearchRunState.COMPLETED
        assert execution.run.provenance_fingerprint == fingerprint
    finally:
        database.close()

    reopened = SqliteDatabase(tmp_path / "quantx.db")
    try:
        reread = read_candles(
            catalog=FilesystemDatasetCatalog(tmp_path / "catalog"),
            store=SqliteMarketDataStore(reopened),
            dataset_id="nse-equities",
            version="2026-01",
            instrument=INSTRUMENT,
            timeframe="1m",
            start=T0,
            end=T1,
        )
        assert reread == _expected_candles()
        reloaded = SqliteResearchRunRepository(reopened).get_run(RUN_ID)
        assert reloaded is not None
        assert reloaded.state is ResearchRunState.COMPLETED
        assert reloaded.provenance_fingerprint == fingerprint
    finally:
        reopened.close()
