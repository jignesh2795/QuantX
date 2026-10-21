"""Strategy preparation binds the canonical derivative resolution (QX-05)."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeployment,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, PositionEffect
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
from quantx.domain.market_data import MarketDataEvent, MarketDataType, Quote
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import PreTradeRiskEngine, RiskContext, RiskResult
from quantx.domain.strategy import SignalAction, StrategyId, StrategyResult, StrategySignal
from quantx.domain.value_objects import InstrumentId, Money
from quantx.research.market_rules import (
    PointInTimeContractCatalog,
    PointInTimeInstrumentRegistry,
    PointInTimeInstrumentResolver,
    VersionedContractMetadata,
    VersionedInstrumentRule,
)
from quantx.strategy.deployment import StrategyExecutionDecision
from quantx.strategy.execution import StrategyExecutionPreparer

T0 = datetime(2026, 1, 1, tzinfo=UTC)
EXPIRY = datetime(2026, 12, 31, 15, 30, tzinfo=UTC)
OPTION = InstrumentId("NSE", "NIFTY26DEC25000CE")
UNDERLYING = InstrumentId("NSE", "NIFTY")


def _market() -> MarketContext:
    return MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN")


def _instrument() -> Instrument:
    return Instrument(
        instrument_id=OPTION,
        symbol=OPTION.symbol,
        asset_class=AssetClass.OPTION,
        market=_market(),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("25"),
    )


def _contract(*, strike: str = "25000") -> Contract:
    return Contract(
        instrument_id=OPTION,
        asset_class=AssetClass.OPTION,
        underlying=UNDERLYING,
        expiry=EXPIRY,
        strike=Decimal(strike),
        option_type=OptionType.CALL,
    )


def _record(
    contract: Contract,
    start: datetime,
    end: datetime | None,
    *,
    version: str,
) -> VersionedContractMetadata:
    return VersionedContractMetadata(
        contract=contract,
        effective_from=start,
        effective_to=end,
        metadata_version=version,
        source="nse-bhavcopy",
    )


def _rule() -> VersionedInstrumentRule:
    return VersionedInstrumentRule(
        instrument_id=str(OPTION),
        effective_from=T0,
        effective_to=None,
        tick_size=Decimal("0.05"),
        lot_size=Decimal("25"),
        multiplier=Decimal("1"),
        currency="INR",
        rule_version="rule-v1",
    )


def _resolver(*records: VersionedContractMetadata) -> PointInTimeInstrumentResolver:
    return PointInTimeInstrumentResolver(
        instruments=InMemoryInstrumentRegistry((_instrument(),)),
        rules=PointInTimeInstrumentRegistry((_rule(),)),
        contracts=PointInTimeContractCatalog(records),
    )


def _event(timestamp: datetime = T0) -> MarketDataEvent:
    return MarketDataEvent(
        MarketDataType.QUOTE,
        timestamp,
        OPTION,
        Quote(OPTION, timestamp, bid=Decimal("99"), ask=Decimal("100"), last=Decimal("100")),
    )


def _context() -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=_market(),
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )


def _decision(event: MarketDataEvent) -> StrategyExecutionDecision:
    deployment = StrategyDeployment(
        deployment_id=StrategyDeploymentId("deploy-1"),
        strategy_id="option-buyer",
        strategy_version="1",
        portfolio_id=PortfolioId("portfolio-1"),
        account_id=AccountId("acct-1"),
        market=_market(),
        execution_mode=ExecutionMode.PAPER,
        enabled=True,
    )
    signal = StrategySignal(
        StrategyId("option-buyer"),
        "1",
        OPTION,
        SignalAction.BUY,
        1.0,
        generated_at=event.timestamp,
    )
    intent = TradeIntent(
        instrument=OPTION,
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        required_margin=Decimal("1000"),
        position_effect=PositionEffect.OPEN,
        execution_context=_context(),
        strategy_id="option-buyer",
        strategy_version="1",
    )
    return StrategyExecutionDecision(deployment, StrategyResult(signal, intent))


def _financial_state() -> AccountFinancialState:
    return AccountFinancialState(
        CapitalSourceType.PAPER_CONFIGURED,
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


def test_preparer_binds_the_exact_resolution_to_risk_and_the_request() -> None:
    resolver = _resolver(_record(_contract(), T0, None, version="contract-v1"))
    risk = _RecordingRiskEngine()
    event = _event()

    result = StrategyExecutionPreparer(
        InMemoryInstrumentRegistry((_instrument(),)),
        risk_engine=risk,
        instrument_resolver=resolver,
    ).prepare(_decision(event), event, _financial_state())

    expected = resolver.resolve_at(OPTION, event.timestamp)
    approved = risk.contexts[0].instrument_resolution

    assert result.risk_result is not None
    assert result.risk_result.decision.value == "approve"
    assert result.request is not None
    assert approved == expected
    assert approved is not None
    # The versioned identity and provenance reach risk, not merely an equal
    # Contract value.
    assert approved.contract == expected.contract
    assert approved.contract_metadata_version == "contract-v1"
    assert approved.contract_source == "nse-bhavcopy"
    assert approved.contract_effective_from == T0
    assert approved.instrument_rule_version == "rule-v1"
    assert approved.instrument_rule_effective_from == T0
    assert approved.resolved_at == event.timestamp
    # The very same selected resolution is retained by the risk result and the
    # approved request, so the request executes the semantics risk approved.
    assert result.risk_result.instrument_resolution is approved
    assert result.request.instrument_resolution is approved
    assert result.request.order.instrument == OPTION
    # Notional/margin arithmetic is unchanged by the identity handoff.
    assert result.request.required_margin == Decimal("1000")


def test_preparer_rejects_a_derivative_without_a_resolver_before_risk() -> None:
    risk = _RecordingRiskEngine()

    with pytest.raises(ValueError, match="requires a point-in-time instrument resolver"):
        StrategyExecutionPreparer(
            InMemoryInstrumentRegistry((_instrument(),)),
            risk_engine=risk,
        ).prepare(_decision(_event()), _event(), _financial_state())

    assert risk.contexts == []


def test_preparer_never_hands_risk_a_bare_contract() -> None:
    resolver = _resolver(_record(_contract(), T0, None, version="contract-v1"))
    risk = _RecordingRiskEngine()
    event = _event()

    StrategyExecutionPreparer(
        InMemoryInstrumentRegistry((_instrument(),)),
        risk_engine=risk,
        instrument_resolver=resolver,
    ).prepare(_decision(event), event, _financial_state())

    # ``contract`` is a read-only projection of the canonical resolution: the
    # risk boundary received the resolution itself, never a second source of
    # truth for the selected contract or its version.
    context = risk.contexts[0]
    assert context.instrument_resolution is not None
    assert context.contract is context.instrument_resolution.contract
    assert context.instrument_resolution.contract_metadata_version == "contract-v1"


def test_preparer_selects_the_historical_contract_for_the_event_instant() -> None:
    later = datetime(2026, 2, 1, tzinfo=UTC)
    resolver = _resolver(
        _record(_contract(strike="25000"), T0, later, version="contract-v1"),
        _record(_contract(strike="26000"), later, None, version="contract-v2"),
    )
    event = _event(datetime(2026, 1, 5, tzinfo=UTC))

    result = StrategyExecutionPreparer(
        InMemoryInstrumentRegistry((_instrument(),)),
        instrument_resolver=resolver,
    ).prepare(_decision(event), event, _financial_state())

    assert result.request is not None
    resolution = result.request.instrument_resolution
    assert resolution is not None
    assert resolution.contract_metadata_version == "contract-v1"
    assert resolution.contract is not None
    assert resolution.contract.strike == Decimal("25000")
