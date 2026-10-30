"""Regression tests for the application-owned LIVE risk evidence authority.

The authority is the only seam allowed to turn broker-bound evidence into LIVE
risk admission. These tests pin its fail-closed contract: identity, request
binding, completeness, contradictions, freshness, trusted capture time, and the
per-instance HMAC seal all have to hold before the existing risk engine runs.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest

from quantx.application.live_risk import (
    LivePreTradeRiskEvaluator,
    LiveRiskEvaluationInputs,
    LiveRiskEvidence,
    LiveRiskEvidenceAuthority,
    LiveRiskEvidenceAuthorization,
    LiveRiskEvidenceField,
    LiveRiskEvidenceObservation,
    required_live_risk_evidence_fields,
)
from quantx.application.live_risk_evidence import (
    LiveRiskPositionPnlCollection,
    LiveRiskPositionPnlObservation,
    LiveRiskPositionPnlProvenance,
)
from quantx.application.live_risk_sources import live_risk_evidence_catalog_for
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.clock import Clock, FixedClock
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType, PositionEffect
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instrument_registry import InstrumentResolution
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import (
    LiveRiskLimitsError,
    PreTradeRiskEngine,
    RiskContext,
    RiskDecision,
    RiskLimits,
    RiskResult,
    RiskSnapshot,
)
from quantx.domain.value_objects import Money, ProductCode
from tests.unit._execution_request_proofs import approved_request
from tests.unit.application._live_risk_trust import (
    catalog_for,
    registered_connection,
    registry_with,
)

EVALUATED_AT = datetime(2026, 1, 1, 9, 30, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 1, 1, 9, 29, tzinfo=UTC)

ACCOUNT = AccountId("acct-1")
CONNECTION = BrokerConnectionId("conn-1")
PORTFOLIO = PortfolioId("portfolio-1")
CLIENT = "client-1"
SOURCE_ID = "test-complete-source"
TRANSPORT = object()

ALL_FIELDS = frozenset(LiveRiskEvidenceField)

_IDENTITY = "LIVE_RISK_EVIDENCE_IDENTITY_MISMATCH"
_REQUEST = "LIVE_RISK_EVIDENCE_REQUEST_MISMATCH"
_INCOMPLETE = "LIVE_RISK_EVIDENCE_INCOMPLETE"
_CONTRADICTION = "LIVE_RISK_EVIDENCE_CONTRADICTION"
_FUTURE = "LIVE_RISK_EVIDENCE_FUTURE_DATED"
_STALE = "LIVE_RISK_EVIDENCE_STALE"
_SOURCE_UNAVAILABLE = "LIVE_RISK_EVIDENCE_SOURCE_UNAVAILABLE"
_EVIDENCE_UNAVAILABLE = "LIVE_RISK_EVIDENCE_UNAVAILABLE"
_AUTHORIZATION_INVALID = "LIVE_RISK_EVIDENCE_AUTHORIZATION_INVALID"
_CLOCK_UNAVAILABLE = "LIVE_RISK_EVIDENCE_CLOCK_UNAVAILABLE"
_CLOCK_INVALID = "LIVE_RISK_EVIDENCE_CLOCK_INVALID"
_CLAIM_OUT_OF_TOLERANCE = "LIVE_CLOCK_CLAIM_OUT_OF_TOLERANCE"


def _market() -> MarketContext:
    return MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def _instrument(*, symbol: str = "TCS") -> Instrument:
    return Instrument(
        InstrumentId("NSE", symbol),
        symbol,
        AssetClass.EQUITY,
        _market(),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _foreign_instrument() -> Instrument:
    return Instrument(
        InstrumentId("NYSE", "AAPL"),
        "AAPL",
        AssetClass.EQUITY,
        MarketContext(MarketRegion.NORTH_AMERICA, MarketFamily.EQUITY, "NYSE", "US"),
        "USD",
        Decimal("0.01"),
        Decimal("1"),
    )


def _financial() -> AccountFinancialState:
    return AccountFinancialState(
        CapitalSourceType.LIVE_BROKER,
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("0"), "INR"),
        Money(Decimal("100000"), "INR"),
        Money(Decimal("100000"), "INR"),
    )


def _financial_usd() -> AccountFinancialState:
    return AccountFinancialState(
        CapitalSourceType.LIVE_BROKER,
        Money(Decimal("100000"), "USD"),
        Money(Decimal("100000"), "USD"),
        Money(Decimal("0"), "USD"),
        Money(Decimal("0"), "USD"),
        Money(Decimal("100000"), "USD"),
        Money(Decimal("100000"), "USD"),
    )


def _context(**overrides) -> RiskContext:
    values: dict = {
        "reference_price": Decimal("100"),
        "product": ProductCode("CNC"),
        "market_pack_id": "india-equity",
        "rule_version": "india-products-v1",
        "account_id": ACCOUNT,
        "portfolio_id": PORTFOLIO,
        "broker_connection_id": CONNECTION,
    }
    values.update(overrides)
    return RiskContext(_instrument(), _financial(), **values)


def _execution_context() -> ExecutionContext:
    return ExecutionContext(
        account_id=ACCOUNT,
        portfolio_id=PORTFOLIO,
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=_market(),
        broker_connection_id=CONNECTION,
        execution_mode=ExecutionMode.LIVE,
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )


def _intent(**overrides) -> TradeIntent:
    values: dict = {
        "instrument": InstrumentId("NSE", "TCS"),
        "side": OrderSide.BUY,
        "quantity": Decimal("10"),
        "order_type": OrderType.LIMIT,
        "limit_price": Decimal("100"),
        "required_margin": Decimal("1000"),
        "required_capabilities": frozenset({"ORDER_SUBMISSION"}),
        "execution_context": _execution_context(),
        "product": ProductCode("CNC"),
    }
    values.update(overrides)
    return TradeIntent(**values)


def _limits(**overrides) -> RiskLimits:
    values: dict = {
        "max_order_notional": Decimal("100000"),
        "max_position_notional": Decimal("100000"),
        "max_portfolio_exposure": Decimal("1000000"),
        "max_instrument_concentration": Decimal("0.9"),
        "max_daily_loss": Decimal("10000"),
        "max_drawdown": Decimal("0.5"),
        "max_snapshot_age": timedelta(minutes=5),
    }
    values.update(overrides)
    return RiskLimits(**values)


def _snapshot(**overrides) -> RiskSnapshot:
    values: dict = {
        "observed_at": OBSERVED_AT,
        "current_position_exposure": Decimal("1000"),
        "current_instrument_exposure": Decimal("1000"),
        "current_portfolio_exposure": Decimal("5000"),
        "available_margin": Decimal("100000"),
        "required_margin": Decimal("1000"),
        "daily_pnl": Decimal("0"),
        "equity": Decimal("100000"),
        "high_water_mark": Decimal("100000"),
        "account_id": ACCOUNT,
        "portfolio_id": PORTFOLIO,
        "broker_connection_id": CONNECTION,
    }
    values.update(overrides)
    return RiskSnapshot(**values)


_DEFAULT_INTENT_ID = object()


def _request(*, intent_id: UUID | None | object = _DEFAULT_INTENT_ID) -> ApprovedExecutionRequest:
    intent = _intent()
    order = build_order_from_intent(intent)
    if intent_id is _DEFAULT_INTENT_ID:
        intent_id = uuid4()
    order = replace(order, intent_id=cast(UUID | None, intent_id))
    return approved_request(
        order=order,
        execution_context=_execution_context(),
        risk_result=RiskResult(RiskDecision.APPROVE, "upstream approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        required_margin=intent.required_margin,
        product=ProductCode("CNC"),
    )


def _observations(observed_at: datetime = OBSERVED_AT) -> dict:
    return {
        LiveRiskEvidenceField.CASH_BALANCE: LiveRiskEvidenceObservation(
            Decimal("100000"), observed_at
        ),
        LiveRiskEvidenceField.AVAILABLE_CASH: LiveRiskEvidenceObservation(
            Decimal("100000"), observed_at
        ),
        LiveRiskEvidenceField.BLOCKED_CASH: LiveRiskEvidenceObservation(Decimal("0"), observed_at),
        LiveRiskEvidenceField.MARGIN_USED: LiveRiskEvidenceObservation(Decimal("0"), observed_at),
        LiveRiskEvidenceField.MARGIN_AVAILABLE: LiveRiskEvidenceObservation(
            Decimal("100000"), observed_at
        ),
        LiveRiskEvidenceField.BUYING_POWER: LiveRiskEvidenceObservation(
            Decimal("100000"), observed_at
        ),
        LiveRiskEvidenceField.CURRENT_POSITION_EXPOSURE: LiveRiskEvidenceObservation(
            Decimal("1000"), observed_at
        ),
        LiveRiskEvidenceField.CURRENT_INSTRUMENT_EXPOSURE: LiveRiskEvidenceObservation(
            Decimal("1000"), observed_at
        ),
        LiveRiskEvidenceField.CURRENT_PORTFOLIO_EXPOSURE: LiveRiskEvidenceObservation(
            Decimal("5000"), observed_at
        ),
        LiveRiskEvidenceField.DAILY_PNL: LiveRiskEvidenceObservation(Decimal("0"), observed_at),
        LiveRiskEvidenceField.EQUITY: LiveRiskEvidenceObservation(Decimal("100000"), observed_at),
        LiveRiskEvidenceField.HIGH_WATER_MARK: LiveRiskEvidenceObservation(
            Decimal("100000"), observed_at
        ),
    }


def _evidence(**overrides) -> LiveRiskEvidence:
    values: dict = {
        "source_id": SOURCE_ID,
        "broker_client_id": CLIENT,
        "account_id": ACCOUNT,
        "broker_connection_id": CONNECTION,
        "transport": TRANSPORT,
        "identity_observed_at": OBSERVED_AT,
        "context": _context(),
        "snapshot": _snapshot(),
        "observations": _observations(),
        "reference_price": Decimal("100"),
        "unavailable_fields": (),
        "contradictions": (),
        "message": "complete",
    }
    values.update(overrides)
    return LiveRiskEvidence(**values)


class _FakeSource:
    def __init__(
        self,
        *,
        evidence_factory,
        supported_fields: frozenset[LiveRiskEvidenceField] = ALL_FIELDS,
        source_id: str = SOURCE_ID,
        error: Exception | None = None,
    ) -> None:
        self._evidence_factory = evidence_factory
        self._supported_fields = supported_fields
        self._source_id = source_id
        self._error = error
        self.calls = 0

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def supported_fields(self) -> frozenset[LiveRiskEvidenceField]:
        return self._supported_fields

    def collect(self, request: ApprovedExecutionRequest) -> LiveRiskEvidence:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._evidence_factory(request)


def _source(
    *,
    evidence_factory=None,
    supported_fields: frozenset[LiveRiskEvidenceField] = ALL_FIELDS,
    source_id: str = SOURCE_ID,
    error: Exception | None = None,
) -> _FakeSource:
    return _FakeSource(
        evidence_factory=evidence_factory or (lambda request: _evidence()),
        supported_fields=supported_fields,
        source_id=source_id,
        error=error,
    )


def _authority(
    *,
    source=None,
    limits: RiskLimits | None = None,
    clock: Clock | None = None,
    account_id: AccountId = ACCOUNT,
    broker_connection_id: BrokerConnectionId = CONNECTION,
    broker_client_id: str = CLIENT,
    transport: object = TRANSPORT,
) -> LiveRiskEvidenceAuthority:
    """Build an authority whose source trust is the registered adapter's own path."""
    registered = registered_connection(
        account_id=account_id,
        connection_id=broker_connection_id,
        source=source if source is not None else _source(),
        broker_client_id=broker_client_id,
        transport=transport,
    )
    catalog = catalog_for(registered)
    grant = catalog.grant(registered)
    assert grant is not None
    return LiveRiskEvidenceAuthority(
        grant=grant,
        catalog=catalog,
        registry=registry_with(registered),
        limits=limits if limits is not None else _limits(),
        clock=clock if clock is not None else FixedClock(EVALUATED_AT),
    )


