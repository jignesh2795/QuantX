"""Regression tests for the Dhan-backed LIVE risk evidence source.

The source is a neutral evidence producer, not an authority. These tests pin
its fail-closed mapping: identity is verified before any other read, missing
values never become zero, unavailable books never become empty books, and
foreign or contradictory observations never become usable evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.application.live_risk import LiveRiskEvidenceField
from quantx.application.live_risk_evidence import (
    LiveRiskPositionPnlProvenance,
    LiveRiskPositionPnlUnavailableReason,
)
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import ProductCode
from quantx.plugins.dhan.models import (
    DhanFundsSnapshot,
    DhanHoldingSnapshot,
    DhanHoldingsSnapshot,
    DhanInstrumentRef,
    DhanPositionSnapshot,
    DhanPositionsSnapshot,
    DhanProfileSnapshot,
)
from quantx.plugins.dhan.risk_evidence import (
    DhanRiskEvidenceSource,
    build_dhan_risk_evidence_source,
)
from quantx.plugins.dhan.transport import DhanTransport, InMemoryDhanTransport
from tests.unit._execution_request_proofs import approved_request

OBSERVED_AT = datetime(2026, 1, 1, tzinfo=UTC)

ACCOUNT = AccountId("acct-1")
CONNECTION = BrokerConnectionId("conn-1")
CLIENT = "client-1"
SECURITY_ID = "1333"
EXCHANGE_SEGMENT = "NSE_EQ"


def _market() -> MarketContext:
    return MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def _instrument(
    *,
    symbol: str = "TCS",
    multiplier: Decimal = Decimal("1"),
) -> Instrument:
    return Instrument(
        InstrumentId("NSE", symbol),
        symbol,
        AssetClass.EQUITY,
        _market(),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
        multiplier,
    )


def _ref(
    *,
    security_id: str = SECURITY_ID,
    exchange_segment: str = EXCHANGE_SEGMENT,
    symbol: str = "TCS",
) -> DhanInstrumentRef:
    return DhanInstrumentRef(security_id, exchange_segment, symbol)


def _execution_context(instrument: Instrument | None = None) -> ExecutionContext:
    selected = instrument or _instrument()
    return ExecutionContext(
        account_id=ACCOUNT,
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=selected.market,
        broker_connection_id=CONNECTION,
        execution_mode=ExecutionMode.LIVE,
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )


def _request(
    *,
    instrument: Instrument | None = None,
    order_type: OrderType = OrderType.LIMIT,
    limit_price: Decimal | None = Decimal("100"),
) -> ApprovedExecutionRequest:
    selected = instrument or _instrument()
    context = _execution_context(selected)
    intent = TradeIntent(
        instrument=selected.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type=order_type,
        limit_price=limit_price,
        required_margin=Decimal("1000"),
        required_capabilities=frozenset({"ORDER_SUBMISSION"}),
        execution_context=context,
        product=ProductCode("CNC"),
    )
    return approved_request(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        required_margin=Decimal("1000"),
        product=ProductCode("CNC"),
    )


def _position(
    *,
    security_id: str = SECURITY_ID,
    exchange_segment: str = EXCHANGE_SEGMENT,
    net_quantity: Decimal = Decimal("10"),
    average_price: Decimal | None = Decimal("100"),
    client_id: str | None = CLIENT,
    multiplier: Decimal | None = None,
    product_type: str | None = None,
    position_type: str | None = None,
    realized_profit: Decimal | None = None,
    unrealized_profit: Decimal | None = None,
) -> DhanPositionSnapshot:
    return DhanPositionSnapshot(
        security_id=security_id,
        exchange_segment=exchange_segment,
        net_quantity=net_quantity,
        average_price=average_price,
        client_id=client_id,
        product_type=product_type,
        position_type=position_type,
        buy_quantity=net_quantity if net_quantity >= 0 else Decimal("0"),
        sell_quantity=Decimal("0") if net_quantity >= 0 else -net_quantity,
        realized_profit=realized_profit,
        unrealized_profit=unrealized_profit,
        multiplier=multiplier,
    )


def _transport(**overrides) -> InMemoryDhanTransport:
    values: dict = {
        "profile_client_id": CLIENT,
        "funds_client_id": CLIENT,
        "funds_sod_limit": Decimal("10000"),
        "funds_available_balance": Decimal("5000"),
        "funds_utilized_amount": Decimal("1200"),
        "funds_blocked_payout_amount": Decimal("0"),
        "position_snapshots": (_position(),),
        "holding_snapshots": (),
    }
    values.update(overrides)
    return InMemoryDhanTransport(**values)


def _source(
    transport: DhanTransport | None = None,
    *,
    instruments: tuple[tuple[Instrument, DhanInstrumentRef], ...] | None = None,
    client_id: str = CLIENT,
    read_timeout: float = 5.0,
    account_id: AccountId = ACCOUNT,
    connection_id: BrokerConnectionId = CONNECTION,
) -> DhanRiskEvidenceSource:
    return DhanRiskEvidenceSource(
        transport=transport or _transport(),
        account_id=account_id,
        broker_connection_id=connection_id,
        broker_client_id=client_id,
        instruments=instruments or ((_instrument(), _ref()),),
        read_timeout=read_timeout,
    )


def _field_names(evidence) -> set[str]:
    return {field.value for field in evidence.unavailable_fields}


class _RecordingTransport(InMemoryDhanTransport):
    """In-memory transport that records calls and can fail a named observation."""

    def __init__(self, *, fail: str | None = None, **overrides) -> None:
        super().__init__(**overrides)
        self.calls: list[tuple[str, float]] = []
        self._fail = fail

    def _record(self, name: str, timeout: float) -> None:
        self.calls.append((name, timeout))
        if self._fail == name:
            raise RuntimeError(f"{name} transport failure")

    def profile(self, *, timeout: float = 10.0) -> DhanProfileSnapshot:
        self._record("profile", timeout)
        return super().profile(timeout=timeout)

    def fund_limits(self, *, timeout: float = 10.0) -> DhanFundsSnapshot:
        self._record("fund_limits", timeout)
        return super().fund_limits(timeout=timeout)

    def positions(self, *, timeout: float = 10.0) -> DhanPositionsSnapshot:
        self._record("positions", timeout)
        return super().positions(timeout=timeout)

    def holdings(self, *, timeout: float = 10.0) -> DhanHoldingsSnapshot:
        self._record("holdings", timeout)
        return super().holdings(timeout=timeout)


class _TimedTransport(InMemoryDhanTransport):
    """In-memory transport with distinct observation instants per endpoint."""

    def __init__(
        self,
        *,
        profile_at: datetime,
        funds_at: datetime,
        positions_at: datetime,
        holdings_at: datetime,
        **overrides,
    ) -> None:
        super().__init__(**overrides)
        self._profile_at = profile_at
        self._funds_at = funds_at
        self._positions_at = positions_at
        self._holdings_at = holdings_at

    def profile(self, *, timeout: float = 10.0) -> DhanProfileSnapshot:
        base = super().profile(timeout=timeout)
        return DhanProfileSnapshot(
            observed_at=self._profile_at,
            client_id=base.client_id,
            available=base.available,
            message=base.message,
        )

    def fund_limits(self, *, timeout: float = 10.0) -> DhanFundsSnapshot:
        base = super().fund_limits(timeout=timeout)
        return DhanFundsSnapshot(
            observed_at=self._funds_at,
            available_balance=base.available_balance,
            utilized_amount=base.utilized_amount,
            available=base.available,
            message=base.message,
            client_id=base.client_id,
            sod_limit=base.sod_limit,
            collateral_amount=base.collateral_amount,
            receivable_amount=base.receivable_amount,
            blocked_payout_amount=base.blocked_payout_amount,
            withdrawable_balance=base.withdrawable_balance,
        )

    def positions(self, *, timeout: float = 10.0) -> DhanPositionsSnapshot:
        base = super().positions(timeout=timeout)
        return DhanPositionsSnapshot(
            observed_at=self._positions_at,
            positions=base.positions,
            available=base.available,
            message=base.message,
        )

    def holdings(self, *, timeout: float = 10.0) -> DhanHoldingsSnapshot:
        base = super().holdings(timeout=timeout)
        return DhanHoldingsSnapshot(
            observed_at=self._holdings_at,
            holdings=base.holdings,
            available=base.available,
            message=base.message,
        )


def test_source_declares_only_the_fields_dhan_can_actually_supply() -> None:
    source = _source()

    supported = {field.value for field in source.supported_fields}
    assert supported == {
        "cash_balance",
        "available_cash",
        "blocked_cash",
        "margin_used",
        "margin_available",
        "buying_power",
        "current_position_exposure",
        "current_instrument_exposure",
        "current_portfolio_exposure",
    }
    for unsupported in ("daily_pnl", "equity", "high_water_mark"):
        assert unsupported not in supported


def test_source_rejects_an_unusable_transport() -> None:
    with pytest.raises(ValueError, match="DhanTransport"):
        DhanRiskEvidenceSource(
            transport=object(),  # type: ignore[arg-type]
            account_id=ACCOUNT,
            broker_connection_id=CONNECTION,
            broker_client_id=CLIENT,
            instruments=((_instrument(), _ref()),),
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"account_id": "acct"}, "AccountId"),
        ({"broker_connection_id": "conn"}, "BrokerConnectionId"),
        ({"broker_client_id": ""}, "client id"),
        ({"broker_client_id": "   "}, "client id"),
        ({"instruments": ()}, "at least one instrument"),
        ({"read_timeout": 0}, "positive number"),
        ({"read_timeout": -1.0}, "positive number"),
        ({"read_timeout": True}, "positive number"),
        ({"read_timeout": "5"}, "positive number"),
    ],
)
def test_source_rejects_invalid_construction_inputs(overrides, message) -> None:
    values: dict = {
        "transport": _transport(),
        "account_id": ACCOUNT,
        "broker_connection_id": CONNECTION,
        "broker_client_id": CLIENT,
        "instruments": ((_instrument(), _ref()),),
        "read_timeout": 5.0,
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        DhanRiskEvidenceSource(**values)


def test_source_rejects_duplicate_instrument_ids() -> None:
    instrument = _instrument()

    with pytest.raises(ValueError, match="duplicate id"):
        _source(
            instruments=(
                (instrument, _ref(security_id="1333")),
                (instrument, _ref(security_id="1334")),
            )
        )


def test_source_rejects_an_ambiguous_position_mapping() -> None:
    with pytest.raises(ValueError, match="ambiguous position"):
        _source(
            instruments=(
                (_instrument(symbol="TCS"), _ref(symbol="TCS")),
                (_instrument(symbol="INFY"), _ref(symbol="INFY")),
            )
        )


def test_source_rejects_an_ambiguous_holding_mapping() -> None:
    with pytest.raises(ValueError, match="ambiguous holding"):
        _source(
            instruments=(
                (_instrument(symbol="TCS"), _ref(exchange_segment="NSE_EQ", symbol="TCS")),
                (_instrument(symbol="INFY"), _ref(exchange_segment="BSE_EQ", symbol="INFY")),
            )
        )


def test_source_strips_the_configured_client_id() -> None:
    source = _source(client_id="  client-1  ")

    assert source.broker_client_id == CLIENT


def test_collect_maps_complete_funds_positions_and_identity() -> None:
    transport = _transport()
    source = _source(transport)

    evidence = source.collect(_request())

    assert evidence.message == "Dhan risk evidence collected"
    assert evidence.source_id == "dhan-risk-evidence-v1"
    assert evidence.broker_client_id == CLIENT
    assert evidence.account_id == ACCOUNT
    assert evidence.broker_connection_id == CONNECTION
    assert evidence.transport is transport
    assert evidence.identity_observed_at == OBSERVED_AT
    assert evidence.context is not None
    assert evidence.snapshot is not None
    assert evidence.contradictions == ()

    financial = evidence.context.financial_state
    assert financial.cash_balance.amount == Decimal("10000")
    assert financial.available_cash.amount == Decimal("5000")
    assert financial.blocked_cash.amount == Decimal("0")
    assert financial.margin_used.amount == Decimal("1200")
    assert financial.margin_available.amount == Decimal("5000")
    assert financial.buying_power.amount == Decimal("5000")
    assert evidence.snapshot.available_margin == Decimal("5000")
    assert evidence.snapshot.required_margin == Decimal("1000")
    assert evidence.snapshot.current_position_exposure == Decimal("1000")
    assert evidence.snapshot.current_instrument_exposure == Decimal("1000")
    assert evidence.snapshot.current_portfolio_exposure == Decimal("1000")
    assert evidence.snapshot.daily_pnl is None
    assert evidence.snapshot.equity is None
    assert evidence.snapshot.high_water_mark is None
    assert evidence.snapshot.observed_at == OBSERVED_AT

    assert _field_names(evidence) == {"daily_pnl", "equity", "high_water_mark"}
    assert {
        field.value: observation.value for field, observation in evidence.observations.items()
    } == {
        "cash_balance": Decimal("10000"),
        "available_cash": Decimal("5000"),
        "blocked_cash": Decimal("0"),
        "margin_used": Decimal("1200"),
        "margin_available": Decimal("5000"),
        "buying_power": Decimal("5000"),
        "current_position_exposure": Decimal("1000"),
        "current_instrument_exposure": Decimal("1000"),
        "current_portfolio_exposure": Decimal("1000"),
    }


def test_collect_verifies_profile_identity_before_reading_anything_else() -> None:
    transport = _RecordingTransport(profile_client_id="foreign-client")
    source = _source(transport)

    evidence = source.collect(_request())

    assert [name for name, _ in transport.calls] == ["profile"]
    assert evidence.context is None
    assert evidence.snapshot is None
    assert evidence.identity_observed_at == OBSERVED_AT
    assert evidence.broker_client_id == "foreign-client"
    assert _field_names(evidence) == {field.value for field in LiveRiskEvidenceField}


def test_collect_passes_the_explicit_read_timeout_to_every_observation() -> None:
    transport = _RecordingTransport(profile_client_id=CLIENT)
    source = _source(transport, read_timeout=3.5)

    source.collect(_request())

    assert transport.calls == [
        ("profile", 3.5),
        ("fund_limits", 3.5),
        ("positions", 3.5),
        ("holdings", 3.5),
    ]


def test_collect_without_a_profile_identity_is_unavailable() -> None:
    source = _source(_transport(profile_client_id=None))

    evidence = source.collect(_request())

    assert evidence.context is None
    assert evidence.snapshot is None
    assert evidence.broker_client_id is None
    assert evidence.identity_observed_at == OBSERVED_AT
    assert _field_names(evidence) == {field.value for field in LiveRiskEvidenceField}


def test_collect_with_an_unavailable_profile_is_unavailable() -> None:
    source = _source(_transport(profile_available=False))

    evidence = source.collect(_request())

    assert evidence.context is None
    assert evidence.snapshot is None
    assert evidence.broker_client_id is None
    assert evidence.identity_observed_at == OBSERVED_AT


def test_collect_with_a_foreign_profile_identity_is_unavailable() -> None:
    source = _source(_transport(profile_client_id="foreign-client"))

    evidence = source.collect(_request())

    assert evidence.context is None
    assert evidence.snapshot is None
    assert evidence.broker_client_id == "foreign-client"
    assert evidence.identity_observed_at == OBSERVED_AT
    assert evidence.message == "Dhan profile identity does not match the configured client"


def test_collect_with_a_foreign_funds_identity_is_a_contradiction() -> None:
    source = _source(_transport(funds_client_id="foreign-client"))

    evidence = source.collect(_request())

    assert evidence.context is None
    assert evidence.snapshot is None
    assert "funds client identity mismatch" in evidence.contradictions
    financial_names = {
        "cash_balance",
        "available_cash",
        "blocked_cash",
        "margin_used",
        "margin_available",
        "buying_power",
    }
    assert financial_names <= _field_names(evidence)
    # The books are still mapped independently of the financial failure.
    assert "current_position_exposure" not in _field_names(evidence)


def test_collect_with_a_missing_sod_limit_keeps_the_account_state_unknown() -> None:
    source = _source(_transport(funds_sod_limit=None))

    evidence = source.collect(_request())

    assert evidence.context is None
    assert evidence.snapshot is None
    financial_names = {
        "cash_balance",
        "available_cash",
        "blocked_cash",
        "margin_used",
        "margin_available",
        "buying_power",
    }
    assert financial_names <= _field_names(evidence)
    assert not any(field.value in financial_names for field in evidence.observations)


def test_collect_preserves_observed_zero_fund_values() -> None:
    source = _source(
        _transport(
            funds_sod_limit=Decimal("0"),
            funds_available_balance=Decimal("0"),
            funds_utilized_amount=Decimal("0"),
            funds_blocked_payout_amount=Decimal("0"),
        )
    )

    evidence = source.collect(_request())

    assert evidence.context is not None
    assert evidence.context.financial_state.cash_balance.amount == Decimal("0")
    assert evidence.context.financial_state.available_cash.amount == Decimal("0")
    assert evidence.context.financial_state.blocked_cash.amount == Decimal("0")
    assert evidence.context.financial_state.margin_used.amount == Decimal("0")
    assert evidence.context.financial_state.margin_available.amount == Decimal("0")
    assert evidence.context.financial_state.buying_power.amount == Decimal("0")


def test_collect_with_a_missing_available_balance_keeps_the_account_state_unknown() -> None:
    source = _source(_transport(funds_available_balance=None))

    evidence = source.collect(_request())

    assert evidence.context is None
    assert "available_cash" in _field_names(evidence)
    assert "margin_available" in _field_names(evidence)
    assert "buying_power" in _field_names(evidence)


def test_collect_with_a_negative_fund_value_keeps_the_account_state_unknown() -> None:
    source = _source(_transport(funds_available_balance=Decimal("-1")))

    evidence = source.collect(_request())

    assert evidence.context is None
    assert "available_cash" in _field_names(evidence)


def test_collect_with_unavailable_funds_keeps_the_account_state_unknown() -> None:
    source = _source(_transport(funds_available=False))

    evidence = source.collect(_request())

    assert evidence.context is None
    assert "cash_balance" in _field_names(evidence)


def test_collect_with_unavailable_positions_keeps_exposure_unknown() -> None:
    source = _source(_transport(positions_available=False))

    evidence = source.collect(_request())

    assert evidence.context is not None
    assert evidence.snapshot is not None
    assert evidence.snapshot.current_position_exposure is None
    assert evidence.snapshot.current_instrument_exposure is None
    assert evidence.snapshot.current_portfolio_exposure is None
    assert {
        "current_position_exposure",
        "current_instrument_exposure",
        "current_portfolio_exposure",
    } <= _field_names(evidence)


def test_collect_with_unavailable_holdings_keeps_exposure_unknown() -> None:
    source = _source(_transport(holdings_available=False))

    evidence = source.collect(_request())

    assert evidence.context is not None
    assert evidence.snapshot is not None
    assert evidence.snapshot.current_position_exposure is None
    assert evidence.snapshot.current_portfolio_exposure is None


def test_collect_does_not_treat_a_missing_position_price_as_zero() -> None:
    source = _source(_transport(position_snapshots=(_position(average_price=None),)))

    evidence = source.collect(_request())

    assert evidence.context is not None
    assert evidence.snapshot is not None
    assert evidence.snapshot.current_position_exposure is None
    assert evidence.snapshot.current_instrument_exposure is None
    assert evidence.snapshot.current_portfolio_exposure is None
    assert "current_position_exposure" in _field_names(evidence)
    assert "current_portfolio_exposure" in _field_names(evidence)


def test_collect_treats_a_zero_net_position_as_observed_zero() -> None:
    source = _source(
        _transport(position_snapshots=(_position(net_quantity=Decimal("0"), average_price=None),))
    )

    evidence = source.collect(_request())

    assert evidence.snapshot is not None
    assert evidence.snapshot.current_position_exposure == Decimal("0")
    assert evidence.snapshot.current_instrument_exposure == Decimal("0")
    assert evidence.snapshot.current_portfolio_exposure == Decimal("0")
    assert "current_position_exposure" not in _field_names(evidence)


def test_collect_treats_an_absent_instrument_in_available_books_as_observed_zero() -> None:
    source = _source(_transport(position_snapshots=(), holding_snapshots=()))

    evidence = source.collect(_request())

    assert evidence.snapshot is not None
    assert evidence.snapshot.current_position_exposure == Decimal("0")
    assert evidence.snapshot.current_instrument_exposure == Decimal("0")
    assert evidence.snapshot.current_portfolio_exposure == Decimal("0")


def test_collect_with_an_unmapped_nonzero_position_keeps_portfolio_unknown() -> None:
    source = _source(
        _transport(
            position_snapshots=(
                _position(security_id="9999", exchange_segment="NSE_EQ", net_quantity=Decimal("5")),
            )
        )
    )

    evidence = source.collect(_request())

    assert evidence.snapshot is not None
    # The requested instrument is absent from the available book, so its
    # exposure is an observed zero.
    assert evidence.snapshot.current_position_exposure == Decimal("0")
    # The portfolio cannot be summed because one row has no configured mapping.
    assert evidence.snapshot.current_portfolio_exposure is None
    assert "current_portfolio_exposure" in _field_names(evidence)


def test_collect_with_an_unmapped_zero_position_keeps_portfolio_observable() -> None:
    source = _source(
        _transport(
            position_snapshots=(
                _position(
                    security_id="9999",
                    exchange_segment="NSE_EQ",
                    net_quantity=Decimal("0"),
                    average_price=None,
                ),
            )
        )
    )

    evidence = source.collect(_request())

    assert evidence.snapshot is not None
    assert evidence.snapshot.current_portfolio_exposure == Decimal("0")


def test_collect_with_an_unmapped_nonzero_holding_keeps_portfolio_unknown() -> None:
    source = _source(
        _transport(
            position_snapshots=(),
            holding_snapshots=(
                DhanHoldingSnapshot(
                    security_id="9999",
                    exchange="ALL",
                    total_quantity=Decimal("5"),
                    average_cost_price=Decimal("100"),
                ),
            ),
        )
    )

    evidence = source.collect(_request())

    assert evidence.snapshot is not None
    assert evidence.snapshot.current_position_exposure == Decimal("0")
    assert evidence.snapshot.current_portfolio_exposure is None


def test_collect_maps_a_holding_exposure_using_available_cost_basis() -> None:
    source = _source(
        _transport(
            position_snapshots=(),
            holding_snapshots=(
                DhanHoldingSnapshot(
                    security_id=SECURITY_ID,
                    exchange="ALL",
                    total_quantity=Decimal("5"),
                    dp_quantity=Decimal("5"),
                    t1_quantity=Decimal("0"),
                    available_quantity=Decimal("5"),
                    collateral_quantity=Decimal("0"),
                    average_cost_price=Decimal("200"),
                ),
            ),
        )
    )

    evidence = source.collect(_request())

    assert evidence.snapshot is not None
    assert evidence.snapshot.current_position_exposure == Decimal("1000")
    assert evidence.snapshot.current_instrument_exposure == Decimal("1000")
    assert evidence.snapshot.current_portfolio_exposure == Decimal("1000")


def test_collect_uses_the_position_multiplier_when_present() -> None:
    source = _source(
        _transport(
            position_snapshots=(
                _position(
                    net_quantity=Decimal("10"),
                    average_price=Decimal("100"),
                    multiplier=Decimal("2"),
                ),
            )
        )
    )

    evidence = source.collect(_request())

    assert evidence.snapshot is not None
    assert evidence.snapshot.current_position_exposure == Decimal("2000")


def test_collect_uses_the_instrument_multiplier_when_the_position_omits_it() -> None:
    instrument = _instrument(multiplier=Decimal("3"))
    source = _source(
        _transport(position_snapshots=(_position(multiplier=None),)),
        instruments=((instrument, _ref()),),
    )

    evidence = source.collect(_request(instrument=instrument))

    assert evidence.snapshot is not None
    assert evidence.snapshot.current_position_exposure == Decimal("3000")


def test_collect_flags_a_foreign_position_client_id_as_a_contradiction() -> None:
    source = _source(_transport(position_snapshots=(_position(client_id="foreign-client"),)))

    evidence = source.collect(_request())

    assert "position client identity mismatch" in evidence.contradictions
    # The row still maps, but the contradiction prevents admission.
    assert evidence.snapshot is not None
    assert evidence.snapshot.current_position_exposure == Decimal("1000")


def test_collect_flags_holding_available_quantity_above_total() -> None:
    source = _source(
        _transport(
            holding_snapshots=(
                DhanHoldingSnapshot(
                    security_id=SECURITY_ID,
                    exchange="ALL",
                    total_quantity=Decimal("5"),
                    available_quantity=Decimal("6"),
                    average_cost_price=Decimal("100"),
                ),
            )
        )
    )

    evidence = source.collect(_request())

    assert "holding available quantity contradiction" in evidence.contradictions


def test_collect_flags_holding_collateral_quantity_above_total() -> None:
    source = _source(
        _transport(
            holding_snapshots=(
                DhanHoldingSnapshot(
                    security_id=SECURITY_ID,
                    exchange="ALL",
                    total_quantity=Decimal("5"),
                    collateral_quantity=Decimal("6"),
                    average_cost_price=Decimal("100"),
                ),
            )
        )
    )

    evidence = source.collect(_request())

    assert "holding collateral quantity contradiction" in evidence.contradictions


def test_collect_rejects_a_request_instrument_without_a_configured_mapping() -> None:
    source = _source()

    evidence = source.collect(_request(instrument=_instrument(symbol="INFY")))

    assert evidence.context is None
    assert evidence.snapshot is None
    assert evidence.broker_client_id == CLIENT
    assert evidence.identity_observed_at == OBSERVED_AT
    assert evidence.message == "request instrument has no configured Dhan reference"


def test_collect_with_a_transport_failure_is_unavailable() -> None:
    source = _source(_RecordingTransport(profile_client_id=CLIENT, fail="fund_limits"))

    evidence = source.collect(_request())

    assert evidence.context is None
    assert evidence.snapshot is None
    assert "cash_balance" in _field_names(evidence)


def test_collect_uses_the_oldest_observation_as_the_snapshot_instant() -> None:
    profile_at = datetime(2026, 1, 1, 9, 25, tzinfo=UTC)
    funds_at = datetime(2026, 1, 1, 9, 26, tzinfo=UTC)
    positions_at = datetime(2026, 1, 1, 9, 27, tzinfo=UTC)
    holdings_at = datetime(2026, 1, 1, 9, 28, tzinfo=UTC)
    source = _source(
        _TimedTransport(
            profile_at=profile_at,
            funds_at=funds_at,
            positions_at=positions_at,
            holdings_at=holdings_at,
            profile_client_id=CLIENT,
            funds_client_id=CLIENT,
            funds_sod_limit=Decimal("10000"),
            funds_available_balance=Decimal("5000"),
            funds_utilized_amount=Decimal("1200"),
            funds_blocked_payout_amount=Decimal("0"),
            position_snapshots=(_position(),),
            holding_snapshots=(),
        )
    )

    evidence = source.collect(_request())

    assert evidence.identity_observed_at == profile_at
    assert evidence.snapshot is not None
    assert evidence.snapshot.observed_at == profile_at
    assert {observation.observed_at for observation in evidence.observations.values()} == {
        funds_at,
        positions_at,
    }


def test_collect_preserves_each_broker_reported_position_pnl_row() -> None:
    infy = _instrument(symbol="INFY")
    positions = (
        _position(
            realized_profit=Decimal("-12.50"),
            unrealized_profit=Decimal("3.25"),
            product_type="INTRADAY",
            position_type="LONG",
        ),
        _position(
            security_id="9999",
            net_quantity=Decimal("-2"),
            realized_profit=Decimal("5"),
            unrealized_profit=Decimal("-2.00"),
            product_type="CNC",
            position_type="SHORT",
        ),
    )
    source = _source(
        _transport(position_snapshots=positions),
        instruments=((_instrument(), _ref()), (infy, _ref(security_id="9999", symbol="INFY"))),
    )

    evidence = source.collect(_request())

    collection = evidence.position_pnl_collection
    assert collection.complete is True
    assert collection.observed_at == OBSERVED_AT
    assert len(collection.observations) == 2
    first, second = collection.observations
    assert first.instrument_id == _instrument().instrument_id
    assert first.net_quantity == Decimal("10")
    assert first.realized_pnl is not None
    assert first.realized_pnl.amount == Decimal("-12.50")
    assert first.realized_pnl.currency == "INR"
    assert first.unrealized_pnl is not None
    assert first.unrealized_pnl.amount == Decimal("3.25")
    assert first.provenance is LiveRiskPositionPnlProvenance.BROKER_REPORTED
    assert second.instrument_id == infy.instrument_id
    assert second.net_quantity == Decimal("-2")
    assert second.realized_pnl is not None and second.realized_pnl.amount == Decimal("5")
    assert second.unrealized_pnl is not None and second.unrealized_pnl.amount == Decimal("-2.00")
    assert first.source_position_key != second.source_position_key
    assert evidence.snapshot is not None
    assert evidence.snapshot.daily_pnl is None
    assert evidence.snapshot.equity is None
    assert evidence.snapshot.high_water_mark is None
    assert {
        LiveRiskEvidenceField.DAILY_PNL,
        LiveRiskEvidenceField.EQUITY,
        LiveRiskEvidenceField.HIGH_WATER_MARK,
    } <= set(evidence.unavailable_fields)


def test_collect_keeps_missing_position_pnl_values_unknown() -> None:
    source = _source(
        _transport(
            position_snapshots=(
                _position(realized_profit=None, unrealized_profit=Decimal("0")),
            )
        )
    )

    evidence = source.collect(_request())

    collection = evidence.position_pnl_collection
    assert collection.complete is False
    assert (
        LiveRiskPositionPnlUnavailableReason.POSITION_REALIZED_PNL_UNAVAILABLE
        in collection.unavailable_reasons
    )
    assert len(collection.observations) == 1
    assert collection.observations[0].realized_pnl is None
    assert collection.observations[0].unrealized_pnl is not None
    assert collection.observations[0].unrealized_pnl.amount == Decimal("0")


def test_collect_retains_but_marks_an_unmapped_position_pnl_row_incomplete() -> None:
    source = _source(
        _transport(
            position_snapshots=(
                _position(
                    security_id="9999",
                    realized_profit=Decimal("-5"),
                    unrealized_profit=Decimal("-4"),
                ),
            )
        )
    )

    evidence = source.collect(_request())

    collection = evidence.position_pnl_collection
    assert collection.complete is False
    assert (
        LiveRiskPositionPnlUnavailableReason.POSITION_INSTRUMENT_UNMAPPED
        in collection.unavailable_reasons
    )
    assert len(collection.observations) == 1
    assert collection.observations[0].instrument_id is None
    assert collection.observations[0].realized_pnl is not None
    assert collection.observations[0].realized_pnl.amount == Decimal("-5")
    assert collection.observations[0].unrealized_pnl is not None
    assert collection.observations[0].unrealized_pnl.amount == Decimal("-4")


def test_collect_marks_non_finite_position_pnl_unavailable() -> None:
    source = _source(
        _transport(
            position_snapshots=(
                _position(
                    realized_profit=Decimal("1"),
                    unrealized_profit=Decimal("NaN"),
                ),
            )
        )
    )

    evidence = source.collect(_request())

    collection = evidence.position_pnl_collection
    assert collection.complete is False
    assert (
        LiveRiskPositionPnlUnavailableReason.POSITION_UNREALIZED_PNL_UNAVAILABLE
        in collection.unavailable_reasons
    )
    assert collection.observations[0].unrealized_pnl is None


def test_collect_marks_a_foreign_position_client_as_incomplete() -> None:
    source = _source(
        _transport(
            position_snapshots=(
                _position(
                    client_id="foreign-client",
                    realized_profit=Decimal("1"),
                    unrealized_profit=Decimal("2"),
                ),
            )
        )
    )

    evidence = source.collect(_request())

    collection = evidence.position_pnl_collection
    assert collection.complete is False
    assert (
        LiveRiskPositionPnlUnavailableReason.POSITION_CLIENT_ID_MISMATCH
        in collection.unavailable_reasons
    )
    assert "position client identity mismatch" in evidence.contradictions


def test_collect_marks_an_unavailable_positions_book_not_collected() -> None:
    source = _source(_RecordingTransport(fail="positions"))

    evidence = source.collect(_request())

    collection = evidence.position_pnl_collection
    assert collection.complete is False
    assert collection.observed_at is None
    assert collection.observations == ()
    assert (
        LiveRiskPositionPnlUnavailableReason.POSITION_BOOK_UNAVAILABLE
        in collection.unavailable_reasons
    )


def test_collect_treats_an_available_empty_positions_book_as_an_empty_collection() -> None:
    source = _source(_transport(position_snapshots=()))

    evidence = source.collect(_request())

    collection = evidence.position_pnl_collection
    assert collection.complete is True
    assert collection.observed_at == OBSERVED_AT
    assert collection.observations == ()


def test_collect_preserves_request_identity_and_resolution() -> None:
    request = _request()
    source = _source()

    evidence = source.collect(request)

    assert evidence.context is not None
    assert evidence.snapshot is not None
    assert evidence.context.instrument == _instrument()
    assert evidence.context.account_id == ACCOUNT
    assert evidence.context.portfolio_id == request.execution_context.portfolio_id
    assert evidence.context.broker_connection_id == CONNECTION
    assert evidence.context.product == request.product
    assert evidence.context.effective_position_effect == request.effective_position_effect
    assert evidence.context.market_pack_id == request.execution_context.market_pack_id
    assert evidence.context.rule_version == request.execution_context.rule_version
    assert evidence.context.instrument_resolution == request.instrument_resolution
    assert evidence.context.reference_price == request.order.limit_price
    assert evidence.snapshot.required_margin == request.required_margin
    assert evidence.snapshot.account_id == ACCOUNT
    assert evidence.snapshot.portfolio_id == request.execution_context.portfolio_id
    assert evidence.snapshot.broker_connection_id == CONNECTION


def test_collect_reports_a_market_order_reference_price_as_unknown() -> None:
    request = _request(order_type=OrderType.MARKET, limit_price=None)
    source = _source()

    evidence = source.collect(request)

    assert evidence.context is not None
    assert evidence.context.reference_price is None
    assert evidence.reference_price is None


def test_builder_binds_the_explicit_source_inputs() -> None:
    transport = _transport()
    instruments = ((_instrument(), _ref()),)

    source = build_dhan_risk_evidence_source(
        transport=transport,
        account_id=ACCOUNT,
        broker_connection_id=CONNECTION,
        broker_client_id=CLIENT,
        instruments=instruments,
        read_timeout=2.5,
    )

    assert source.transport is transport
    assert source.account_id == ACCOUNT
    assert source.broker_connection_id == CONNECTION
    assert source.broker_client_id == CLIENT
    assert source.instruments == instruments
    assert source.read_timeout == 2.5
