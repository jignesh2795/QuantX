from datetime import UTC, datetime
from decimal import Decimal

from quantx.domain.enums import AssetClass
from quantx.domain.market_data import Candle, Quote
from quantx.domain.value_objects import InstrumentId
from quantx.india.domain import IndianExchange, IndianInstrumentSpec, IndianSegment
from quantx.research.data import HistoricalDataSeries, HistoricalObservation


def test_indian_equity_spec_builds_universal_instrument() -> None:
    spec = IndianInstrumentSpec(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        exchange=IndianExchange.NSE,
        segment=IndianSegment.EQUITY,
    )
    instrument = spec.to_instrument()
    assert instrument.market.venue == "NSE"
    assert instrument.currency == "INR"


def test_market_data_is_framework_independent() -> None:
    quote = Quote(
        instrument=InstrumentId("NSE", "TCS"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        bid=Decimal("99"),
        ask=Decimal("100"),
    )
    candle = Candle(
        instrument=InstrumentId("NSE", "TCS"),
        timeframe="5m",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
    )
    assert candle.close == Decimal("100.5")
    series = HistoricalDataSeries(
        (
            HistoricalObservation(
                snapshot=quote,
                source_id="test",
                dataset_version="1",
                sequence=1,
            ),
            HistoricalObservation(
                snapshot=Quote(
                    instrument=InstrumentId("NSE", "TCS"),
                    timestamp=datetime(2026, 1, 1, 0, 5, tzinfo=UTC),
                    bid=Decimal("100"),
                    ask=Decimal("101"),
                ),
                source_id="test",
                dataset_version="1",
                sequence=2,
            ),
        )
    )
    assert len(series) == 2
    assert series.latest_at_or_before(datetime(2026, 1, 1, 0, 3, tzinfo=UTC)) is not None


def test_transaction_coordinator_stores_receipt_id_for_idempotency(monkeypatch) -> None:
    from uuid import uuid4

    from quantx.execution.idempotency import InMemoryIdempotencyStore
    from quantx.execution.preconditions.models import (
        PreconditionsResult,
        PreconditionsStatus,
    )
    from quantx.execution.transactions.coordinator import ExecutionTransactionCoordinator

    request_id = uuid4()
    client_order_id = uuid4()
    receipt_id = uuid4()

    request = type("Request", (), {})()
    request.order = type("Order", (), {"client_order_id": client_order_id})()

    receipt = type("Receipt", (), {"request_id": request_id, "receipt_id": receipt_id})()

    monkeypatch.setattr(
        "quantx.execution.transactions.coordinator.request_fingerprint",
        lambda _: "fingerprint-a",
    )

    store = InMemoryIdempotencyStore()
    coordinator = ExecutionTransactionCoordinator(
        idempotency=store,
        preconditions=lambda _: PreconditionsResult(PreconditionsStatus.READY),
        submit=lambda _: receipt,
    )

    result = coordinator.execute(request)

    assert result.receipt is receipt
    decision = store.check(client_order_id, "fingerprint-a")
    assert decision.existing_receipt_id == receipt_id
