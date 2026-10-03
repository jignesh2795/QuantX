"""Experiment-level backtest fidelity/provenance coverage.

The deterministic backtest result must state which execution evidence and
models a run actually used, using the existing research fidelity
vocabulary. Provenance inputs the backtest does not possess are never
fabricated.
"""

from datetime import UTC, datetime
from decimal import Decimal

from quantx.application.backtest import BacktestDisposition, DeterministicBacktestService
from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.instruments import Instrument, MarketContext, MarketFamily, MarketRegion
from quantx.domain.market_data import Candle, Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.strategy import SignalAction, StrategyId, StrategyResult, StrategySignal
from quantx.domain.value_objects import InstrumentId, Money
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.research.provenance import ResearchProvenance
from quantx.research.result import ResultQuality

T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
T1 = datetime(2026, 1, 1, 9, 16, tzinfo=UTC)
T2 = datetime(2026, 1, 1, 9, 17, tzinfo=UTC)

TCS = InstrumentId("NSE", "TCS")


def _instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    return Instrument(TCS, "TCS", AssetClass.EQUITY, market, "INR", Decimal("0.05"), Decimal("1"))


def _financial_state() -> AccountFinancialState:
    return AccountFinancialState(
        capital_source=CapitalSourceType.BACKTEST_CONFIGURED,
        cash_balance=Money(Decimal("100000"), "INR"),
        available_cash=Money(Decimal("100000"), "INR"),
        blocked_cash=Money(Decimal("0"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
        margin_available=Money(Decimal("100000"), "INR"),
        buying_power=Money(Decimal("100000"), "INR"),
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


def _candle(timestamp: datetime, close: Decimal) -> Candle:
    return Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=timestamp,
        open=Decimal("99"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=close,
        volume=Decimal("1000"),
    )


def _candle_series() -> HistoricalDataSeries:
    return HistoricalDataSeries(
        tuple(
            HistoricalObservation.from_candle(_candle(ts, close), "test", "v1", index)
            for index, (ts, close) in enumerate(
                ((T0, Decimal("100")), (T1, Decimal("101")), (T2, Decimal("102")))
            )
        )
    )


def _quote_series() -> HistoricalDataSeries:
    return HistoricalDataSeries(
        (
            HistoricalObservation(
                Quote(
                    instrument=TCS,
                    timestamp=T0,
                    bid=Decimal("99"),
                    ask=Decimal("100"),
                    last=Decimal("100"),
                ),
                "test",
                "1",
                0,
            ),
            HistoricalObservation(
                Quote(
                    instrument=TCS,
                    timestamp=T1,
                    bid=Decimal("101"),
                    ask=Decimal("102"),
                    last=Decimal("101"),
                ),
                "test",
                "1",
                1,
            ),
        )
    )


def _strategy(order_type: OrderType, price: Decimal | None = None):
    def strategy(frame):
        signal = StrategySignal(
            StrategyId("fidelity-check"),
            "1",
            TCS,
            SignalAction.BUY,
            1.0,
            generated_at=frame.observation.timestamp,
        )
        intent = TradeIntent(
            instrument=TCS,
            side=OrderSide.BUY,
            quantity=Decimal("1"),
            order_type=order_type,
            limit_price=price if order_type is OrderType.LIMIT else None,
            stop_price=price if order_type is OrderType.STOP else None,
            execution_context=_context(),
            strategy_id="fidelity-check",
            strategy_version="1",
        )
        return StrategyResult(signal, intent)

    return strategy


def _run(series, order_type: OrderType, price: Decimal | None = None):
    return DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    ).run(
        series=series,
        strategy=_strategy(order_type, price),
        financial_state=_financial_state(),
    )


def test_basic_bar_result_reports_model_and_evidence() -> None:
    result = _run(_candle_series(), OrderType.MARKET)

    assert result.fidelity.execution_models == ("BASIC_BAR@basic-bar-v4",)
    assert result.fidelity.evidence_types == ("CANDLE",)
    assert result.fidelity.deterministic is True
    assert result.fidelity.simulated is True
    assert result.fidelity.quality is ResultQuality.COMPLETE_WITH_DETERMINISTIC_DERIVATIONS
    assert result.fidelity.quality is not ResultQuality.COMPLETE_OBSERVED


def test_basic_bar_result_records_limitations() -> None:
    result = _run(_candle_series(), OrderType.MARKET)

    limitations = result.fidelity.limitations
    assert "fills are simulated executions, not observed broker executions" in limitations
    assert "no intrabar path is modeled" in limitations
    assert "no liquidity or depth is modeled" in result.fidelity.limitations
    assert "candle market orders fill at the observed bar close" in result.fidelity.limitations


def test_blocked_run_is_incomplete_not_complete() -> None:
    # BUY stop=1000 is never touched, so nothing is declined; use an
    # ambiguous stop instead: high touches 100 with a disconfirming close.
    ambiguous = HistoricalDataSeries(
        (
            HistoricalObservation.from_candle(
                Candle(
                    instrument=TCS,
                    timeframe="1m",
                    timestamp=T0,
                    open=Decimal("105"),
                    high=Decimal("106"),
                    low=Decimal("95"),
                    close=Decimal("97"),
                    volume=Decimal("1000"),
                ),
                "test",
                "v1",
                0,
            ),
        )
    )
    result = _run(ambiguous, OrderType.STOP, Decimal("100"))

    assert result.steps[0].disposition is BacktestDisposition.BLOCKED
    assert result.fidelity.quality is ResultQuality.INCOMPLETE
    assert result.fidelity.execution_models == ()
    assert result.fidelity.evidence_types == ("CANDLE",)


def test_quote_result_keeps_quote_semantics() -> None:
    result = _run(_quote_series(), OrderType.MARKET)

    assert result.fidelity.execution_models == ("QUOTE@paper-core-v0.3",)
    assert result.fidelity.evidence_types == ("QUOTE",)
    assert result.fidelity.quality is ResultQuality.COMPLETE_WITH_DETERMINISTIC_DERIVATIONS
    assert "BASIC_BAR" not in str(result.fidelity.execution_models)


def test_mixed_run_does_not_inherit_single_model_label() -> None:
    series = HistoricalDataSeries(
        (
            HistoricalObservation(
                Quote(
                    instrument=TCS,
                    timestamp=T0,
                    bid=Decimal("99"),
                    ask=Decimal("100"),
                    last=Decimal("100"),
                ),
                "test",
                "1",
                0,
            ),
            HistoricalObservation.from_candle(_candle(T1, Decimal("101")), "test", "v1", 1),
        )
    )
    result = _run(series, OrderType.MARKET)

    assert result.fidelity.execution_models == (
        "QUOTE@paper-core-v0.3",
        "BASIC_BAR@basic-bar-v4",
    )
    assert result.fidelity.evidence_types == ("QUOTE", "CANDLE")


def test_backtest_result_fabricates_no_provenance() -> None:
    result = _run(_candle_series(), OrderType.MARKET)

    assert not hasattr(result, "dataset_id")
    assert not hasattr(result, "code_revision")
    assert not hasattr(result.fidelity, "dataset_id")
    assert not hasattr(result.fidelity, "fingerprint")


def test_explicit_provenance_uses_existing_machinery() -> None:
    provenance = ResearchProvenance(
        dataset_id="nse-eq",
        dataset_version="v1",
        instrument_master_version="instr-v3",
        market_rule_version="rules-v2",
        execution_model_version="basic-bar-v4",
        simulation_profile="BASIC_BAR",
        code_revision="abc123",
        configuration_revision="cfg9",
    )

    assert provenance.execution_model_version == "basic-bar-v4"
    assert (
        provenance.fingerprint()
        == ResearchProvenance(
            dataset_id="nse-eq",
            dataset_version="v1",
            instrument_master_version="instr-v3",
            market_rule_version="rules-v2",
            execution_model_version="basic-bar-v4",
            simulation_profile="BASIC_BAR",
            code_revision="abc123",
            configuration_revision="cfg9",
        ).fingerprint()
    )


def test_fidelity_is_reproducible() -> None:
    first = _run(_candle_series(), OrderType.MARKET)
    second = _run(_candle_series(), OrderType.MARKET)

    assert first.fidelity == second.fidelity


def test_end_to_end_candle_to_fidelity_metadata() -> None:
    series = _candle_series()
    result = _run(series, OrderType.MARKET)

    assert [observation.snapshot.timeframe for observation in series] == ["1m", "1m", "1m"]
    assert result.executed_count == 3
    assert [fill.price for receipt in result.receipts for fill in receipt.fills] == [
        Decimal("100"),
        Decimal("101"),
        Decimal("102"),
    ]
    assert result.fidelity.execution_models == ("BASIC_BAR@basic-bar-v4",)
    assert result.fidelity.evidence_types == ("CANDLE",)
    assert all(receipt.simulated is True for receipt in result.receipts)
    assert result.ledger[0].quantity == Decimal("3")
