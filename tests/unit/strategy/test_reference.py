from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.enums import OrderStatus
from quantx.domain.market_data import MarketDataEvent, MarketDataType, Quote
from quantx.domain.strategy import SignalAction, StrategyDefinition, StrategyId
from quantx.domain.value_objects import InstrumentId
from quantx.execution.accounting import PositionLedgerEntry
from quantx.strategy.compiler import StrategyCompiler
from quantx.strategy.context import StrategyContext
from quantx.strategy.engine_snapshot import (
    EngineEvidenceAdapter,
    EngineStateSnapshot,
    EvidenceAvailability,
    EvidenceCollection,
    OpenOrderFact,
    PositionFact,
    build_engine_snapshot,
)
from quantx.strategy.ir import StrategyIR
from quantx.strategy.reference import BuyAndHoldStrategy, BuyThenCloseStrategy


def _event(symbol: str = "TCS") -> MarketDataEvent:
    instrument = InstrumentId("NSE", symbol)
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    return MarketDataEvent(
        MarketDataType.QUOTE,
        timestamp,
        instrument,
        Quote(instrument, timestamp, bid=Decimal("100"), ask=Decimal("101")),
    )


def _ir(strategy_id: str = "buy-and-hold", quantity: str | None = "2") -> StrategyIR:
    parameters = {} if quantity is None else {"quantity": quantity}
    definition = StrategyDefinition(
        StrategyId(strategy_id),
        "1",
        strategy_id,
        parameters=parameters,
    )
    return StrategyCompiler.compile(definition)


def _known_empty_engine(event: MarketDataEvent) -> EngineStateSnapshot:
    adapter = EngineEvidenceAdapter(
        positions=EvidenceCollection.known(()),
        orders=EvidenceCollection.known(()),
        account_state=None,
        account_reason="test provides no account-state tracker",
    )
    return build_engine_snapshot(adapter, as_of=event.timestamp)


def _context(
    strategy_id: str = "buy-and-hold",
    quantity: str | None = "2",
    symbol: str = "TCS",
    engine: EngineStateSnapshot | None = None,
) -> StrategyContext:
    event = _event(symbol)
    snapshot = engine if engine is not None else _known_empty_engine(event)
    return StrategyContext(event, _ir(strategy_id, quantity), engine=snapshot)


def _position_fact(symbol: str = "TCS", quantity: str = "2") -> PositionFact:
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    return PositionFact.from_ledger_entry(
        PositionLedgerEntry(
            instrument=InstrumentId("NSE", symbol),
            quantity=Decimal(quantity),
            average_price=Decimal("100"),
            realized_pnl=Decimal("0"),
            fees=Decimal("0"),
        ),
        effective_at=instant,
    )


def _order_fact(
    symbol: str = "TCS",
    status: OrderStatus = OrderStatus.ACCEPTED,
    order_id: str = "order-1",
) -> OpenOrderFact:
    instant = datetime(2026, 1, 1, tzinfo=UTC)
    return OpenOrderFact(
        client_order_id=order_id,
        instrument=InstrumentId("NSE", symbol),
        status=status,
        order_quantity=Decimal("2"),
        filled_quantity=Decimal("0"),
        remaining_quantity=Decimal("2"),
        created_at=instant,
        evidence_time=instant,
    )


def _engine_with(
    event: MarketDataEvent,
    positions: tuple[PositionFact, ...] = (),
    orders: tuple[OpenOrderFact, ...] = (),
    positions_availability: EvidenceAvailability = EvidenceAvailability.AVAILABLE,
    orders_availability: EvidenceAvailability = EvidenceAvailability.AVAILABLE,
) -> EngineStateSnapshot:
    adapter = EngineEvidenceAdapter(
        positions=EvidenceCollection(
            items=positions,
            availability=positions_availability,
            reason=None
            if positions_availability is EvidenceAvailability.AVAILABLE
            else "test withholds position evidence",
        ),
        orders=EvidenceCollection(
            items=orders,
            availability=orders_availability,
            reason=None
            if orders_availability is EvidenceAvailability.AVAILABLE
            else "test withholds order evidence",
        ),
        account_state=None,
        account_reason="test provides no account-state tracker",
    )
    return build_engine_snapshot(adapter, as_of=event.timestamp)


def _context_with_engine(event: MarketDataEvent, engine: EngineStateSnapshot) -> StrategyContext:
    return StrategyContext(event, _ir(), engine=engine)


def test_buy_and_hold_buys_once_with_known_empty_inventories() -> None:
    result = BuyAndHoldStrategy().on_market_data(_context())

    assert result.signal.action is SignalAction.BUY
    assert result.intent is not None
    assert result.intent.quantity == Decimal("2")
    assert result.intent.strategy_id == "buy-and-hold"
    assert result.intent.strategy_version == "1"


