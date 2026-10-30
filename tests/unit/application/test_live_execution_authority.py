"""Composition-root slice C: authority-mode LIVE admission through the stack.

These tests exercise the built stack end to end. A complete application-owned
source may reach the existing risk engine and the fake broker, while every
unknown, foreign, incomplete, stale, contradictory, or unavailable evidence
path stops before reservation, quarantine, or submission. The Dhan source is
also pinned here: it cannot authorize LIVE because it cannot supply daily P&L,
complete equity, or a high-water mark.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest

from quantx.application import execution as execution_module
from quantx.application import live_risk as live_risk_module
from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
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
    LiveRiskEvidenceSource,
)
from quantx.application.production import ProductionRuntime
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.clock import FixedClock
from quantx.domain.deployment import PortfolioId
from quantx.domain.enums import OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instruments import InstrumentId, MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.position_effect import PositionEffect
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
from quantx.plugins.dhan.risk_evidence import (
    DHAN_BROKER_ID,
    DhanRiskEvidenceSource,
)
from quantx.plugins.dhan.transport import InMemoryDhanTransport
from tests.unit._execution_request_proofs import approved_request, policy_verifier
from tests.unit.application._live_risk_trust import (
    BROKER_ID,
    registered_connection,
    registry_with,
)
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


def _config(
    *,
    clock=None,
    limits: RiskLimits | None = None,
    expected_account_id: object = ACCOUNT,
    expected_connection_id: object = CONNECTION,
) -> LiveExecutionConfig:
    """Build an authority-mode config; the runtime's adapter supplies the source."""
    return LiveExecutionConfig(
        risk_limits=limits if limits is not None else _limits(),
        risk_engine=PreTradeRiskEngine(),
        clock=clock if clock is not None else FixedClock(EVALUATED_AT),
        market_policy=_policy(),
        policy_verifier=policy_verifier(),
        expected_account_id=expected_account_id,  # type: ignore[arg-type]
        expected_broker_connection_id=expected_connection_id,  # type: ignore[arg-type]
    )


def _live_runtime(
    database: SqliteDatabase,
    *,
    account_id: AccountId = ACCOUNT,
    connection_id: BrokerConnectionId = CONNECTION,
    broker_id: str = BROKER_ID,
    enabled: bool = True,
    source: LiveRiskEvidenceSource | None = None,
    broker_client_id: str = CLIENT,
    transport: object = TRANSPORT,
) -> ProductionRuntime:
    """Build the runtime whose registry registers the exact connection.

    ``source`` is what the registered adapter exposes. Without it the connection
    has no evidence construction path, which is the ordinary registration.
    """
    runtime = _runtime(database)
    return ProductionRuntime(
        database=runtime.database,
        unit_of_work=runtime.unit_of_work,
        registry=registry_with(
            registered_connection(
                account_id=account_id,
                connection_id=connection_id,
                broker_id=broker_id,
                enabled=enabled,
                source=source,
                broker_client_id=broker_client_id,
                transport=transport,
            )
        ),
        application=runtime.application,
    )


def _registered_adapter(
    runtime: ProductionRuntime,
    connection_id: BrokerConnectionId = CONNECTION,
):
    """The exact adapter a sanctioned LIVE stack is allowed to submit through."""
    registered = runtime.registry.get(connection_id)
    assert registered is not None
    return registered.adapter


def _live_stack(
    database: SqliteDatabase,
    *,
    source: LiveRiskEvidenceSource | None = None,
    clock=None,
    limits: RiskLimits | None = None,
    broker_id: str = BROKER_ID,
    broker_client_id: str = CLIENT,
    transport: object = TRANSPORT,
):
    """Build the sanctioned stack plus the exact adapter it may submit through."""
    runtime = _live_runtime(
        database,
        source=source,
        broker_id=broker_id,
        broker_client_id=broker_client_id,
        transport=transport,
    )
    stack = build_live_execution(runtime, _config(clock=clock, limits=limits))
    return stack, _registered_adapter(runtime)


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
        build_live_execution(_live_runtime(database), config)
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


