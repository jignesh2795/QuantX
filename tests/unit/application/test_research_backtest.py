from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.application.backtest import DeterministicBacktestService
from quantx.application.research_backtest import ResearchBacktestApplicationService
from quantx.application.research_run import ResearchRunApplicationService
from quantx.domain.clock import FixedClock
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.instruments import Instrument, MarketContext, MarketFamily, MarketRegion
from quantx.domain.market_data import Quote
from quantx.domain.strategy import SignalAction, StrategyResult, StrategySignal, StrategyId
from quantx.domain.value_objects import InstrumentId, Money
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.research.result import ResearchRunSpec, ResultQuality
from quantx.research.run import ResearchRunState
from quantx.research.storage import InMemoryResearchRunRepository


def _instrument() -> Instrument:
    market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        "EQUITY",
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


def _series(dataset_id: str = "nse-eq") -> HistoricalDataSeries:
    instrument = _instrument().instrument_id
    quote = Quote(
        instrument=instrument,
        timestamp=datetime(2026, 1, 1, 9, 15, tzinfo=UTC),
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    return HistoricalDataSeries(
        (
            HistoricalObservation(
                quote,
                "test",
                "1",
                0,
                dataset_id=dataset_id,
            ),
        )
    )


def _spec(dataset_id: str = "nse-eq") -> ResearchRunSpec:
    return ResearchRunSpec(
        run_id="run-backtest-1",
        dataset_id=dataset_id,
        dataset_version="1",
        instrument_master_version="instrument-v1",
        market_rule_version="rules-v1",
        execution_model_version="paper-v1",
        simulation_profile="default",
        code_revision="code-v1",
        configuration_revision="config-v1",
        random_seed=7,
    )


def _strategy(frame):
    signal = StrategySignal(
        StrategyId("bound-strategy"),
        "1",
        frame.observation.instrument,
        SignalAction.HOLD,
        1.0,
        generated_at=frame.observation.timestamp,
    )
    return StrategyResult(signal)


def _service(
    repository: InMemoryResearchRunRepository,
    clock: FixedClock,
) -> ResearchBacktestApplicationService:
    lifecycle = ResearchRunApplicationService(repository=repository, clock=clock)
    backtest = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),))
    )
    return ResearchBacktestApplicationService(
        lifecycle=lifecycle,
        backtest=backtest,
        clock=clock,
    )


def test_research_backtest_binds_real_backtest_to_durable_run() -> None:
    repository = InMemoryResearchRunRepository()
    clock = FixedClock(datetime(2026, 10, 6, 10, 0, tzinfo=UTC))
    service = _service(repository, clock)

    execution = service.execute(
        _spec(),
        series=_series(),
        strategy=_strategy,
        financial_state=_financial_state(),
    )

    assert execution.run.state is ResearchRunState.COMPLETED
    assert execution.result.spec.run_id == "run-backtest-1"
    assert execution.result.provenance == _spec().to_provenance()
    assert execution.result.quality is ResultQuality.COMPLETE_WITH_DETERMINISTIC_DERIVATIONS
    assert execution.result.metric("step_count") == Decimal("1")
    assert execution.result.metric("receipt_count") == Decimal("0")
    assert execution.result.metric("executed_count") == Decimal("0")
    assert execution.result.metric("rejected_count") == Decimal("0")
    assert execution.result.time_range_start == "2026-01-01T09:15:00+00:00"
    assert execution.result.time_range_end == "2026-01-01T09:15:00+00:00"

    stored = repository.get_run("run-backtest-1")
    assert stored == execution.run
    assert stored.result_id == execution.result.result_id
    assert stored.provenance_fingerprint == execution.result.fingerprint


def test_research_backtest_passes_declared_provenance_into_backtest() -> None:
    repository = InMemoryResearchRunRepository()
    clock = FixedClock(datetime(2026, 10, 6, 10, 0, tzinfo=UTC))
    service = _service(repository, clock)

    with pytest.raises(ValueError, match="dataset_id"):
        service.execute(
            _spec("declared-dataset"),
            series=_series("observed-dataset"),
            strategy=_strategy,
            financial_state=_financial_state(),
        )

    stored = repository.get_run("run-backtest-1")
    assert stored is not None
    assert stored.state is ResearchRunState.FAILED
    assert stored.result_id is None
    assert stored.failure_reason is not None
    assert "dataset_id" in stored.failure_reason
