from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantx.domain.enums import OrderStatus
from quantx.domain.market_data import Candle, MarketDataEvent, MarketDataType, Quote
from quantx.domain.strategy import StrategyDefinition, StrategyId
from quantx.domain.value_objects import InstrumentId
from quantx.execution.accounting import PositionLedgerEntry
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.context import StrategyContext
from quantx.strategy.engine_snapshot import (
    EngineEvidenceAdapter,
    EvidenceAvailability,
    EvidenceCollection,
    OpenOrderFact,
    PositionFact,
    TemporalIntegrityError,
    build_engine_snapshot,
    prior_candle_history,
    unavailable_engine_snapshot,
)


def _instrument(symbol: str = "TCS") -> InstrumentId:
    return InstrumentId("NSE", symbol)


def _ir():
    return StrategyCompiler.compile(
        StrategyDefinition(StrategyId("buy-and-hold"), "1", "Buy and Hold", parameters={"quantity": "2"})
    )


def _event(timestamp: datetime | None = None) -> MarketDataEvent:
    instant = timestamp or datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    instrument = _instrument()
    return MarketDataEvent(
        MarketDataType.QUOTE,
        instant,
        instrument,
        Quote(instrument, instant, bid=Decimal("99"), ask=Decimal("100"), last=Decimal("100")),
    )


def _candle(timestamp: datetime, instrument: InstrumentId | None = None) -> Candle:
    return Candle(
        instrument=instrument or _instrument(),
        timeframe="1m",
        timestamp=timestamp,
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("10"),
    )


def _adapter(
    *,
    positions: EvidenceCollection[PositionFact] | None = None,
    orders: EvidenceCollection[OpenOrderFact] | None = None,
) -> EngineEvidenceAdapter:
    return EngineEvidenceAdapter(
        positions=positions or EvidenceCollection.known(()),
        orders=orders or EvidenceCollection.known(()),
        account_state=None,
        account_reason="test adapter has no account-state tracker",
    )


def test_default_context_has_explicit_unavailable_state_not_known_empty() -> None:
    context = StrategyContext(_event(), _ir())

    assert context.engine.positions.availability is EvidenceAvailability.UNAVAILABLE
    assert context.engine.positions.reason
    assert context.engine.orders.availability is EvidenceAvailability.UNAVAILABLE
    assert context.engine.account_availability is EvidenceAvailability.UNAVAILABLE
    assert context.params.get_int("quantity") == 2
    assert context.as_of == _event().timestamp


def test_known_empty_inventory_is_distinct_from_unavailable_inventory() -> None:
    as_of = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    snapshot = build_engine_snapshot(_adapter(), as_of=as_of)
    unavailable = unavailable_engine_snapshot(as_of, "driver evidence was not supplied")

    assert snapshot.positions.availability is EvidenceAvailability.AVAILABLE
    assert snapshot.positions.items == ()
    assert snapshot.orders.availability is EvidenceAvailability.AVAILABLE
    assert unavailable.positions.availability is EvidenceAvailability.UNAVAILABLE
    assert unavailable.positions.reason == "driver evidence was not supplied"


def test_snapshot_projects_position_facts_without_changing_decimal_values() -> None:
    entry = PositionLedgerEntry(
        instrument=_instrument(),
        quantity=Decimal("2"),
        average_price=Decimal("100.25"),
        realized_pnl=Decimal("1.10"),
        fees=Decimal("0.05"),
    )
    as_of = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    fact = PositionFact.from_ledger_entry(entry, effective_at=as_of)
    snapshot = build_engine_snapshot(
        _adapter(positions=EvidenceCollection.known((fact,))),
        as_of=as_of,
    )
    assert snapshot.positions.items == (fact,)
    assert snapshot.positions.items[0].quantity == Decimal("2")
    assert snapshot.positions.items[0].average_price == Decimal("100.25")


def test_unknown_order_status_is_not_removed_as_canonical_terminal() -> None:
    as_of = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    fact = OpenOrderFact(
        client_order_id="order-1",
        instrument=_instrument(),
        status=OrderStatus.UNKNOWN,
        order_quantity=Decimal("2"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("2"),
        created_at=as_of,
        evidence_time=as_of,
        reason="execution outcome is uncertain",
    )
    snapshot = build_engine_snapshot(
        _adapter(orders=EvidenceCollection.known((fact,))),
        as_of=as_of,
    )
    assert snapshot.orders.items == (fact,)


def test_snapshot_rejects_future_effective_position_evidence() -> None:
    as_of = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    entry = PositionLedgerEntry(
        instrument=_instrument(),
        quantity=Decimal("1"),
        average_price=Decimal("100"),
        realized_pnl=Decimal("0"),
        fees=Decimal("0"),
    )
    fact = PositionFact.from_ledger_entry(
        entry,
        effective_at=as_of + timedelta(seconds=1),
    )
    with pytest.raises(TemporalIntegrityError, match="position evidence"):
        build_engine_snapshot(
            _adapter(positions=EvidenceCollection.known((fact,))),
            as_of=as_of,
        )


def test_snapshot_rejects_future_effective_order_evidence() -> None:
    as_of = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    future_fact = OpenOrderFact(
        client_order_id="future-order",
        instrument=_instrument(),
        status=OrderStatus.ACCEPTED,
        order_quantity=Decimal("1"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("1"),
        created_at=as_of,
        evidence_time=as_of + timedelta(seconds=1),
    )
    with pytest.raises(TemporalIntegrityError, match="later than snapshot as_of"):
        build_engine_snapshot(
            _adapter(orders=EvidenceCollection.known((future_fact,))),
            as_of=as_of,
        )


def test_history_is_prior_only_same_instrument_and_most_recent_first_window() -> None:
    as_of = datetime(2026, 1, 1, 9, 18, tzinfo=UTC)
    candles = (
        _candle(as_of - timedelta(minutes=3)),
        _candle(as_of - timedelta(minutes=2)),
        _candle(as_of - timedelta(minutes=1)),
        _candle(as_of),
        _candle(as_of - timedelta(minutes=1), _instrument("INFY")),
    )
    history = prior_candle_history(
        candles, instrument=_instrument(), as_of=as_of, limit=2
    )
    assert history == candles[1:3]
    assert prior_candle_history(candles, instrument=_instrument(), as_of=as_of, limit=0) == ()


def test_context_rejects_nonprior_or_cross_instrument_history() -> None:
    instant = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    future = _candle(instant)
    other = _candle(instant - timedelta(minutes=1), _instrument("INFY"))
    with pytest.raises(ValueError, match="strictly prior"):
        StrategyContext(_event(instant), _ir(), history=(future,))
    with pytest.raises(ValueError, match="event instrument"):
        StrategyContext(_event(instant), _ir(), history=(other,))