def test_build_rejects_a_missing_or_ambiguous_evidence_mode(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        neither = LiveExecutionConfig(
            risk_limits=_limits(),
            risk_engine=PreTradeRiskEngine(),
            clock=FixedClock(EVALUATED_AT),
            market_policy=_policy(),
            policy_verifier=policy_verifier(),
        )
        _expect_build_error(database, neither, "authority mode requires")

        both = LiveExecutionConfig(
            risk_limits=_limits(),
            risk_engine=PreTradeRiskEngine(),
            clock=FixedClock(EVALUATED_AT),
            market_policy=_policy(),
            policy_verifier=policy_verifier(),
            risk_inputs_for_request=lambda request: None,
            expected_account_id=ACCOUNT,
            expected_broker_connection_id=CONNECTION,
        )
        _expect_build_error(database, both, "rejected in callback mode")
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
        _expect_build_error(database, config, "rejected in callback mode")
    finally:
        database.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_account_id", None),
        ("expected_account_id", "acct-1"),
        ("expected_connection_id", None),
        ("expected_connection_id", "conn-1"),
    ],
)
def test_build_rejects_incomplete_authority_identity(tmp_path, field, value) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        config = _config(**{field: value})
        with pytest.raises(LiveExecutionCompositionError):
            build_live_execution(_live_runtime(database, source=_source()), config)
        assert SqliteTradingGateStateStore(database).load() is None
    finally:
        database.close()


