from datetime import UTC, datetime
from decimal import Decimal

from quantx.application.backtest import (
    BacktestDisposition,
    DeterministicBacktestService,
)
from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.market_data import Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyContext
from quantx.domain.strategy import (
    SignalAction,
    StrategyId,
    StrategyResult,
    StrategySignal,
)
from quantx.domain.value_objects import InstrumentId, Money
from quantx.india import IndianExchange, IndianInstrumentSpec, IndianSegment
from quantx.research.data import HistoricalDataSeries, HistoricalObservation


def test_indian_nse_spec_flows_through_registry_and_deterministic_backtest() -> None:
    spec = IndianInstrumentSpec(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        exchange=IndianExchange.NSE,
        segment=IndianSegment.EQUITY,
    )
    instrument = spec.to_instrument()
    registry = InMemoryInstrumentRegistry((instrument,))

    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )
    timestamp = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
    series = HistoricalDataSeries(
        (
            HistoricalObservation(
                Quote(
                    instrument=spec.instrument_id,
                    timestamp=timestamp,
                    bid=Decimal("99"),
                    ask=Decimal("100"),
                    last=Decimal("100"),
                ),
                "india-test",
                "1",
                0,
            ),
        )
    )

    def strategy(frame):
        signal = StrategySignal(
            StrategyId("india-tcs"),
            "1",
            spec.instrument_id,
            SignalAction.BUY,
            1.0,
            generated_at=frame.observation.timestamp,
        )
        intent = TradeIntent(
            instrument=spec.instrument_id,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            execution_context=context,
            strategy_id="india-tcs",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    result = DeterministicBacktestService(instrument_registry=registry).run(
        series=series,
        strategy=strategy,
        financial_state=AccountFinancialState(
            capital_source=CapitalSourceType.BACKTEST_CONFIGURED,
            cash_balance=Money(Decimal("1000"), "INR"),
            available_cash=Money(Decimal("1000"), "INR"),
            blocked_cash=Money(Decimal("0"), "INR"),
            margin_used=Money(Decimal("0"), "INR"),
            margin_available=Money(Decimal("1000"), "INR"),
            buying_power=Money(Decimal("1000"), "INR"),
        ),
        policy_context=PolicyContext(),
    )

    assert result.executed_count == 1
    assert result.steps[0].disposition is BacktestDisposition.EXECUTED
    assert result.receipts[0].fills[0].instrument == spec.instrument_id