def _authority_for(evidence: dict | None = None, **overrides) -> LiveRiskEvidenceAuthority:
    source = _source(evidence_factory=lambda request: _evidence(**(evidence or {})))
    return _authority(source=source, **overrides)


def _reason_code(result: RiskResult) -> str:
    return result.reason.split(":", 1)[0]


def _rejection(result) -> RiskResult:
    assert type(result) is RiskResult
    assert result.decision is RiskDecision.REJECT
    return result


class _RaisingClock(Clock):
    def now(self) -> datetime:
        raise RuntimeError("internal clock failure detail")


class _NaiveClock(Clock):
    def now(self) -> datetime:
        return datetime(2026, 1, 1, 9, 30)


class _StepClock(Clock):
    def __init__(self, *readings: datetime) -> None:
        self._readings = list(readings)

    def now(self) -> datetime:
        return self._readings.pop(0)


# Construction and required-field derivation.


def test_authority_requires_an_application_issued_grant() -> None:
    registered = registered_connection(
        account_id=ACCOUNT, connection_id=CONNECTION, source=_source()
    )
    catalog = catalog_for(registered)

    with pytest.raises(TypeError, match="application-issued source grant"):
        LiveRiskEvidenceAuthority(
            grant=object(),  # type: ignore[arg-type]
            catalog=catalog,
            registry=registry_with(registered),
            limits=_limits(),
            clock=FixedClock(EVALUATED_AT),
        )


