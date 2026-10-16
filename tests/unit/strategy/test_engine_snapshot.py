from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantx.domain.enums import OrderStatus
from quantx.domain.finance import CapitalSourceType
from quantx.domain.market_data import Candle, MarketDataEvent, MarketDataType, Quote
from quantx.domain.strategy import StrategyDefinition, StrategyId
from quantx.domain.value_objects import InstrumentId, Money
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.historical_account_state import (
    AccountStateCompleteness,
    HistoricalAccountStateSnapshot,
    HistoricalValuationEvidence,
)
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.context import StrategyContext
from quantx.strategy.engine_snapshot import (
    EngineEvidenceAdapter,
    EvidenceAvailability,
    EvidenceCollection,
    OpenOrderFact,
    PositionFact,
    TemporalIntegrityError,
    active_order_fact,
    build_engine_snapshot,
    build_simulated_engine_snapshot,
    prior_candle_history,
    unavailable_engine_snapshot,
)


def _instrument(symbol: str = "TCS") -> InstrumentId:
    return InstrumentId("NSE", symbol)


def _ir():
    return StrategyCompiler.compile(
        StrategyDefinition(
            StrategyId("buy-and-hold"), "1", "Buy and Hold", parameters={"quantity": "2"}
        )
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
    assert context.engine.orders.reason
    assert context.engine.account_availability is EvidenceAvailability.UNAVAILABLE
    assert context.engine.account_state is None
    assert context.engine.account_reason
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


def test_simulated_snapshot_marks_unknown_order_inventory_incomplete() -> None:
    as_of = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    unresolved = OpenOrderFact(
        client_order_id="unknown-order",
        instrument=_instrument(),
        status=OrderStatus.UNKNOWN,
        order_quantity=Decimal("2"),
        filled_quantity=None,
        remaining_quantity=None,
        created_at=as_of,
        evidence_time=as_of,
        reason="execution status is unresolved",
        effective_at=as_of,
    )

    snapshot = build_simulated_engine_snapshot(
        as_of=as_of,
        accounting=FillAccounting(),
        active_orders=(unresolved,),
        account_state=None,
        account_reason="account valuation is unavailable in this driver",
    )
    known_empty = build_simulated_engine_snapshot(
        as_of=as_of,
        accounting=FillAccounting(),
        active_orders=(),
        account_state=None,
        account_reason="account valuation is unavailable in this driver",
    )

    assert snapshot.orders.availability is EvidenceAvailability.INCOMPLETE
    assert snapshot.orders.items == (unresolved,)
    assert snapshot.orders.reason is not None
    assert known_empty.orders.availability is EvidenceAvailability.AVAILABLE
    assert known_empty.orders.items == ()


def test_incomplete_position_order_and_account_evidence_keeps_reasons() -> None:
    as_of = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    account = HistoricalAccountStateSnapshot(
        timestamp=as_of,
        capital_source=CapitalSourceType.BACKTEST_CONFIGURED,
        cash=Money(Decimal("1000"), "INR"),
        market_value=None,
        equity=None,
        realized_pnl=Money.zero("INR"),
        unrealized_pnl=None,
        gross_exposure=None,
        fees=Money.zero("INR"),
        positions=(),
        completeness=AccountStateCompleteness.INCOMPLETE,
        unavailable_instruments=("NSE:TCS",),
        issue="explicit mark is stale for exact-current sampling",
    )
    adapter = EngineEvidenceAdapter(
        positions=EvidenceCollection.incomplete((), "position inventory is incomplete"),
        orders=EvidenceCollection.incomplete((), "order inventory is incomplete"),
        account_state=account,
        account_reason=account.issue,
    )

    snapshot = build_engine_snapshot(adapter, as_of=as_of)

    assert snapshot.positions.availability is EvidenceAvailability.INCOMPLETE
    assert snapshot.positions.reason == "position inventory is incomplete"
    assert snapshot.orders.availability is EvidenceAvailability.INCOMPLETE
    assert snapshot.orders.reason == "order inventory is incomplete"
    assert snapshot.account_availability is EvidenceAvailability.INCOMPLETE
    assert snapshot.account_reason == "explicit mark is stale for exact-current sampling"
    assert snapshot.account_state is account
    assert snapshot.account_state.market_value is None
    assert snapshot.account_state.equity is None


def _incomplete_account_with_valuation_evidence(
    as_of: datetime,
    evidence: HistoricalValuationEvidence,
) -> HistoricalAccountStateSnapshot:
    return HistoricalAccountStateSnapshot(
        timestamp=as_of,
        capital_source=CapitalSourceType.BACKTEST_CONFIGURED,
        cash=Money(Decimal("1000"), "INR"),
        market_value=None,
        equity=None,
        realized_pnl=Money.zero("INR"),
        unrealized_pnl=None,
        gross_exposure=None,
        fees=Money.zero("INR"),
        positions=(),
        completeness=AccountStateCompleteness.INCOMPLETE,
        unavailable_instruments=("NSE:TCS",),
        issue="account valuation is incomplete",
        valuation_evidence=(evidence,),
    )


def test_snapshot_rejects_future_account_mark_observation_time() -> None:
    as_of = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    account = _incomplete_account_with_valuation_evidence(
        as_of,
        HistoricalValuationEvidence(
            instrument_id="NSE:TCS",
            mark_price=Decimal("100"),
            source="test",
            observed_at=as_of + timedelta(seconds=1),
            selected_at=as_of,
            unavailable=False,
        ),
    )
    with pytest.raises(TemporalIntegrityError, match="valuation mark"):
        build_engine_snapshot(
            EngineEvidenceAdapter(
                positions=EvidenceCollection.known(()),
                orders=EvidenceCollection.known(()),
                account_state=account,
                account_reason=account.issue,
            ),
            as_of=as_of,
        )


def test_snapshot_rejects_future_account_valuation_selection_time() -> None:
    as_of = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    account = _incomplete_account_with_valuation_evidence(
        as_of,
        HistoricalValuationEvidence(
            instrument_id="NSE:TCS",
            mark_price=Decimal("100"),
            source="test",
            observed_at=as_of,
            selected_at=as_of + timedelta(seconds=1),
            unavailable=False,
        ),
    )
    with pytest.raises(TemporalIntegrityError, match="valuation selection"):
        build_engine_snapshot(
            EngineEvidenceAdapter(
                positions=EvidenceCollection.known(()),
                orders=EvidenceCollection.known(()),
                account_state=account,
                account_reason=account.issue,
            ),
            as_of=as_of,
        )


def test_context_snapshot_and_parameter_views_are_frozen() -> None:
    context = StrategyContext(_event(), _ir())

    with pytest.raises(FrozenInstanceError):
        context.as_of = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        context.engine.as_of = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        context.engine.positions.items = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        context.params.parameters = ()  # type: ignore[misc]

    assert isinstance(context.history, tuple)
    assert isinstance(context.engine.positions.items, tuple)
    assert isinstance(context.ir.parameters, tuple)
    assert context.params.parameters is context.ir.parameters


def test_active_order_fact_retains_unknown_and_drops_canonical_terminal() -> None:
    as_of = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    common = {
        "client_order_id": "order-1",
        "instrument": _instrument(),
        "order_quantity": Decimal("1"),
        "filled_quantity": Decimal("0"),
        "created_at": as_of,
        "evidence_time": as_of,
    }

    unresolved = active_order_fact(status=OrderStatus.UNKNOWN, **common)
    accepted = active_order_fact(status=OrderStatus.ACCEPTED, **common)
    terminal = active_order_fact(status=OrderStatus.FILLED, **common)

    assert unresolved is not None
    assert unresolved.status is OrderStatus.UNKNOWN
    assert accepted is not None
    assert terminal is None


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


def test_unknown_order_fact_does_not_fabricate_filled_or_remaining_quantity() -> None:
    as_of = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    fact = active_order_fact(
        client_order_id="unknown-order",
        instrument=_instrument(),
        status=OrderStatus.UNKNOWN,
        order_quantity=Decimal("2"),
        filled_quantity=None,
        created_at=as_of,
        evidence_time=as_of,
        effective_at=as_of,
    )

    assert fact is not None
    assert fact.status is OrderStatus.UNKNOWN
    assert fact.filled_quantity is None
    assert fact.remaining_quantity is None


def test_snapshot_rejects_future_effective_order_time_when_availability_is_current() -> None:
    as_of = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    future_fact = OpenOrderFact(
        client_order_id="future-effective-order",
        instrument=_instrument(),
        status=OrderStatus.ACCEPTED,
        order_quantity=Decimal("1"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("1"),
        created_at=as_of,
        evidence_time=as_of,
        effective_at=as_of + timedelta(seconds=1),
    )
    with pytest.raises(TemporalIntegrityError, match="order effective evidence"):
        build_engine_snapshot(
            _adapter(orders=EvidenceCollection.known((future_fact,))),
            as_of=as_of,
        )


def test_snapshot_rejects_future_position_availability_time() -> None:
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
        effective_at=as_of,
        evidence_time=as_of + timedelta(seconds=1),
    )
    with pytest.raises(TemporalIntegrityError, match="availability"):
        build_engine_snapshot(
            _adapter(positions=EvidenceCollection.known((fact,))),
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
    history = prior_candle_history(candles, instrument=_instrument(), as_of=as_of, limit=2)
    assert history == candles[1:3]
    assert prior_candle_history(candles, instrument=_instrument(), as_of=as_of, limit=0) == ()


def test_history_sorts_observations_before_applying_recent_window() -> None:
    as_of = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)
    oldest = _candle(as_of - timedelta(minutes=4))
    newest = _candle(as_of - timedelta(minutes=1))
    middle = _candle(as_of - timedelta(minutes=2))

    history = prior_candle_history(
        (oldest, newest, middle),
        instrument=_instrument(),
        as_of=as_of,
        limit=2,
    )

    assert history == (middle, newest)


def test_context_rejects_event_after_as_of() -> None:
    as_of = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    future_event = _event(as_of + timedelta(minutes=1))

    with pytest.raises(ValueError, match="event timestamp must not be later than context as_of"):
        StrategyContext(future_event, _ir(), as_of=as_of)


def test_context_rejects_nonprior_or_cross_instrument_history() -> None:
    instant = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    future = _candle(instant)
    other = _candle(instant - timedelta(minutes=1), _instrument("INFY"))
    with pytest.raises(ValueError, match="strictly prior"):
        StrategyContext(_event(instant), _ir(), history=(future,))
    with pytest.raises(ValueError, match="event instrument"):
        StrategyContext(_event(instant), _ir(), history=(other,))
