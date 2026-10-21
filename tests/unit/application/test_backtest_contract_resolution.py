"""Deterministic replay binds the canonical derivative resolution (QX-05)."""

from datetime import UTC, datetime
from decimal import Decimal

from quantx.application.backtest import BacktestDisposition, DeterministicBacktestService
from quantx.domain.accounts import AccountId
from quantx.domain.clock import SimulatedClock
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, PositionEffect
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instrument_registry import InMemoryInstrumentRegistry
from quantx.domain.instruments import (
    Contract,
    Instrument,
    MarketContext,
    MarketFamily,
    MarketRegion,
    OptionType,
)
from quantx.domain.market_data import Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import PreTradeRiskEngine, RiskContext, RiskResult
from quantx.domain.strategy import SignalAction, StrategyId, StrategyResult, StrategySignal
from quantx.domain.value_objects import InstrumentId, Money
from quantx.execution.paper_engine import PaperExecutionEngine
from quantx.research.data import HistoricalDataSeries, HistoricalObservation
from quantx.research.market_rules import (
    PointInTimeContractCatalog,
    PointInTimeInstrumentRegistry,
    PointInTimeInstrumentResolver,
    VersionedContractMetadata,
    VersionedInstrumentRule,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
EXPIRY = datetime(2026, 12, 31, 15, 30, tzinfo=UTC)
OPTION = InstrumentId("NSE", "NIFTY26DEC25000CE")
UNDERLYING = InstrumentId("NSE", "NIFTY")
MARKET = MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN")


def _instrument() -> Instrument:
    return Instrument(
        instrument_id=OPTION,
        symbol=OPTION.symbol,
        asset_class=AssetClass.OPTION,
        market=MARKET,
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("25"),
    )


def _contract() -> Contract:
    return Contract(
        instrument_id=OPTION,
        asset_class=AssetClass.OPTION,
        underlying=UNDERLYING,
        expiry=EXPIRY,
        strike=Decimal("25000"),
        option_type=OptionType.CALL,
    )


def _resolver() -> PointInTimeInstrumentResolver:
    return PointInTimeInstrumentResolver(
        instruments=InMemoryInstrumentRegistry((_instrument(),)),
        rules=PointInTimeInstrumentRegistry(
            (
                VersionedInstrumentRule(
                    instrument_id=str(OPTION),
                    effective_from=T0,
                    effective_to=None,
                    tick_size=Decimal("0.05"),
                    lot_size=Decimal("25"),
                    multiplier=Decimal("1"),
                    currency="INR",
                    rule_version="rule-v1",
                ),
            )
        ),
        contracts=PointInTimeContractCatalog(
            (
                VersionedContractMetadata(
                    contract=_contract(),
                    effective_from=T0,
                    effective_to=None,
                    metadata_version="contract-v1",
                    source="nse-bhavcopy",
                ),
            )
        ),
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MARKET,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )


def _series() -> HistoricalDataSeries:
    quote = Quote(
        OPTION,
        T0,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )
    return HistoricalDataSeries(
        (HistoricalObservation(quote, "test", "1", 0, dataset_id="nse-fno"),)
    )


def _financial_state() -> AccountFinancialState:
    return AccountFinancialState(
        CapitalSourceType.BACKTEST_CONFIGURED,
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
    )


class _RecordingRiskEngine:
    def __init__(self) -> None:
        self.contexts: list[RiskContext] = []

    def evaluate(self, intent: TradeIntent, context: RiskContext) -> RiskResult:
        self.contexts.append(context)
        return PreTradeRiskEngine().evaluate(intent, context)


class _RecordingEngine:
    def __init__(self) -> None:
        self.requests: list[ApprovedExecutionRequest] = []
        self._inner = PaperExecutionEngine(clock=SimulatedClock(T0))

    @property
    def clock(self) -> SimulatedClock:
        return self._inner.clock

    def execute(self, request: ApprovedExecutionRequest, *, snapshot: object) -> object:
        self.requests.append(request)
        return self._inner.execute(request, snapshot=snapshot)  # type: ignore[arg-type]


def _strategy(frame):
    signal = StrategySignal(
        StrategyId("option-buyer"),
        "1",
        OPTION,
        SignalAction.BUY,
        1.0,
        generated_at=frame.observation.timestamp,
    )
    intent = TradeIntent(
        instrument=OPTION,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        position_effect=PositionEffect.OPEN,
        execution_context=_context(),
        strategy_id="option-buyer",
        strategy_version="1",
    )
    return StrategyResult(signal, intent)


def test_backtest_binds_resolution_to_risk_and_the_approved_request() -> None:
    resolver = _resolver()
    risk = _RecordingRiskEngine()
    execution = _RecordingEngine()
    service = DeterministicBacktestService(
        instrument_registry=InMemoryInstrumentRegistry((_instrument(),)),
        risk_engine=risk,
        execution_engine=execution,  # type: ignore[arg-type]
        instrument_resolver=resolver,
    )

    result = service.run(
        series=_series(),
        strategy=_strategy,
        financial_state=_financial_state(),
    )

    expected = resolver.resolve_at(OPTION, T0)
    approved = risk.contexts[0].instrument_resolution

    assert result.steps[0].disposition is BacktestDisposition.EXECUTED
    assert result.executed_count == 1
    assert approved == expected
    assert approved is not None
    # The historical frame's versioned identity and provenance reach risk, not
    # merely an equal Contract value, and no second lookup happens later.
    assert approved.contract == expected.contract
    assert approved.contract_metadata_version == "contract-v1"
    assert approved.contract_source == "nse-bhavcopy"
    assert approved.contract_effective_from == T0
    assert approved.instrument_rule_version == "rule-v1"
    assert approved.instrument_rule_effective_from == T0
    # The very same selected resolution is retained by the risk result and the
    # request handed to execution.
    assert result.steps[0].risk_result is not None
    assert result.steps[0].risk_result.instrument_resolution is approved
    assert execution.requests[0].instrument_resolution is approved