def test_authority_requires_a_clock() -> None:
    with pytest.raises(TypeError, match="Clock"):
        _authority(clock=object())


def test_authority_rejects_a_connection_this_process_did_not_register() -> None:
    registered = registered_connection(
        account_id=ACCOUNT, connection_id=CONNECTION, source=_source()
    )
    catalog = catalog_for(registered)
    grant = catalog.grant(registered)
    assert grant is not None

    with pytest.raises(TypeError, match="registered broker connection"):
        LiveRiskEvidenceAuthority(
            grant=grant,
            catalog=catalog,
            registry=registry_with(
                registered_connection(
                    account_id=ACCOUNT,
                    connection_id=BrokerConnectionId("conn-other"),
                )
            ),
            limits=_limits(),
            clock=FixedClock(EVALUATED_AT),
        )


def test_authority_rejects_a_disabled_connection() -> None:
    disabled = registered_connection(
        account_id=ACCOUNT,
        connection_id=CONNECTION,
        enabled=False,
        source=_source(),
    )

    catalog = live_risk_evidence_catalog_for(disabled)
    assert catalog is None


def test_authority_rejects_a_catalog_that_did_not_mint_the_grant() -> None:
    registered = registered_connection(
        account_id=ACCOUNT, connection_id=CONNECTION, source=_source()
    )
    other_registration = registered_connection(
        account_id=ACCOUNT, connection_id=CONNECTION, source=_source()
    )
    issuing = catalog_for(registered)
    stranger = catalog_for(other_registration)
    grant = issuing.grant(registered)
    assert grant is not None

    with pytest.raises(TypeError, match="application-issued source grant"):
        LiveRiskEvidenceAuthority(
            grant=grant,
            catalog=stranger,
            registry=registry_with(registered),
            limits=_limits(),
            clock=FixedClock(EVALUATED_AT),
        )


