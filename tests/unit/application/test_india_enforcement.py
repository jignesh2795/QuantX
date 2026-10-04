"""R1-B1 integration: India rules gate LIVE submission before reservation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
from quantx.application.runtime import ApplicationRuntime
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
    OrderStatus,
    OrderType,
    TimeInForce,
)
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
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.execution.trading_gate import DurableTradingGate
from quantx.india.domain import (
    IndianExchange,
    IndianInstrumentSpec,
    IndianSegment,
    ProductType,
)
from quantx.india.execution_rules import (
    IndiaExecutionRuleEngine,
    IndiaRuleDecision,
    IndiaRuleResult,
)
from quantx.india.rule_data import (
    IndiaRuleScope,
    IndiaVenueRuleSnapshot,
    PriceBandRuleSnapshot,
)
from quantx.india.session_calendar import (
    IndiaSessionDecision,
    IndiaSessionPermission,
    IndiaSessionResult,
)
from quantx.integrations.brokers import (
    BrokerConnectionRef,
    CapabilitySet,
)
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteReceiptRepository,
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)
from quantx.plugins.dhan import DhanBrokerAdapter, DhanInstrumentRef, InMemoryDhanTransport

CHECKED_AT = datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)


def _market() -> MarketContext:
    return MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def _instrument() -> Instrument:
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        _market(),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _spec(**overrides) -> IndianInstrumentSpec:
    values: dict = {
        "instrument_id": InstrumentId("NSE", "TCS"),
        "symbol": "TCS",
        "asset_class": AssetClass.EQUITY,
        "exchange": IndianExchange.NSE,
        "segment": IndianSegment.EQUITY,
    }
    values.update(overrides)
    return IndianInstrumentSpec(**values)


def _request() -> ApprovedExecutionRequest:
    instrument = _instrument()
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        required_capabilities=frozenset({"ORDER_SUBMISSION"}),
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "upstream approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _adapter(transport: InMemoryDhanTransport) -> DhanBrokerAdapter:
    instrument = _instrument()
    return DhanBrokerAdapter(
        _connection=BrokerConnectionRef(
            AccountId("acct-1"), BrokerConnectionId("conn-1"), "dhan", "NSE_EQ"
        ),
        _instruments={
            instrument.instrument_id: (
                instrument,
                DhanInstrumentRef("1333", "NSE_EQ", "TCS", "CNC"),
            )
        },
        _transport=transport,
        _submit_timeout=5.0,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
    )


def _started_runtime() -> ApplicationRuntime:
    class NoopRecovery:
        def run(self, *, checked_at=None):
            from quantx.application.pending_recovery import PendingRecoveryRun
            return PendingRecoveryRun()

    runtime = ApplicationRuntime(pending_recovery=NoopRecovery())
    runtime.start(checked_at=None)
    return runtime


def _evaluator(specs=None, product: ProductType | None = ProductType.CNC):
    table = specs if specs is not None else {InstrumentId("NSE", "TCS"): _spec()}

    def run(request: ApprovedExecutionRequest) -> IndiaRuleResult:
        spec = table.get(request.order.instrument)
        if spec is None:
            return IndiaRuleResult(
                IndiaRuleDecision.REJECT,
                "INDIA_SEGMENT_INVALID: no Indian market specification "
                "for the requested instrument",
            )
        return IndiaExecutionRuleEngine().validate(spec, request.order, product=product)

    return run


def _approving_india_session_evaluator():
    def allow(request) -> IndiaSessionResult:
        return IndiaSessionResult(
            IndiaSessionDecision.ALLOW,
            "india session approved for test",
            calendar_version="test-calendar-v1",
            provenance="test-calendar",
            evaluated_at=CHECKED_AT,
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
            session_id="regular",
            granted_permissions=frozenset({IndiaSessionPermission.ORDER_SUBMISSION}),
            calendar_evaluated=True,
        )

    return allow


def _orchestrator(database, unit_of_work, **overrides) -> ExecutionOrchestrator:
    overrides.setdefault(
        "india_session_evaluator", _approving_india_session_evaluator()
    )
    return ExecutionOrchestrator(
        unit_of_work=unit_of_work,
        trading_gate=DurableTradingGate(SqliteTradingGateStateStore(database)),
        application_runtime=_started_runtime(),
        **overrides,
    )


def test_india_live_without_session_calendar_fails_closed(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = _orchestrator(
            database,
            SqliteUnitOfWork(database),
            india_session_evaluator=None,
        )
        result = orchestrator.execute(_request(), broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "India session calendar" in result.reason
        assert transport.submitted == ()
    finally:
        database.close()


def test_india_live_closed_session_blocks_before_india_rules(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        calls = []

        def closed_session(request) -> IndiaSessionResult:
            return IndiaSessionResult(
                IndiaSessionDecision.BLOCK,
                "india trading session is closed",
                calendar_version="test-calendar-v1",
                provenance="test-calendar",
                evaluated_at=CHECKED_AT,
                exchange=IndianExchange.NSE,
                segment=IndianSegment.EQUITY,
                session_id=None,
                calendar_evaluated=True,
            )

        def must_not_run(request) -> IndiaRuleResult:
            calls.append(request)
            raise AssertionError("B3 rules must not run when the India session is closed")

        orchestrator = _orchestrator(
            database,
            SqliteUnitOfWork(database),
            india_session_evaluator=closed_session,
            india_rule_evaluator=must_not_run,
        )
        result = orchestrator.execute(_request(), broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "session/calendar blocked" in result.reason
        assert calls == []
        assert transport.submitted == ()
    finally:
        database.close()


def test_india_rejection_blocks_before_reservation_and_submit(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        unit_of_work = SqliteUnitOfWork(database)
        orchestrator = _orchestrator(
            database,
            unit_of_work,
            india_rule_evaluator=_compat_evaluator(
                _venue_rules(),
                product=ProductType.CNC,
                spec=_spec(lot_size=Decimal("25")),
            ),
        )
        request = _request()
        result = orchestrator.execute(request, broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "INDIA_LOT_SIZE_INVALID" in result.reason
        assert transport.submitted == ()
        fingerprint = request_fingerprint(request)
        with SqliteUnitOfWork(database) as check_uow:
            decision = check_uow.idempotency.check(request.order.client_order_id, fingerprint)
            assert decision.reservation_pending is False
            assert decision.existing_receipt_id is None
            assert decision.operator_resolved is False
        assert SqliteReceiptRepository(database).get_by_client_order(
            request.order.client_order_id
        ) is None
        assert unit_of_work.idempotency.get_operator_resolution(
            request.order.client_order_id, fingerprint
        ) is None
    finally:
        database.close()


def test_india_live_without_evaluator_fails_closed(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        unit_of_work = SqliteUnitOfWork(database)
        orchestrator = _orchestrator(database, unit_of_work)
        request = _request()
        result = orchestrator.execute(request, broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "india rule evaluator" in result.reason
        assert transport.submitted == ()
        fingerprint = request_fingerprint(request)
        with SqliteUnitOfWork(database) as check_uow:
            decision = check_uow.idempotency.check(request.order.client_order_id, fingerprint)
            assert decision.reservation_pending is False
            assert decision.existing_receipt_id is None
            assert decision.operator_resolved is False
        assert SqliteReceiptRepository(database).get_by_client_order(
            request.order.client_order_id
        ) is None
        assert unit_of_work.idempotency.get_operator_resolution(
            request.order.client_order_id, fingerprint
        ) is None
    finally:
        database.close()


def test_india_approval_keeps_submission_reachable(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = _orchestrator(
            database,
            SqliteUnitOfWork(database),
            india_rule_evaluator=_compat_evaluator(),
        )
        result = orchestrator.execute(_request(), broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.EXECUTED
        assert len(transport.submitted) == 1
    finally:
        database.close()


def test_upstream_approve_cannot_bypass_india_rules(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = _orchestrator(
            database,
            SqliteUnitOfWork(database),
            india_rule_evaluator=_compat_evaluator(
                _venue_rules(
                    scope=IndiaRuleScope(
                        exchange=IndianExchange.NSE,
                        segment=IndianSegment.DERIVATIVES,
                    )
                ),
                product=ProductType.CNC,
                spec=_spec(segment=IndianSegment.DERIVATIVES),
            ),
        )
        request = _request()
        assert request.risk_result.decision is RiskDecision.APPROVE
        result = orchestrator.execute(request, broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "INDIA_SEGMENT_INVALID" in result.reason
        assert transport.submitted == ()
    finally:
        database.close()


def test_failing_india_evaluator_fails_closed(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        def exploding(request) -> IndiaRuleResult:
            raise RuntimeError("spec catalog unavailable")

        orchestrator = _orchestrator(
            database, SqliteUnitOfWork(database), india_rule_evaluator=exploding
        )
        result = orchestrator.execute(_request(), broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "failed closed" in result.reason
        assert transport.submitted == ()
    finally:
        database.close()


def test_india_rejection_precedes_risk_evaluation(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        def permissive_risk(request):
            return RiskResult(RiskDecision.APPROVE, "risk approved")

        orchestrator = _orchestrator(
            database,
            SqliteUnitOfWork(database),
            india_rule_evaluator=_compat_evaluator(
                _venue_rules(quantity_freeze=Decimal("1")),
                product=ProductType.CNC,
                spec=_spec(lot_size=Decimal("25")),
            ),
            live_risk_evaluator=permissive_risk,
        )
        result = orchestrator.execute(_request(), broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "INDIA_LOT_SIZE_INVALID" in result.reason
        assert transport.submitted == ()
    finally:
        database.close()


class UsBroker:
    def __init__(self, instrument) -> None:
        self.submit_calls = 0
        self._instrument = instrument
        self._connection = BrokerConnectionRef(
            AccountId("acct-1"), BrokerConnectionId("conn-1"), "us", "NYSE"
        )

    @property
    def connection(self):
        return self._connection

    def health(self) -> bool:
        return True

    def capabilities(self):
        return CapabilitySet(frozenset())

    def instrument(self, instrument_id):
        return self._instrument if instrument_id == self._instrument.instrument_id else None

    def submit(self, request):
        from uuid import uuid4

        self.submit_calls += 1
        return ExecutionReceipt(
            request_id=uuid4(),
            client_order_id=request.order.client_order_id,
            outcome=ExecutionOutcome.ACCEPTED,
            order_status=OrderStatus.ACCEPTED,
            executed_at=request.order.created_at,
            simulated=False,
            source="us-broker",
            account_id=self._connection.account_id,
            connection_id=self._connection.connection_id,
        )


def _us_request() -> tuple[ApprovedExecutionRequest, Instrument]:
    us_market = MarketContext(MarketRegion.NORTH_AMERICA, MarketFamily.EQUITY, "NYSE", "US")
    us_instrument = Instrument(
        InstrumentId("NYSE", "AAPL"),
        "AAPL",
        AssetClass.EQUITY,
        us_market,
        "USD",
        Decimal("0.01"),
        Decimal("1"),
    )
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=us_market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
    )
    intent = TradeIntent(
        instrument=us_instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        order_type=OrderType.MARKET,
        execution_context=context,
    )
    return (
        ApprovedExecutionRequest(
            order=build_order_from_intent(intent),
            execution_context=context,
            risk_result=RiskResult(RiskDecision.APPROVE, "upstream approved"),
            policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        ),
        us_instrument,
    )


def test_non_india_live_without_evaluator_preserves_legacy_behavior(tmp_path) -> None:
    request, us_instrument = _us_request()
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        broker = UsBroker(us_instrument)
        orchestrator = _orchestrator(database, SqliteUnitOfWork(database))
        result = orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.EXECUTED
        assert broker.submit_calls == 1
    finally:
        database.close()


def _venue_rules(**overrides) -> IndiaVenueRuleSnapshot:
    values: dict = {
        "version": "NSE-EQ-2026-01",
        "provenance": "test-venue-rules",
        "effective_at": datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        "scope": IndiaRuleScope(
            exchange=IndianExchange.NSE, segment=IndianSegment.EQUITY
        ),
        "allowed_order_types": frozenset(
            {OrderType.MARKET, OrderType.LIMIT, OrderType.STOP, OrderType.STOP_LIMIT}
        ),
        "allowed_time_in_force": frozenset({TimeInForce.DAY, TimeInForce.IOC}),
        "allowed_products": frozenset({ProductType.CNC, ProductType.MIS}),
        "quantity_freeze": Decimal("10000"),
        "price_band": PriceBandRuleSnapshot(
            lower_bound=Decimal("90"),
            upper_bound=Decimal("110"),
            rule_type="OPERATING_RANGE",
            effective_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
            source="test-venue",
            version="band-1",
        ),
    }
    values.update(overrides)
    return IndiaVenueRuleSnapshot(**values)


def _compat_evaluator(
    rules=None,
    product: ProductType | None = ProductType.CNC,
    spec: IndianInstrumentSpec | None = None,
):
    snapshot = rules if rules is not None else _venue_rules()
    instrument_spec = spec if spec is not None else _spec()

    def run(request: ApprovedExecutionRequest) -> IndiaRuleResult:
        return IndiaExecutionRuleEngine().validate_compatibility(
            instrument_spec,
            request.order,
            product=product,
            venue_rules=snapshot,
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
        )

    return run


def test_india_live_b1_only_result_cannot_bypass_b3(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = _orchestrator(
            database,
            SqliteUnitOfWork(database),
            india_rule_evaluator=_evaluator(),
        )
        result = orchestrator.execute(_request(), broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "authoritative B3 compatibility evidence" in result.reason
        assert transport.submitted == ()
    finally:
        database.close()


def test_compat_freeze_rejection_blocks_before_reservation(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        unit_of_work = SqliteUnitOfWork(database)
        orchestrator = _orchestrator(
            database,
            unit_of_work,
            india_rule_evaluator=_compat_evaluator(_venue_rules(quantity_freeze=Decimal("1"))),
        )
        request = _request()
        result = orchestrator.execute(request, broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "INDIA_QUANTITY_FREEZE_INVALID" in result.reason
        assert transport.submitted == ()
        fingerprint = request_fingerprint(request)
        with SqliteUnitOfWork(database) as check_uow:
            decision = check_uow.idempotency.check(request.order.client_order_id, fingerprint)
            assert decision.reservation_pending is False
            assert decision.existing_receipt_id is None
        assert SqliteReceiptRepository(database).get_by_client_order(
            request.order.client_order_id
        ) is None
    finally:
        database.close()


def test_compat_missing_rule_data_blocks(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = _orchestrator(
            database,
            SqliteUnitOfWork(database),
            india_rule_evaluator=_compat_evaluator(_venue_rules(quantity_freeze=None)),
        )
        result = orchestrator.execute(_request(), broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "INDIA_RULE_DATA_UNAVAILABLE" in result.reason
        assert transport.submitted == ()
    finally:
        database.close()


def test_compat_approval_reaches_submission(tmp_path) -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        orchestrator = _orchestrator(
            database,
            SqliteUnitOfWork(database),
            india_rule_evaluator=_compat_evaluator(),
        )
        result = orchestrator.execute(_request(), broker=_adapter(transport))

        assert result.status is ExecutionDispatchStatus.EXECUTED
        assert len(transport.submitted) == 1
    finally:
        database.close()


def test_non_india_live_skips_configured_india_evaluator(tmp_path) -> None:
    request, us_instrument = _us_request()
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        broker = UsBroker(us_instrument)
        calls: list = []

        def recording_evaluator(evaluated):
            calls.append(evaluated)
            return IndiaRuleResult(IndiaRuleDecision.REJECT, "must not run for US orders")

        orchestrator = _orchestrator(
            database, SqliteUnitOfWork(database), india_rule_evaluator=recording_evaluator
        )
        result = orchestrator.execute(request, broker=broker)

        assert calls == []
        assert result.status is ExecutionDispatchStatus.EXECUTED
        assert broker.submit_calls == 1
    finally:
        database.close()