def test_build_rejects_an_unregistered_connection(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        with pytest.raises(
            LiveExecutionCompositionError,
            match="account and broker connection this process registered",
        ):
            build_live_execution(_runtime(database), _config())
        assert SqliteTradingGateStateStore(database).load() is None
    finally:
        database.close()


def test_build_rejects_a_disabled_registered_connection(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        with pytest.raises(
            LiveExecutionCompositionError,
            match="account and broker connection this process registered",
        ):
            build_live_execution(
                _live_runtime(database, enabled=False, source=_source()),
                _config(),
            )
        assert SqliteTradingGateStateStore(database).load() is None
    finally:
        database.close()


def test_build_rejects_a_connection_registered_for_another_account(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        with pytest.raises(
            LiveExecutionCompositionError,
            match="account and broker connection this process registered",
        ):
            build_live_execution(
                _live_runtime(database, source=_source()),
                _config(expected_account_id=AccountId("acct-other")),
            )
        assert SqliteTradingGateStateStore(database).load() is None
    finally:
        database.close()


def test_build_rejects_a_connection_without_an_evidence_construction_path(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        with pytest.raises(
            LiveExecutionCompositionError,
            match="construction path on the registered broker adapter",
        ):
            build_live_execution(_live_runtime(database), _config())
        assert SqliteTradingGateStateStore(database).load() is None
    finally:
        database.close()


def test_build_returns_a_disarmed_gate_for_authority_mode(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        stack = build_live_execution(_live_runtime(database, source=_source()), _config())

        assert stack.gate.state().enabled is False
    finally:
        database.close()


# Complete authority evidence.


def test_complete_authority_evidence_executes_through_the_registered_adapter(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        source = _source()
        stack, broker = _live_stack(database, source=source)
        stack.gate.enable()
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


def test_direct_orchestrator_cannot_bypass_authority_bound_adapter(tmp_path) -> None:
    """A valid evaluator authority must bind dispatch even without factory wiring.

    The old optional live_broker guard was skipped when a caller directly
    constructed an orchestrator with no live_broker argument. The authority's
    registered adapter is the trust anchor even on this construction path, so
    a different broker with matching identifiers must not collect evidence,
    reserve, or submit.
    """
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        source = _source()
        stack, registered = _live_stack(database, source=source)
        stack.gate.enable()
        request = _request()
        impostor = FakeBroker(account_id=ACCOUNT, connection_id=CONNECTION)

        direct = ExecutionOrchestrator(
            trading_gate=stack.gate,
            unit_of_work=stack.orchestrator._unit_of_work,
            application_runtime=stack.orchestrator._application_runtime,
            live_risk_evaluator=stack.orchestrator._live_risk_evaluator,
            # Intentionally omit live_broker: the authority binding must survive
            # direct orchestrator construction.
            market_policy=stack.orchestrator._market_policy,
            submission_quarantine=stack.orchestrator._submission_quarantine,
            policy_verifier=policy_verifier(),
        )

        assert impostor is not registered
        assert impostor.connection.account_id == registered.connection.account_id
        assert impostor.connection.connection_id == registered.connection.connection_id

        result = direct.execute(request, broker=impostor)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "registered broker adapter" in result.reason
        assert source.calls == 0
        assert impostor.submit_calls == 0
        assert result.receipt is None
        assert stack.gate.state().enabled is True
        _assert_no_submission_side_effects(database, request, impostor)
    finally:
        database.close()


def test_transactional_entry_rechecks_authority_bound_adapter(tmp_path) -> None:
    """The private transaction entry point independently enforces adapter identity.

    Mint a valid test authorization for an impostor broker, as the unit-test
    helper can do through the module-private issuer. The transaction boundary
    must still reject it before reserving, collecting evidence, or submitting.
    """
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        source = _source()
        stack, registered = _live_stack(database, source=source)
        stack.gate.enable()
        request = _request()
        impostor = FakeBroker(account_id=ACCOUNT, connection_id=CONNECTION)
        unit_of_work = stack.orchestrator._unit_of_work
        assert unit_of_work is not None

        with execution_module._LIVE_SUBMISSION_AUTHORITIES_LOCK:
            authorizer = execution_module._LIVE_SUBMISSION_AUTHORITIES.get(stack.orchestrator)
        assert authorizer is not None
        authorization = authorizer.issue(
            client_order_id=request.order.client_order_id,
            request_fingerprint=request_fingerprint(request),
            broker_identity=id(impostor),
            unit_of_work_identity=id(unit_of_work),
        )

        assert impostor is not registered
        result = stack.orchestrator._execute_live_transactional(
            request, impostor, unit_of_work, authorization
        )

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "registered broker adapter" in result.reason
        assert source.calls == 0
        assert impostor.submit_calls == 0
        assert result.receipt is None
        assert stack.gate.state().enabled is True
        _assert_no_submission_side_effects(database, request, impostor)
    finally:
        database.close()


def test_authority_rejects_a_market_order_without_a_reference_price(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        evidence = _evidence(
            context=_live_context(reference_price=None),
            reference_price=None,
        )
        stack, broker = _live_stack(
            database, source=_source(evidence_factory=lambda request: evidence)
        )
        stack.gate.enable()
        request = _request(order_type=OrderType.MARKET, limit_price=None)

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "order value cannot be determined" in result.reason
        _assert_no_submission_side_effects(database, request, broker)
    finally:
        database.close()



# Request-binding mismatches are exercised through the sanctioned composition.
# Fault injection makes the application-owned intent builder return one
# contradictory field while keeping the registered fake adapter and complete
# evidence source legitimate. The authority must reject before reservation.

@pytest.mark.parametrize(
    "mismatch_dimension",
    [
        "instrument",
        "side",
        "quantity",
        "order-type",
        "limit-price",
        "account",
        "portfolio",
        "broker-connection",
        "market-context",
        "market-pack",
        "rule-version",
    ],
)
def test_built_stack_rejects_a_risk_intent_mismatch_before_submission(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    mismatch_dimension: str,
) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        source = _source()
        stack, broker = _live_stack(database, source=source)
        stack.gate.enable()
        request = _request()
        original_builder = live_risk_module._intent_for_request

        def _mismatched_intent(
            approved: ApprovedExecutionRequest,
        ) -> TradeIntent | None:
            intent = original_builder(approved)
            if intent is None:
                return None
            if mismatch_dimension == "instrument":
                return replace(intent, instrument=InstrumentId("NSE", "INFY"))
            if mismatch_dimension == "side":
                return replace(intent, side=OrderSide.SELL)
            if mismatch_dimension == "quantity":
                return replace(intent, quantity=Decimal("2"))
            if mismatch_dimension == "order-type":
                return replace(intent, order_type=OrderType.MARKET, limit_price=None)
            if mismatch_dimension == "limit-price":
                return replace(intent, limit_price=Decimal("101"))
            if mismatch_dimension == "account":
                return replace(
                    intent,
                    execution_context=replace(
                        intent.execution_context,
                        account_id=AccountId("acct-foreign"),
                    ),
                )
            if mismatch_dimension == "portfolio":
                return replace(
                    intent,
                    execution_context=replace(
                        intent.execution_context,
                        portfolio_id=PortfolioId("portfolio-foreign"),
                    ),
                )
            if mismatch_dimension == "broker-connection":
                return replace(
                    intent,
                    execution_context=replace(
                        intent.execution_context,
                        broker_connection_id=BrokerConnectionId("conn-foreign"),
                    ),
                )
            if mismatch_dimension == "market-context":
                return replace(
                    intent,
                    execution_context=replace(
                        intent.execution_context,
                        market=MarketContext(
                            MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN"
                        ),
                    ),
                )
            if mismatch_dimension == "market-pack":
                return replace(
                    intent,
                    execution_context=replace(
                        intent.execution_context,
                        market_pack_id="foreign-pack",
                    ),
                )
            if mismatch_dimension == "rule-version":
                return replace(
                    intent,
                    execution_context=replace(
                        intent.execution_context,
                        rule_version="foreign-rules",
                    ),
                )
            raise AssertionError(f"unknown mismatch dimension: {mismatch_dimension}")

        monkeypatch.setattr(
            live_risk_module, "_intent_for_request", _mismatched_intent
        )
        gate_before = stack.gate.state()

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert _REQUEST in result.reason
        assert source.calls == 1
        assert broker.submit_calls == 0
        assert stack.gate.state() == gate_before
        _assert_no_submission_side_effects(database, request, broker)
    finally:
        database.close()


@pytest.mark.parametrize(
    ("mismatch_dimension", "expected_reason"),
    [
        ("instrument", _REQUEST),
        ("market", _REQUEST),
        ("product", _REQUEST),
        ("position-effect", _REQUEST),
        ("market-pack", _REQUEST),
        ("rule-version", _REQUEST),
        ("context-account", _IDENTITY),
        ("context-connection", _IDENTITY),
        ("snapshot-portfolio", _REQUEST),
    ],
)
def test_built_stack_rejects_mismatched_evidence_context_before_submission(
    tmp_path,
    mismatch_dimension: str,
    expected_reason: str,
) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        overrides: dict[str, object] = {}
        if mismatch_dimension == "instrument":
            overrides["context"] = _live_context(
                instrument=replace(
                    _india_instrument(),
                    instrument_id=InstrumentId("NSE", "INFY"),
                    symbol="INFY",
                )
            )
        elif mismatch_dimension == "market":
            overrides["context"] = _live_context(
                instrument=replace(
                    _india_instrument(),
                    market=MarketContext(
                        MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN"
                    ),
                )
            )
        elif mismatch_dimension == "product":
            overrides["context"] = _live_context(product=ProductCode("MIS"))
        elif mismatch_dimension == "position-effect":
            overrides["context"] = _live_context(
                effective_position_effect=PositionEffect.OPEN
            )
        elif mismatch_dimension == "market-pack":
            overrides["context"] = _live_context(market_pack_id="foreign-pack")
        elif mismatch_dimension == "rule-version":
            overrides["context"] = _live_context(rule_version="foreign-rules")
        elif mismatch_dimension == "context-account":
            overrides["context"] = _live_context(
                account_id=AccountId("acct-foreign")
            )
        elif mismatch_dimension == "context-connection":
            overrides["context"] = _live_context(
                broker_connection_id=BrokerConnectionId("conn-foreign")
            )
        elif mismatch_dimension == "snapshot-portfolio":
            overrides["snapshot"] = _snapshot(
                portfolio_id=PortfolioId("portfolio-foreign")
            )
        else:
            raise AssertionError(f"unknown mismatch dimension: {mismatch_dimension}")

        evidence = _evidence(**overrides)
        source = _source(evidence_factory=lambda _request: evidence)
        stack, broker = _live_stack(database, source=source)
        stack.gate.enable()
        request = _request()
        gate_before = stack.gate.state()

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert expected_reason in result.reason
        assert source.calls == 1
        assert broker.submit_calls == 0
        assert stack.gate.state() == gate_before
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
        stack, broker = _live_stack(
            database,
            source=_source(evidence_factory=lambda request: evidence),
            clock=FixedClock(clock) if clock is not None else None,
        )
        stack.gate.enable()
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
        stack, broker = _live_stack(
            database, source=_source(evidence_factory=lambda request: evidence)
        )
        stack.gate.enable()
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
        stack, broker = _live_stack(
            database, source=_source(error=RuntimeError("transport failure"))
        )
        stack.gate.enable()
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
        stack, broker = _live_stack(database, source=_source(evidence_factory=lambda request: None))
        stack.gate.enable()
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

        stack = build_live_execution(_live_runtime(database), _callback_config(forbidden))
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
        stack, broker = _live_stack(
            database, source=_dhan_source(transport), broker_id=DHAN_BROKER_ID
        )
        stack.gate.enable()
        request = _request()

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert _SOURCE_UNAVAILABLE in result.reason
        assert transport.profile_reads == 0
        assert stack.gate.state().enabled is True
        _assert_no_submission_side_effects(database, request, broker)
    finally:
        database.close()