def test_authority_requires_complete_live_limits() -> None:
    with pytest.raises(LiveRiskLimitsError, match="max_daily_loss"):
        _authority(limits=_limits(max_daily_loss=None))


def test_authority_derives_every_field_the_default_limits_consume() -> None:
    assert required_live_risk_evidence_fields(_limits()) == ALL_FIELDS


def test_required_fields_always_include_the_six_financial_values() -> None:
    required = required_live_risk_evidence_fields(
        _limits(
            max_portfolio_exposure=None,
            max_instrument_concentration=None,
            max_drawdown=None,
        )
    )

    assert required == {
        LiveRiskEvidenceField.CASH_BALANCE,
        LiveRiskEvidenceField.AVAILABLE_CASH,
        LiveRiskEvidenceField.BLOCKED_CASH,
        LiveRiskEvidenceField.MARGIN_USED,
        LiveRiskEvidenceField.MARGIN_AVAILABLE,
        LiveRiskEvidenceField.BUYING_POWER,
        LiveRiskEvidenceField.CURRENT_POSITION_EXPOSURE,
        LiveRiskEvidenceField.DAILY_PNL,
    }


def test_required_fields_follow_each_enabled_limit() -> None:
    base = _limits(
        max_position_notional=None,
        max_portfolio_exposure=None,
        max_instrument_concentration=None,
        max_drawdown=None,
    )
    financial = {
        LiveRiskEvidenceField.CASH_BALANCE,
        LiveRiskEvidenceField.AVAILABLE_CASH,
        LiveRiskEvidenceField.BLOCKED_CASH,
        LiveRiskEvidenceField.MARGIN_USED,
        LiveRiskEvidenceField.MARGIN_AVAILABLE,
        LiveRiskEvidenceField.BUYING_POWER,
    }
    daily = LiveRiskEvidenceField.DAILY_PNL

    assert required_live_risk_evidence_fields(base) == financial | {daily}
    assert required_live_risk_evidence_fields(
        replace(base, max_position_notional=Decimal("1"))
    ) == financial | {daily, LiveRiskEvidenceField.CURRENT_POSITION_EXPOSURE}
    assert required_live_risk_evidence_fields(
        replace(base, max_portfolio_exposure=Decimal("1"))
    ) == financial | {daily, LiveRiskEvidenceField.CURRENT_PORTFOLIO_EXPOSURE}
    assert required_live_risk_evidence_fields(
        replace(base, max_instrument_concentration=Decimal("0.5"))
    ) == financial | {
        daily,
        LiveRiskEvidenceField.CURRENT_INSTRUMENT_EXPOSURE,
        LiveRiskEvidenceField.CURRENT_PORTFOLIO_EXPOSURE,
    }
    assert required_live_risk_evidence_fields(replace(base, max_drawdown=Decimal("0.5"))) == (
        financial
        | {
            daily,
            LiveRiskEvidenceField.EQUITY,
            LiveRiskEvidenceField.HIGH_WATER_MARK,
        }
    )


