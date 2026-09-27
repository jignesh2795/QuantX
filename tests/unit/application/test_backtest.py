from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quantx.application.backtest import BacktestDisposition, DeterministicBacktestService
from quantx.domain.accounts import AccountId
from quantx.domain.deployment import ExecutionContext, ExecutionMode, PortfolioId, StrategyDeploymentId
from quantx.domain.enums import AssetClass, OrderSide
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instruments import Instrument, MarketContext, MarketFamily, MarketRegion
from quantx.domain.market_data import Quote
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyContext
from quantx.domain.strategy import SignalAction, StrategyResult, StrategySignal, StrategyId
from quantx.domain.value_objects import InstrumentId, Money
from quantx.research.data import HistoricalDataSeries, HistoricalObservation


def _instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        market,
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _financial_state() -> AccountFinancialState:
    return AccountFinancialState(
        capital_source=CapitalSourceType.BACKTEST_CONFIGURED,
        cash_balance=Money(Decimal("1000"), "INR"),
        available_cash=Money(Decimal("1000"), "INR"),
        blocked_cash=Money(Decimal("0"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
        margin_available=Money(Decimal("1000"), "INR"),
        buying_power=Money(Decimal("1000"), "INR"),
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=_instrument().market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )


def _series() -> HistoricalDataSeries:
    instrument = _instrument().instrument_id
    first = Quote(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc),
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    second = Quote(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 9, 16, tzinfo=timezone.utc),
        bid=Decimal("101"),
        ask=Decimal("102"),
        last=Decimal("101"),
    )
    return HistoricalDataSeries(
        (
            HistoricalObservation(first, "test", "1", 0),
            HistoricalObservation(second, "test", "1", 1),
        )
    )


def test_backtest_composes_replay_strategy_risk_policy_and_paper_execution() -> None:
    instrument = _instrument()
    context = _context()

    def strategy(frame):
        if frame.index == 0:
            signal = StrategySignal(
                StrategyId("buy-once"),
                "1",
                instrument.instrument_id,
                SignalAction.BUY,
                1.0,
                generated_at=frame.observation.timestamp,
            )
            intent = TradeIntent(
                instrument=instrument.instrument_id,
                side=OrderSide.BUY,
                quantity=Decimal("1"),
                execution_context=context,
                strategy_id="buy-once",
                strategy_version="1",
            )
            return StrategyResult(signal, intent)

        signal = StrategySignal(
            StrategyId("buy-once"),
            "1",
            instrument.instrument_id,
            SignalAction.HOLD,
            1.0,
            generated_at=frame.observation.timestamp,
        )
        return StrategyResult(signal, None)

    result = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=strategy,
        financial_state=_financial_state(),
    )

    assert result.executed_count == 1
    assert result.rejected_count == 0
    assert len(result.receipts) == 1
    assert result.receipts[0].fills[0].price == Decimal("100")
    assert result.receipts[0].executed_at == datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc)
    assert result.ledger[0].quantity == Decimal("1")
    assert result.steps[1].disposition is BacktestDisposition.NO_ACTION


def test_backtest_blocks_risk_rejected_intent_without_execution() -> None:
    instrument = _instrument()
    context = _context()

    def strategy(_frame):
        signal = StrategySignal(
            StrategyId("too-large"),
            "1",
            instrument.instrument_id,
            SignalAction.BUY,
            1.0,
            generated_at=datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc),
        )
        intent = TradeIntent(
            instrument=instrument.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            required_margin=Decimal("2000"),
            execution_context=context,
            strategy_id="too-large",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    result = DeterministicBacktestService(
        instrument_registry=__import__("quantx.domain.instrument_registry", fromlist=["InMemoryInstrumentRegistry"]).InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=strategy,
        financial_state=_financial_state(),
    )

    assert result.executed_count == 0
    assert all(step.disposition is BacktestDisposition.RISK_REJECTED for step in result.steps)
    assert result.receipts == ()


def test_backtest_blocks_policy_rejected_intent() -> None:
    instrument = _instrument()
    context = _context()

    def strategy(_frame):
        signal = StrategySignal(
            StrategyId("capability-gated"),
            "1",
            instrument.instrument_id,
            SignalAction.BUY,
            1.0,
            generated_at=datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc),
        )
        intent = TradeIntent(
            instrument=instrument.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            required_capabilities=frozenset({"LIVE_ONLY_CAPABILITY"}),
            execution_context=context,
            strategy_id="capability-gated",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    result = DeterministicBacktestService(
        instrument_registry=__import__("quantx.domain.instrument_registry", fromlist=["InMemoryInstrumentRegistry"]).InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=strategy,
        financial_state=_financial_state(),
        policy_context=PolicyContext(),
    )

    assert result.executed_count == 0
    assert all(step.disposition is BacktestDisposition.POLICY_REJECTED for step in result.steps)


def test_backtest_blocks_intent_when_canonical_market_does_not_match() -> None:
    instrument = _instrument()
    wrong_market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN")
    wrong_context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=wrong_market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )

    def strategy(frame):
        signal = StrategySignal(
            StrategyId("bad-market"),
            "1",
            instrument.instrument_id,
            SignalAction.BUY,
            1.0,
            generated_at=frame.observation.timestamp,
        )
        intent = TradeIntent(
            instrument=instrument.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            execution_context=wrong_context,
            strategy_id="bad-market",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    result = DeterministicBacktestService(
        instrument_registry=__import__("quantx.domain.instrument_registry", fromlist=["InMemoryInstrumentRegistry"]).InMemoryInstrumentRegistry((instrument,))
    ).run(
        series=_series(),
        strategy=strategy,
        financial_state=_financial_state(),
    )

    assert all(step.disposition is BacktestDisposition.BLOCKED for step in result.steps)
