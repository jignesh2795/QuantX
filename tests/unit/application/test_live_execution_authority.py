"""Composition-root slice C: authority-mode LIVE admission through the stack.

These tests exercise the built stack end to end. A complete application-owned
source may reach the existing risk engine and the fake broker, while every
unknown, foreign, incomplete, stale, contradictory, or unavailable evidence
path stops before reservation, quarantine, or submission. The Dhan source is
also pinned here: it cannot authorize LIVE because it cannot supply daily P&L,
complete equity, or a high-water mark.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from quantx.application.execution import ExecutionDispatchStatus
from quantx.application.live_execution import (
    LiveExecutionCompositionError,
    LiveExecutionConfig,
    build_live_execution,
)
from quantx.application.live_risk import (
    LiveRiskEvaluationInputs,
    LiveRiskEvidence,
    LiveRiskEvidenceField,
    LiveRiskEvidenceObservation,
)
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.clock import FixedClock
from quantx.domain.deployment import PortfolioId
from quantx.domain.enums import OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instruments import InstrumentId
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import (
    PreTradeRiskEngine,
    RiskContext,
    RiskDecision,
    RiskLimits,
    RiskResult,
    RiskSnapshot,
)
from quantx.domain.value_objects import Money, ProductCode
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteSubmissionQuarantineRepository,
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)
from quantx.plugins.dhan.models import DhanInstrumentRef, DhanPositionSnapshot
from quantx.plugins.dhan.risk_evidence import DhanRiskEvidenceSource
from quantx.plugins.dhan.transport import InMemoryDhanTransport
from tests.unit._execution_request_proofs import approved_request, policy_verifier
from tests.unit.application.test_execution import FakeBroker
from tests.unit.application.test_live_execution import (
    EVALUATED_AT,
    INDIA_PACK_ID,
    INDIA_RULE_VERSION,
    OBSERVED_AT,
    _execution_context,
    _india_instrument,
    _limits,
    _policy,
    _runtime,
)

ACCOUNT = AccountId("acct-1")
CONNECTION = BrokerConnectionId("conn-1")
PORTFOLIO = PortfolioId("portfolio-1")
CLIENT = "client-1"
SOURCE_ID = "fake-complete-source"
TRANSPORT = object()

ALL_FIELDS = frozenset(LiveRiskEvidenceField)

_IDENTITY = "LIVE_RISK_EVIDENCE_IDENTITY_MISMATCH"
_REQUEST = "LIVE_RISK_EVIDENCE_REQUEST_MISMATCH"
_INCOMPLETE = "LIVE_RISK_EVIDENCE_INCOMPLETE"
_CONTRADICTION = "LIVE_RISK_EVIDENCE_CONTRADICTION"
_FUTURE = "LIVE_RISK_EVIDENCE_FUTURE_DATED"
_STALE = "LIVE_RISK_EVIDENCE_STALE"
_SOURCE_UNAVAILABLE = "authoritative LIVE risk evidence source is unavailable"
_EVIDENCE_UNAVAILABLE = "LIVE_RISK_EVIDENCE_UNAVAILABLE"


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


def _live_context(**overrides) -> RiskContext:
    values: dict = {
        "reference_price": Decimal("100"),
        "product": ProductCode("CNC"),
        "market_pack_id": INDIA_PACK_ID,
        "rule_version": INDIA_RULE_VERSION,
        "account_id": ACCOUNT,
        "portfolio_id": PORTFOLIO,
        "broker_connection_id": CONNECTION,
    }
    values.update(overrides)
    return RiskContext(_india_instrument(), _financial(), **values)


def _snapshot(**overrides) -> RiskSnapshot:
    values: dict = {
        "observed_at": OBSERVED_AT,
        "current_position_exposure": Decimal("0"),
        "current_instrument_exposure": Decimal("0"),
        "current_portfolio_exposure": Decimal("100000"),
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


def _request(
    *,
    order_type: OrderType = OrderType.LIMIT,
    limit_price: Decimal | None = Decimal("100"),
) -> ApprovedExecutionRequest:
    context = _execution_context()
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("1"),
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
        risk_result=RiskResult(RiskDecision.APPROVE, "upstream approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        required_margin=Decimal("1000"),
        product=ProductCode("CNC"),
    )


def _observations(observed_at=OBSERVED_AT) -> dict:
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
            Decimal("0"), observed_at
        ),
        LiveRiskEvidenceField.CURRENT_INSTRUMENT_EXPOSURE: LiveRiskEvidenceObservation(
            Decimal("0"), observed_at
        ),
        LiveRiskEvidenceField.CURRENT_PORTFOLIO_EXPOSURE: LiveRiskEvidenceObservation(
            Decimal("100000"), observed_at
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
        "context": _live_context(),
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
        evidence_factory=None,
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
        if self._evidence_factory is not None:
            return self._evidence_factory(request)
        return _evidence(source_id=self._source_id)


def _source(
    *,
    evidence_factory=None,
    supported_fields: frozenset[LiveRiskEvidenceField] = ALL_FIELDS,
    source_id: str = SOURCE_ID,
    error: Exception | None = None,
) -> _FakeSource:
    return _FakeSource(
        evidence_factory=evidence_factory,
        supported_fields=supported_fields,
        source_id=source_id,
        error=error,
    )


def _authority_config(
    source,
    *,
    clock=None,
    limits: RiskLimits | None = None,
    expected_account_id: object = ACCOUNT,
    expected_connection_id: object = CONNECTION,
    expected_client_id: object = CLIENT,
    expected_transport: object = TRANSPORT,
) -> LiveExecutionConfig:
    return LiveExecutionConfig(
        risk_limits=limits if limits is not None else _limits(),
        risk_engine=PreTradeRiskEngine(),
        clock=clock if clock is not None else FixedClock(EVALUATED_AT),
        market_policy=_policy(),
        policy_verifier=policy_verifier(),
        risk_evidence_source=source,
        expected_account_id=expected_account_id,  # type: ignore[arg-type]
        expected_broker_connection_id=expected_connection_id,  # type: ignore[arg-type]
        expected_broker_client_id=expected_client_id,  # type: ignore[arg-type]
        expected_transport=expected_transport,
    )


def _callback_config(callback) -> LiveExecutionConfig:
    return LiveExecutionConfig(
        risk_limits=_limits(),
        risk_engine=PreTradeRiskEngine(),
        clock=FixedClock(EVALUATED_AT),
        market_policy=_policy(),
        policy_verifier=policy_verifier(),
        risk_inputs_for_request=callback,
    )


def _expect_build_error(
    database: SqliteDatabase, config: LiveExecutionConfig, message: str
) -> None:
    with pytest.raises(LiveExecutionCompositionError, match=message):
        build_live_execution(_runtime(database), config)
    assert SqliteTradingGateStateStore(database).load() is None


def _assert_no_submission_side_effects(
    database: SqliteDatabase,
    request: ApprovedExecutionRequest,
    broker: FakeBroker,
) -> None:
    assert broker.submit_calls == 0
    unit_of_work = SqliteUnitOfWork(database)
    decision = unit_of_work.idempotency.check(
        request.order.client_order_id, request_fingerprint(request)
    )
    assert decision.reservation_pending is False
    assert decision.existing_receipt_id is None
    assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
    assert (
        SqliteSubmissionQuarantineRepository(database).list_by_client_order(
            request.order.client_order_id
        )
        == ()
    )


# Composition validation.


def test_build_requires_exactly_one_evidence_mode(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        neither = LiveExecutionConfig(
            risk_limits=_limits(),
            risk_engine=PreTradeRiskEngine(),
            clock=FixedClock(EVALUATED_AT),
            market_policy=_policy(),
            policy_verifier=policy_verifier(),
        )
        _expect_build_error(database, neither, "exactly one")

        both = LiveExecutionConfig(
            risk_limits=_limits(),
            risk_engine=PreTradeRiskEngine(),
            clock=FixedClock(EVALUATED_AT),
            market_policy=_policy(),
            policy_verifier=policy_verifier(),
            risk_inputs_for_request=lambda request: None,
            risk_evidence_source=_source(),
        )
        _expect_build_error(database, both, "exactly one")
    finally:
        database.close()


def test_build_rejects_authority_identity_in_callback_mode(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        config = LiveExecutionConfig(
            risk_limits=_limits(),
            risk_engine=PreTradeRiskEngine(),
            clock=FixedClock(EVALUATED_AT),
            market_policy=_policy(),
            policy_verifier=policy_verifier(),
            risk_inputs_for_request=lambda request: None,
            expected_account_id=ACCOUNT,
        )
        _expect_build_error(database, config, "authority identity inputs require")
    finally:
        database.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_account_id", None),
        ("expected_account_id", "acct-1"),
        ("expected_connection_id", None),
        ("expected_connection_id", "conn-1"),
        ("expected_client_id", None),
        ("expected_client_id", ""),
        ("expected_client_id", "   "),
        ("expected_client_id", 1),
        ("expected_transport", None),
    ],
)
def test_build_rejects_incomplete_authority_identity(tmp_path, field, value) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        config = _authority_config(_source(), **{field: value})
        with pytest.raises(LiveExecutionCompositionError):
            build_live_execution(_runtime(database), config)
        assert SqliteTradingGateStateStore(database).load() is None
    finally:
        database.close()


def test_build_rejects_a_duck_typed_source(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        _expect_build_error(
            database,
            _authority_config(object()),
            "risk_evidence_source must implement LiveRiskEvidenceSource",
        )
    finally:
        database.close()


def test_build_returns_a_disarmed_gate_for_authority_mode(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        stack = build_live_execution(_runtime(database), _authority_config(_source()))

        assert stack.gate.state().enabled is False
    finally:
        database.close()


# Complete authority evidence.


def test_complete_authority_evidence_executes_through_the_fake_broker(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        source = _source()
        stack = build_live_execution(_runtime(database), _authority_config(source))
        stack.gate.enable()
        broker = FakeBroker()
        request = _request()

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.EXECUTED
        assert result.receipt is not None
        assert source.calls == 1
        assert broker.submit_calls == 1
        decision = SqliteUnitOfWork(database).idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending is False
        assert decision.existing_receipt_id == result.receipt.receipt_id
        assert (
            SqliteSubmissionQuarantineRepository(database).list_by_client_order(
                request.order.client_order_id
            )
            == ()
        )
    finally:
        database.close()


def test_authority_rejects_a_market_order_without_a_reference_price(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        evidence = _evidence(
            context=_live_context(reference_price=None),
            reference_price=None,
        )
        stack = build_live_execution(
            _runtime(database),
            _authority_config(_source(evidence_factory=lambda request: evidence)),
        )
        stack.gate.enable()
        broker = FakeBroker()
        request = _request(order_type=OrderType.MARKET, limit_price=None)

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "order value cannot be determined" in result.reason
        _assert_no_submission_side_effects(database, request, broker)
    finally:
        database.close()


# Every unknown authority path stops before reservation, quarantine, or submit.


@pytest.mark.parametrize(
    ("overrides", "clock", "code"),
    [
        ({"source_id": "foreign-source"}, None, _IDENTITY),
        ({"broker_client_id": "foreign-client"}, None, _IDENTITY),
        ({"account_id": AccountId("acct-foreign")}, None, _IDENTITY),
        ({"broker_connection_id": BrokerConnectionId("conn-foreign")}, None, _IDENTITY),
        ({"transport": object()}, None, _IDENTITY),
        ({"identity_observed_at": None}, None, _INCOMPLETE),
        ({"unavailable_fields": (LiveRiskEvidenceField.DAILY_PNL,)}, None, _INCOMPLETE),
        ({"contradictions": ("funds client identity mismatch",)}, None, _CONTRADICTION),
        (
            {"context": _live_context(portfolio_id=PortfolioId("portfolio-foreign"))},
            None,
            _REQUEST,
        ),
        ({"context": _live_context(reference_price=Decimal("101"))}, None, _REQUEST),
        ({"snapshot": _snapshot(required_margin=Decimal("999"))}, None, _REQUEST),
        ({"snapshot": _snapshot(available_margin=Decimal("99999"))}, None, _REQUEST),
        (
            {"observations": _observations(EVALUATED_AT + timedelta(seconds=1))},
            None,
            _FUTURE,
        ),
        ({}, EVALUATED_AT + timedelta(minutes=6), _STALE),
    ],
    ids=[
        "source-id",
        "client-id",
        "account-id",
        "connection-id",
        "transport",
        "identity-missing",
        "field-unavailable",
        "contradiction",
        "context-portfolio",
        "context-reference-price",
        "snapshot-required-margin",
        "snapshot-available-margin",
        "future",
        "stale",
    ],
)
def test_built_stack_blocks_every_unknown_authority_path(tmp_path, overrides, clock, code) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        evidence = _evidence(**overrides)
        stack = build_live_execution(
            _runtime(database),
            _authority_config(
                _source(evidence_factory=lambda request: evidence),
                clock=FixedClock(clock) if clock is not None else None,
            ),
        )
        stack.gate.enable()
        broker = FakeBroker()
        request = _request()

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert code in result.reason
        assert stack.gate.state().enabled is True
        _assert_no_submission_side_effects(database, request, broker)
    finally:
        database.close()


def test_built_stack_blocks_a_missing_required_observation(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        observations = dict(_observations())
        del observations[LiveRiskEvidenceField.DAILY_PNL]
        evidence = _evidence(observations=observations)
        stack = build_live_execution(
            _runtime(database),
            _authority_config(_source(evidence_factory=lambda request: evidence)),
        )
        stack.gate.enable()
        broker = FakeBroker()
        request = _request()

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert _INCOMPLETE in result.reason
        _assert_no_submission_side_effects(database, request, broker)
    finally:
        database.close()


def test_built_stack_blocks_a_source_exception(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        stack = build_live_execution(
            _runtime(database),
            _authority_config(_source(error=RuntimeError("transport failure"))),
        )
        stack.gate.enable()
        broker = FakeBroker()
        request = _request()

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert _EVIDENCE_UNAVAILABLE in result.reason
        assert "transport failure" not in result.reason
        _assert_no_submission_side_effects(database, request, broker)
    finally:
        database.close()


def test_built_stack_blocks_a_non_evidence_source_result(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        stack = build_live_execution(
            _runtime(database),
            _authority_config(_source(evidence_factory=lambda request: None)),
        )
        stack.gate.enable()
        broker = FakeBroker()
        request = _request()

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert _EVIDENCE_UNAVAILABLE in result.reason
        _assert_no_submission_side_effects(database, request, broker)
    finally:
        database.close()


def test_built_stack_never_consults_a_callback_that_claims_authority(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:

        def forbidden(request: ApprovedExecutionRequest) -> LiveRiskEvaluationInputs:
            raise AssertionError("callback mode must not be consulted for LIVE admission")

        stack = build_live_execution(_runtime(database), _callback_config(forbidden))
        stack.gate.enable()
        broker = FakeBroker()
        request = _request()

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert _SOURCE_UNAVAILABLE in result.reason
        _assert_no_submission_side_effects(database, request, broker)
    finally:
        database.close()


# Dhan cannot authorize LIVE.


class _CountingDhanTransport(InMemoryDhanTransport):
    def __init__(self, **overrides) -> None:
        super().__init__(**overrides)
        self.profile_reads = 0

    def profile(self, *, timeout: float = 10.0):
        self.profile_reads += 1
        return super().profile(timeout=timeout)


def _dhan_transport(**overrides) -> _CountingDhanTransport:
    values: dict = {
        "profile_client_id": CLIENT,
        "funds_client_id": CLIENT,
        "funds_sod_limit": Decimal("10000"),
        "funds_available_balance": Decimal("5000"),
        "funds_utilized_amount": Decimal("1200"),
        "funds_blocked_payout_amount": Decimal("0"),
        "position_snapshots": (
            DhanPositionSnapshot(
                security_id="1333",
                exchange_segment="NSE_EQ",
                net_quantity=Decimal("10"),
                average_price=Decimal("100"),
                client_id=CLIENT,
                buy_quantity=Decimal("10"),
                sell_quantity=Decimal("0"),
            ),
        ),
        "holding_snapshots": (),
    }
    values.update(overrides)
    return _CountingDhanTransport(**values)


def _dhan_source(transport: _CountingDhanTransport) -> DhanRiskEvidenceSource:
    return DhanRiskEvidenceSource(
        transport=transport,
        account_id=ACCOUNT,
        broker_connection_id=CONNECTION,
        broker_client_id=CLIENT,
        instruments=((_india_instrument(), DhanInstrumentRef("1333", "NSE_EQ", "TCS")),),
    )


def test_dhan_source_declares_daily_pnl_equity_and_high_water_mark_unsupported() -> None:
    source = _dhan_source(_dhan_transport())

    assert LiveRiskEvidenceField.DAILY_PNL not in source.supported_fields
    assert LiveRiskEvidenceField.EQUITY not in source.supported_fields
    assert LiveRiskEvidenceField.HIGH_WATER_MARK not in source.supported_fields


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {
            "funds_sod_limit": None,
            "funds_available_balance": None,
            "funds_utilized_amount": None,
            "funds_blocked_payout_amount": None,
        },
    ],
    ids=["complete-dhan-account", "incomplete-dhan-account"],
)
def test_built_stack_blocks_the_dhan_source_before_collection(tmp_path, overrides) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        transport = _dhan_transport(**overrides)
        stack = build_live_execution(
            _runtime(database),
            _authority_config(
                _dhan_source(transport),
                expected_transport=transport,
            ),
        )
        stack.gate.enable()
        broker = FakeBroker()
        request = _request()

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert _SOURCE_UNAVAILABLE in result.reason
        assert transport.profile_reads == 0
        assert stack.gate.state().enabled is True
        _assert_no_submission_side_effects(database, request, broker)
    finally:
        database.close()