def test_authority_is_available_when_the_source_declares_every_required_field() -> None:
    authority = _authority()

    assert authority.required_fields == ALL_FIELDS
    assert authority.authoritative_evidence_available is True


@pytest.mark.parametrize("missing", list(LiveRiskEvidenceField))
def test_authority_is_unavailable_when_one_required_field_is_unsupported(missing) -> None:
    source = _source(supported_fields=ALL_FIELDS - {missing})
    authority = _authority(source=source)

    assert authority.authoritative_evidence_available is False
    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == _SOURCE_UNAVAILABLE
    assert source.calls == 0


def test_authority_availability_follows_the_configured_limits() -> None:
    source = _source(
        supported_fields=ALL_FIELDS
        - {LiveRiskEvidenceField.EQUITY, LiveRiskEvidenceField.HIGH_WATER_MARK}
    )
    authority = _authority(source=source, limits=_limits(max_drawdown=None))

    assert LiveRiskEvidenceField.EQUITY not in authority.required_fields
    assert LiveRiskEvidenceField.HIGH_WATER_MARK not in authority.required_fields
    assert authority.authoritative_evidence_available is True


# Admission.


def test_admit_returns_bound_inputs_and_a_valid_authorization() -> None:
    request = _request()
    authority = _authority()

    admission = authority.admit(request)

    assert type(admission) is tuple
    inputs, authorization = admission
    assert type(inputs) is LiveRiskEvaluationInputs
    assert type(authorization) is LiveRiskEvidenceAuthorization
    assert inputs.intent.intent_id == request.order.intent_id
    assert inputs.context.account_id == ACCOUNT
    assert inputs.context.portfolio_id == PORTFOLIO
    assert inputs.snapshot.account_id == ACCOUNT
    assert inputs.snapshot.observed_at == OBSERVED_AT
    assert inputs.claimed_evaluated_at == EVALUATED_AT
    assert authorization.client_order_id == request.order.client_order_id
    assert authority.verify(authorization, request, inputs) is True


def test_admit_stamps_the_oldest_observation_as_the_snapshot_instant() -> None:
    identity_at = datetime(2026, 1, 1, 9, 25, tzinfo=UTC)
    authority = _authority_for(
        {
            "identity_observed_at": identity_at,
            "observations": _observations(datetime(2026, 1, 1, 9, 29, tzinfo=UTC)),
        }
    )

    admission = authority.admit(_request())

    assert type(admission) is tuple
    inputs, _ = admission
    assert inputs.snapshot.observed_at == identity_at


def test_admit_rejects_a_source_exception() -> None:
    source = _source(error=RuntimeError("transport failure"))
    authority = _authority(source=source)

    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == _EVIDENCE_UNAVAILABLE
    assert source.calls == 1


def test_admit_rejects_a_source_that_returns_a_non_evidence_value() -> None:
    authority = _authority(source=_source(evidence_factory=lambda request: None))

    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == _EVIDENCE_UNAVAILABLE


@pytest.mark.parametrize(
    ("evidence", "code"),
    [
        ({"source_id": "foreign-source"}, _IDENTITY),
        ({"broker_client_id": "foreign-client"}, _IDENTITY),
        ({"broker_client_id": None}, _IDENTITY),
        ({"account_id": AccountId("acct-foreign")}, _IDENTITY),
        ({"account_id": None}, _IDENTITY),
        ({"broker_connection_id": BrokerConnectionId("conn-foreign")}, _IDENTITY),
        ({"broker_connection_id": None}, _IDENTITY),
        ({"transport": object()}, _IDENTITY),
        ({"transport": None}, _IDENTITY),
        ({"identity_observed_at": None}, _INCOMPLETE),
        ({"identity_observed_at": datetime(2026, 1, 1, 9, 29)}, _INCOMPLETE),
        ({"context": None}, _INCOMPLETE),
        ({"snapshot": None}, _INCOMPLETE),
        ({"context": object()}, _IDENTITY),
        ({"snapshot": object()}, _IDENTITY),
        (
            {
                "context": replace(
                    _context(),
                    financial_state=replace(
                        _financial(), capital_source=CapitalSourceType.PAPER_CONFIGURED
                    ),
                )
            },
            _IDENTITY,
        ),
        (
            {
                "context": replace(
                    _context(),
                    instrument=_foreign_instrument(),
                    financial_state=_financial_usd(),
                )
            },
            _IDENTITY,
        ),
        (
            {"context": replace(_context(), financial_state=_financial_usd())},
            _IDENTITY,
        ),
        (
            {"context": replace(_context(), account_id=AccountId("acct-foreign"))},
            _IDENTITY,
        ),
        (
            {
                "context": replace(
                    _context(), broker_connection_id=BrokerConnectionId("conn-foreign")
                )
            },
            _IDENTITY,
        ),
        ({"snapshot": replace(_snapshot(), account_id=AccountId("acct-foreign"))}, _IDENTITY),
        (
            {
                "snapshot": replace(
                    _snapshot(), broker_connection_id=BrokerConnectionId("conn-foreign")
                )
            },
            _IDENTITY,
        ),
    ],
    ids=[
        "source-id",
        "client-id",
        "client-id-missing",
        "account-id",
        "account-id-missing",
        "connection-id",
        "connection-id-missing",
        "transport",
        "transport-missing",
        "identity-missing",
        "identity-naive",
        "context-missing",
        "snapshot-missing",
        "context-type",
        "snapshot-type",
        "capital-source",
        "non-india-market",
        "currency-mismatch",
        "context-account",
        "context-connection",
        "snapshot-account",
        "snapshot-connection",
    ],
)
def test_admit_rejects_foreign_or_missing_identity(evidence, code) -> None:
    authority = _authority_for(evidence)

    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == code