def test_buy_and_hold_holds_for_existing_nonzero_position() -> None:
    event = _event()
    engine = _engine_with(event, positions=(_position_fact(),))
    result = BuyAndHoldStrategy().on_market_data(_context_with_engine(event, engine))

    assert result.signal.action is SignalAction.HOLD
    assert result.intent is None
    assert "position" in result.signal.reason


def test_buy_and_hold_holds_for_active_accepted_order() -> None:
    event = _event()
    engine = _engine_with(event, orders=(_order_fact(),))
    result = BuyAndHoldStrategy().on_market_data(_context_with_engine(event, engine))

    assert result.signal.action is SignalAction.HOLD
    assert result.intent is None
    assert "order" in result.signal.reason


def test_buy_and_hold_holds_for_unresolved_unknown_order() -> None:
    event = _event()
    engine = _engine_with(event, orders=(_order_fact(status=OrderStatus.UNKNOWN),))
    result = BuyAndHoldStrategy().on_market_data(_context_with_engine(event, engine))

    assert result.signal.action is SignalAction.HOLD
    assert result.intent is None


def test_buy_and_hold_holds_when_position_evidence_is_unavailable() -> None:
    event = _event()
    engine = _engine_with(event, positions_availability=EvidenceAvailability.UNAVAILABLE)
    result = BuyAndHoldStrategy().on_market_data(_context_with_engine(event, engine))

    assert result.signal.action is SignalAction.HOLD
    assert result.intent is None
    assert "unavailable" in result.signal.reason


def test_buy_and_hold_holds_when_order_evidence_is_incomplete() -> None:
    event = _event()
    engine = _engine_with(event, orders_availability=EvidenceAvailability.INCOMPLETE)
    result = BuyAndHoldStrategy().on_market_data(_context_with_engine(event, engine))

    assert result.signal.action is SignalAction.HOLD
    assert result.intent is None


def test_buy_and_hold_retries_after_terminal_entry_without_position() -> None:
    strategy = BuyAndHoldStrategy()
    first = strategy.on_market_data(_context())
    assert first.signal.action is SignalAction.BUY

    # A terminal entry order that produced no position leaves known-empty
    # inventories, so the stateless strategy may emit BUY again.
    second = strategy.on_market_data(_context())
    assert second.signal.action is SignalAction.BUY
    assert second.intent is not None


def test_buy_and_hold_tracks_instruments_independently() -> None:
    strategy = BuyAndHoldStrategy()

    tcs = strategy.on_market_data(_context(symbol="TCS"))
    infy = strategy.on_market_data(_context(symbol="INFY"))

    assert tcs.signal.action is SignalAction.BUY
    assert tcs.intent is not None
    assert infy.signal.action is SignalAction.BUY
    assert infy.intent is not None


def test_buy_and_hold_repeated_known_empty_evaluations_carry_no_hidden_state() -> None:
    first = BuyAndHoldStrategy().on_market_data(_context())
    second = BuyAndHoldStrategy().on_market_data(_context())

    assert first.signal.action is SignalAction.BUY
    assert second.signal.action is SignalAction.BUY
    assert first.intent is not None and second.intent is not None
    assert first.intent.quantity == second.intent.quantity


def test_buy_and_hold_uses_default_quantity_without_parameter() -> None:
    result = BuyAndHoldStrategy().on_market_data(_context(quantity=None))

    assert result.signal.action is SignalAction.BUY
    assert result.intent is not None
    assert result.intent.quantity == Decimal("1")


@pytest.mark.parametrize("quantity", ["0", "-2", "0.0"])
def test_buy_and_hold_rejects_non_positive_quantity(quantity: str) -> None:
    with pytest.raises(ValueError, match="buy-and-hold quantity must be positive"):
        BuyAndHoldStrategy().on_market_data(_context(quantity=quantity))


@pytest.mark.parametrize("quantity", ["+2", "01", " 2", "two", "1.5.2", "NaN", "Infinity", "true"])
def test_buy_and_hold_rejects_malformed_quantity(quantity: str) -> None:
    with pytest.raises(ValueError, match="quantity"):
        BuyAndHoldStrategy().on_market_data(_context(quantity=quantity))


def test_buy_and_hold_rejects_missing_event() -> None:
    event = _event()
    context = StrategyContext(
        None,  # type: ignore[arg-type]
        _ir(),
        as_of=event.timestamp,
    )
    with pytest.raises(ValueError, match="requires a market event"):
        BuyAndHoldStrategy().on_market_data(context)


def test_buy_then_close_emits_close_sell_intent() -> None:
    context = _context("buy-then-close")
    strategy = BuyThenCloseStrategy()

    entry = strategy.on_market_data(context)
    close = strategy.on_market_data(context)

    assert entry.signal.action is SignalAction.BUY
    assert entry.intent is not None
    assert close.signal.action is SignalAction.CLOSE
    assert close.intent is not None
    assert close.intent.side.value == "SELL"
    assert close.intent.quantity == Decimal("2")
