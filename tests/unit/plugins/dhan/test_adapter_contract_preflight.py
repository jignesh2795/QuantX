"""Dhan preflight contract-metadata boundary (QX-05).

The adapter never parses expiry, strike, underlying, or option type from a
trading symbol. A derivative submission must carry the canonical point-in-time
resolution whose contract matches the mapped instrument; anything else is a
deterministic local rejection proven not to have reached the broker.
"""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import (
    AssetClass,
    OrderSide,
    OrderType,
    PositionEffect,
    TimeInForce,
)
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instrument_registry import InstrumentResolution
from quantx.domain.instruments import (
    Contract,
    Instrument,
    MarketContext,
    MarketFamily,
    MarketRegion,
    OptionType,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId, ProductCode
from quantx.execution.receipts.models import ExecutionOutcome
from quantx.execution.submission_preflight import BrokerPreflightRejected
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.plugins.dhan import DhanBrokerAdapter, DhanInstrumentRef, InMemoryDhanTransport
from tests.unit._execution_request_proofs import approved_request

T0 = datetime(2026, 1, 1, tzinfo=UTC)
NOW = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
EXPIRY = datetime(2026, 12, 31, 15, 30, tzinfo=UTC)
OPTION = InstrumentId("NSE", "NIFTY26DEC25000CE")
EQUITY = InstrumentId("NSE", "TCS")
UNDERLYING = InstrumentId("NSE", "NIFTY")
PRODUCT = ProductCode("CNC")


def _option_instrument() -> Instrument:
    return Instrument(
        instrument_id=OPTION,
        symbol=OPTION.symbol,
        asset_class=AssetClass.OPTION,
        market=MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN"),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("25"),
    )


def _equity_instrument() -> Instrument:
    return Instrument(
        instrument_id=EQUITY,
        symbol=EQUITY.symbol,
        asset_class=AssetClass.EQUITY,
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def _option_contract(*, strike: str = "25000") -> Contract:
    return Contract(
        instrument_id=OPTION,
        asset_class=AssetClass.OPTION,
        underlying=UNDERLYING,
        expiry=EXPIRY,
        strike=Decimal(strike),
        option_type=OptionType.CALL,
    )


def _option_resolution(instrument: Instrument | None = None) -> InstrumentResolution:
    return InstrumentResolution(
        instrument=instrument or _option_instrument(),
        contract=_option_contract(),
        instrument_rule_version="rule-v1",
        instrument_rule_effective_from=T0,
        resolved_at=NOW,
        contract_metadata_version="contract-v1",
        contract_source="nse-bhavcopy",
        contract_effective_from=T0,
    )


def _equity_resolution() -> InstrumentResolution:
    return InstrumentResolution(
        instrument=_equity_instrument(),
        instrument_rule_version="rule-v1",
        instrument_rule_effective_from=T0,
        resolved_at=NOW,
    )


def _request(
    instrument: Instrument,
    *,
    resolution: InstrumentResolution | None = None,
) -> ApprovedExecutionRequest:
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
        market_pack_id="test-pack",
        rule_version="test-v1",
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("1"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        required_capabilities=frozenset({"ORDER_SUBMISSION"}),
        product=PRODUCT,
        position_effect=PositionEffect.OPEN,
        execution_context=context,
    )
    return approved_request(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        product=PRODUCT,
        position_effect=PositionEffect.OPEN,
        instrument_resolution=resolution,
    )


def _adapter(
    instrument: Instrument,
    transport: InMemoryDhanTransport,
) -> DhanBrokerAdapter:
    segment = "NSE_FNO" if instrument.asset_class is AssetClass.OPTION else "NSE_EQ"
    connection = BrokerConnectionRef(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        "dhan",
        segment,
    )
    return DhanBrokerAdapter(
        _connection=connection,
        _instruments={
            instrument.instrument_id: (
                instrument,
                DhanInstrumentRef(
                    security_id="35001",
                    exchange_segment=segment,
                    trading_symbol=instrument.symbol,
                ),
            )
        },
        _transport=transport,
        _submit_timeout=5.0,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
        _product_map={"CNC": "CNC"},
    )


def test_derivative_submission_requires_resolved_contract_metadata() -> None:
    transport = InMemoryDhanTransport()

    with pytest.raises(BrokerPreflightRejected, match="resolved derivative contract metadata"):
        _adapter(_option_instrument(), transport).submit(_request(_option_instrument()))

    assert not transport.submitted


def test_derivative_submission_with_resolved_contract_is_accepted() -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    request = _request(_option_instrument(), resolution=_option_resolution())

    receipt = _adapter(_option_instrument(), transport).submit(request)

    assert receipt.outcome is ExecutionOutcome.ACCEPTED
    assert transport.submitted[0].security_id == "35001"
    assert transport.submitted[0].exchange_segment == "NSE_FNO"
    assert transport.submitted[0].correlation_id


def test_derivative_submission_rejects_a_contradicting_resolved_instrument() -> None:
    transport = InMemoryDhanTransport()
    contradicted = replace(_option_instrument(), tick_size=Decimal("0.10"))
    request = _request(_option_instrument(), resolution=_option_resolution(contradicted))

    with pytest.raises(BrokerPreflightRejected, match="contradicts the mapped Dhan instrument"):
        _adapter(_option_instrument(), transport).submit(request)

    assert not transport.submitted


def test_equity_submission_without_a_resolution_is_unchanged() -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")

    receipt = _adapter(_equity_instrument(), transport).submit(_request(_equity_instrument()))

    assert receipt.outcome is ExecutionOutcome.ACCEPTED
    assert transport.submitted[0].exchange_segment == "NSE_EQ"


def test_equity_submission_with_a_non_derivative_resolution_is_accepted() -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    request = _request(_equity_instrument(), resolution=_equity_resolution())

    receipt = _adapter(_equity_instrument(), transport).submit(request)

    assert receipt.outcome is ExecutionOutcome.ACCEPTED
    assert request.instrument_resolution is not None
    assert request.instrument_resolution.contract is None