def _resolution() -> InstrumentResolution:
    return InstrumentResolution(
        instrument=_instrument(),
        instrument_rule_version="test-rules-v1",
        instrument_rule_effective_from=OBSERVED_AT - timedelta(days=1),
        resolved_at=OBSERVED_AT,
    )


def _bse_instrument() -> Instrument:
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN"),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


@pytest.mark.parametrize(
    "evidence",
    [
        {"context": replace(_context(), portfolio_id=PortfolioId("portfolio-foreign"))},
        {"snapshot": replace(_snapshot(), portfolio_id=PortfolioId("portfolio-foreign"))},
        {"context": replace(_context(), instrument=_instrument(symbol="INFY"))},
        {"context": replace(_context(), instrument=_bse_instrument())},
        {"context": replace(_context(), product=ProductCode("MIS"))},
        {"context": replace(_context(), effective_position_effect=PositionEffect.OPEN)},
        {"context": replace(_context(), market_pack_id="foreign-pack")},
        {"context": replace(_context(), rule_version="foreign-rules")},
        {"context": replace(_context(), reference_price=Decimal("101"))},
        {"context": replace(_context(), instrument_resolution=_resolution())},
        {"snapshot": replace(_snapshot(), required_margin=Decimal("999"))},
        {"snapshot": replace(_snapshot(), available_margin=Decimal("99999"))},
    ],
    ids=[
        "context-portfolio",
        "snapshot-portfolio",
        "context-instrument",
        "context-market",
        "context-product",
        "context-position-effect",
        "context-market-pack",
        "context-rule-version",
        "context-reference-price",
        "context-instrument-resolution",
        "snapshot-required-margin",
        "snapshot-available-margin",
    ],
)
def test_admit_rejects_evidence_for_another_request(evidence) -> None:
    authority = _authority_for(evidence)

    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == _REQUEST


def test_admit_rejects_a_request_without_an_intent_id() -> None:
    request = _request(intent_id=cast(UUID, None))
    authority = _authority()

    result = _rejection(authority.admit(request))

    assert _reason_code(result) == _REQUEST


def test_admit_rejects_contradictory_evidence() -> None:
    authority = _authority_for({"contradictions": ("funds client identity mismatch",)})

    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == _CONTRADICTION


def test_admit_rejects_an_unavailable_required_field() -> None:
    authority = _authority_for({"unavailable_fields": (LiveRiskEvidenceField.DAILY_PNL,)})

    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == _INCOMPLETE


def test_admit_allows_an_unavailable_field_the_limits_do_not_require() -> None:
    observations = {
        field: observation
        for field, observation in _observations().items()
        if field not in {LiveRiskEvidenceField.EQUITY, LiveRiskEvidenceField.HIGH_WATER_MARK}
    }
    authority = _authority_for(
        {
            "observations": observations,
            "unavailable_fields": (
                LiveRiskEvidenceField.EQUITY,
                LiveRiskEvidenceField.HIGH_WATER_MARK,
            ),
        },
        limits=_limits(max_drawdown=None),
    )

    admission = authority.admit(_request())

    assert type(admission) is tuple


def test_admit_rejects_a_missing_required_observation() -> None:
    observations = dict(_observations())
    del observations[LiveRiskEvidenceField.DAILY_PNL]
    authority = _authority_for({"observations": observations})

    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == _INCOMPLETE


def test_admit_rejects_a_malformed_observation() -> None:
    observations = dict(_observations())
    observations[LiveRiskEvidenceField.DAILY_PNL] = object()
    authority = _authority_for({"observations": observations})

    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == _INCOMPLETE


def test_admit_rejects_an_observation_that_contradicts_the_context() -> None:
    observations = dict(_observations())
    observations[LiveRiskEvidenceField.DAILY_PNL] = LiveRiskEvidenceObservation(
        Decimal("1"), OBSERVED_AT
    )
    authority = _authority_for({"observations": observations})

    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == _CONTRADICTION


def test_admit_rejects_stale_evidence() -> None:
    authority = _authority(clock=FixedClock(OBSERVED_AT + timedelta(minutes=6)))

    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == _STALE


def test_admit_rejects_future_dated_evidence() -> None:
    authority = _authority_for({"observations": _observations(EVALUATED_AT + timedelta(seconds=1))})

    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == _FUTURE


def test_admit_rejects_an_unreadable_trusted_clock() -> None:
    authority = _authority(clock=_RaisingClock())

    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == _CLOCK_UNAVAILABLE
    assert "internal clock failure detail" not in result.reason


def test_admit_rejects_an_invalid_trusted_clock() -> None:
    authority = _authority(clock=_NaiveClock())

    result = _rejection(authority.admit(_request()))

    assert _reason_code(result) == _CLOCK_INVALID


# Authorization seal.


def _admitted():
    request = _request()
    authority = _authority()
    admission = authority.admit(request)
    assert type(admission) is tuple
    inputs, authorization = admission
    return authority, request, inputs, authorization


def test_verify_rejects_a_caller_created_authorization() -> None:
    authority, request, inputs, _ = _admitted()

    forged = LiveRiskEvidenceAuthorization(
        client_order_id=request.order.client_order_id,
        evidence_digest="0" * 64,
        seal="0" * 64,
    )

    assert authority.verify(forged, request, inputs) is False


def test_verify_rejects_a_tampered_digest() -> None:
    authority, request, inputs, authorization = _admitted()

    tampered = replace(authorization, evidence_digest="0" * 64)

    assert authority.verify(tampered, request, inputs) is False


def test_verify_rejects_a_tampered_seal() -> None:
    authority, request, inputs, authorization = _admitted()

    tampered = replace(authorization, seal="0" * 64)

    assert authority.verify(tampered, request, inputs) is False


def test_verify_rejects_another_request() -> None:
    authority, _, inputs, authorization = _admitted()

    assert authority.verify(authorization, _request(), inputs) is False


def test_verify_rejects_an_authorization_from_another_authority() -> None:
    _, request, inputs, authorization = _admitted()
    other = _authority()

    assert other.verify(authorization, request, inputs) is False


def test_verify_rejects_altered_inputs() -> None:
    authority, request, inputs, authorization = _admitted()
    altered = replace(inputs, snapshot=replace(inputs.snapshot, daily_pnl=Decimal("1")))

    assert authority.verify(authorization, request, altered) is False


def test_verify_binds_supplemental_position_pnl_collection() -> None:
    collection = LiveRiskPositionPnlCollection(
        observed_at=OBSERVED_AT,
        observations=(
            LiveRiskPositionPnlObservation(
                source_position_key="0:NSE_EQ:1333",
                instrument_id=InstrumentId("NSE", "TCS"),
                net_quantity=Decimal("10"),
                product_type="CNC",
                position_type="LONG",
                realized_pnl=Money(Decimal("-12.50"), "INR"),
                unrealized_pnl=Money(Decimal("3.25"), "INR"),
                observed_at=OBSERVED_AT,
                provenance=LiveRiskPositionPnlProvenance.BROKER_REPORTED,
            ),
        ),
        unavailable_reasons=(),
    )
    authority = _authority_for({"position_pnl_collection": collection})
    request = _request()

    admission = authority.admit(request)

    assert type(admission) is tuple
    inputs, authorization = admission
    assert inputs.position_pnl_collection == collection
    assert authority.verify(authorization, request, inputs) is True

    changed_row = replace(
        collection.observations[0],
        unrealized_pnl=Money(Decimal("99"), "INR"),
    )
    changed_collection = replace(collection, observations=(changed_row,))
    changed_inputs = replace(inputs, position_pnl_collection=changed_collection)
    assert authority.verify(authorization, request, changed_inputs) is False

    malformed_inputs = replace(
        inputs,
        position_pnl_collection=cast(LiveRiskPositionPnlCollection, object()),
    )
    assert authority.verify(authorization, request, malformed_inputs) is False


def test_verify_rejects_a_non_authorization_value() -> None:
    authority, request, inputs, _ = _admitted()

    assert authority.verify(cast(LiveRiskEvidenceAuthorization, object()), request, inputs) is False


def test_verify_rejects_a_non_uuid_client_order_id() -> None:
    authority, request, inputs, authorization = _admitted()
    tampered = replace(
        authorization,
        client_order_id=cast(UUID, str(request.order.client_order_id)),
    )

    assert authority.verify(tampered, request, inputs) is False


# Evaluator modes.


def test_evaluator_requires_exactly_one_evidence_mode() -> None:
    engine = PreTradeRiskEngine()

    with pytest.raises(TypeError, match="exactly one"):
        LivePreTradeRiskEvaluator(
            engine=engine,
            limits=_limits(),
            clock=FixedClock(EVALUATED_AT),
        )
    with pytest.raises(TypeError, match="exactly one"):
        LivePreTradeRiskEvaluator(
            engine=engine,
            limits=_limits(),
            clock=FixedClock(EVALUATED_AT),
            inputs_for_request=lambda request: _live_inputs(),
            authority=_authority(),
        )


def test_evaluator_rejects_an_unsupported_authority_type() -> None:
    with pytest.raises(TypeError, match="unsupported type"):
        LivePreTradeRiskEvaluator(
            engine=PreTradeRiskEngine(),
            limits=_limits(),
            clock=FixedClock(EVALUATED_AT),
            authority=cast(LiveRiskEvidenceAuthority, object()),
        )


def _live_inputs() -> LiveRiskEvaluationInputs:
    return LiveRiskEvaluationInputs(
        intent=_intent(),
        context=_context(),
        snapshot=_snapshot(),
        claimed_evaluated_at=EVALUATED_AT,
    )


def _authority_evaluator(
    authority: LiveRiskEvidenceAuthority,
    *,
    limits: RiskLimits | None = None,
    clock: Clock | None = None,
) -> LivePreTradeRiskEvaluator:
    return LivePreTradeRiskEvaluator(
        engine=PreTradeRiskEngine(),
        limits=limits if limits is not None else _limits(),
        clock=clock if clock is not None else FixedClock(EVALUATED_AT),
        authority=authority,
    )


def test_callback_evaluator_is_never_authoritative() -> None:
    evaluator = LivePreTradeRiskEvaluator(
        engine=PreTradeRiskEngine(),
        limits=_limits(),
        clock=FixedClock(EVALUATED_AT),
        inputs_for_request=lambda request: _live_inputs(),
    )

    assert evaluator.authoritative_evidence_available is False


def test_authority_evaluator_reports_source_availability() -> None:
    available = _authority_evaluator(_authority())
    unavailable = _authority_evaluator(
        _authority(source=_source(supported_fields=ALL_FIELDS - {LiveRiskEvidenceField.DAILY_PNL}))
    )

    assert available.authoritative_evidence_available is True
    assert unavailable.authoritative_evidence_available is False


def test_authority_evaluator_approves_complete_evidence() -> None:
    evaluator = _authority_evaluator(_authority())

    result = evaluator(_request())

    assert result.decision is RiskDecision.APPROVE


def test_authority_evaluator_rejects_incomplete_evidence() -> None:
    observations = dict(_observations())
    del observations[LiveRiskEvidenceField.DAILY_PNL]
    evaluator = _authority_evaluator(_authority_for({"observations": observations}))

    result = _rejection(evaluator(_request()))

    assert _reason_code(result) == _INCOMPLETE


def test_authority_evaluator_rejects_stale_evidence() -> None:
    later = OBSERVED_AT + timedelta(minutes=6)
    evaluator = _authority_evaluator(_authority(clock=FixedClock(later)))

    result = _rejection(evaluator(_request()))

    assert _reason_code(result) == _STALE


def test_authority_evaluator_rejects_a_claim_outside_clock_tolerance() -> None:
    clock = _StepClock(EVALUATED_AT, EVALUATED_AT + timedelta(seconds=6))
    evaluator = _authority_evaluator(_authority(clock=clock), clock=clock)

    result = _rejection(evaluator(_request()))

    assert _reason_code(result) == _CLAIM_OUT_OF_TOLERANCE


def test_authority_evaluator_runs_the_existing_risk_engine() -> None:
    evaluator = _authority_evaluator(
        _authority(),
        limits=_limits(max_order_notional=Decimal("500")),
    )

    result = _rejection(evaluator(_request()))

    assert result.reason.startswith("ORDER_NOTIONAL_LIMIT_EXCEEDED")


def test_authority_evaluator_never_runs_the_engine_for_foreign_evidence() -> None:
    evaluator = _authority_evaluator(
        _authority_for({"context": replace(_context(), account_id=AccountId("acct-foreign"))})
    )

    result = _rejection(evaluator(_request()))

    assert _reason_code(result) == _IDENTITY
