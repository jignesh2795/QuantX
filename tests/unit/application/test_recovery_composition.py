"""Tests for production recovery startup composition and identity binding."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.application.pending_recovery import PendingExecutionRecoveryRunner
from quantx.application.recovery_composition import (
    RecoveryEndpointResolver,
    ResolvedRecoveryEndpoint,
    build_application_runtime,
)
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderType, TimeInForce
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Fill
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.idempotency import PendingExecutionContext
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.order_lifecycle import OrderLifecycleStatus
from quantx.integrations.account_registry import AccountConnectionRegistry, RegisteredConnection
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.integrations.reconciliation import (
    AccountFinancialState,
    OrderObservation,
    PositionState,
    StateSource,
)
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteIdempotencyStore,
    SqliteReceiptRepository,
    SqliteUnitOfWork,
)
from quantx.plugins.dhan.adapter import DhanBrokerAdapter
from quantx.plugins.dhan.models import DhanInstrumentRef, DhanPositionSnapshot
from quantx.plugins.dhan.recovery import build_dhan_recovery_provider
from quantx.plugins.dhan.transport import InMemoryDhanTransport

CHECKED_AT = datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)


def _instrument() -> Instrument:
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _context(account: str = "acct-1", connection: str = "conn-1") -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId(account),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=_instrument().market,
        broker_connection_id=BrokerConnectionId(connection),
        execution_mode=ExecutionMode.LIVE,
    )


def _approved(
    account: str = "acct-1",
    connection: str = "conn-1",
    quantity: str = "2",
) -> ApprovedExecutionRequest:
    context = _context(account, connection)
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal(quantity),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        build_order_from_intent(intent),
        context,
        RiskResult(RiskDecision.APPROVE, "approved"),
        PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _dhan_adapter(
    account: str = "acct-1",
    connection: str = "conn-1",
    transport: InMemoryDhanTransport | None = None,
) -> DhanBrokerAdapter:
    instrument = _instrument()
    return DhanBrokerAdapter(
        _connection=BrokerConnectionRef(
            AccountId(account),
            BrokerConnectionId(connection),
            "dhan",
            "NSE_EQ",
        ),
        _instruments={
            instrument.instrument_id: (
                instrument,
                DhanInstrumentRef(
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    trading_symbol="TCS",
                    product_type="CNC",
                ),
            )
        },
        _transport=transport or InMemoryDhanTransport(),
    )


def _register(registry: AccountConnectionRegistry, adapter: DhanBrokerAdapter) -> None:
    registry.register(RegisteredConnection(adapter.connection, adapter))


def _recovery_request(approved: ApprovedExecutionRequest):
    fingerprint = request_fingerprint(approved)
    return PendingExecutionContext.from_request(approved, fingerprint).to_recovery_request()


def _reserve(tmp_path, approved: ApprovedExecutionRequest):
    database = SqliteDatabase(tmp_path / "quantx.db")
    unit_of_work = SqliteUnitOfWork(database)
    fingerprint = request_fingerprint(approved)
    unit_of_work.idempotency.reserve_or_get(
        approved.order.client_order_id,
        fingerprint,
        PendingExecutionContext.from_request(approved, fingerprint),
    )
    return database, unit_of_work, fingerprint


def _local_order(approved: ApprovedExecutionRequest) -> OrderObservation:
    return OrderObservation(
        approved.order.client_order_id,
        OrderLifecycleStatus.FILLED,
        "2",
        "2",
        broker_order_id="dhan-test-order",
        account_id=approved.execution_context.account_id,
        connection_id=approved.execution_context.broker_connection_id,
    )


def _local_position(approved: ApprovedExecutionRequest) -> PositionState:
    return PositionState(
        approved.execution_context.account_id,
        approved.execution_context.broker_connection_id,
        "NSE:TCS",
        Decimal("10"),
        Decimal("100"),
        CHECKED_AT,
        StateSource.PAPER,
    )


def _local_account(approved: ApprovedExecutionRequest) -> AccountFinancialState:
    return AccountFinancialState(
        approved.execution_context.account_id,
        approved.execution_context.broker_connection_id,
        CHECKED_AT,
        StateSource.PAPER,
        "INR",
        available_cash=Decimal("5000"),
        margin_used=Decimal("1200"),
    )


def _fills(approved: ApprovedExecutionRequest) -> tuple[Fill, ...]:
    return (
        Fill(
            client_order_id=approved.order.client_order_id,
            instrument=approved.order.instrument,
            side=approved.order.side,
            quantity=Decimal("2"),
            price=Decimal("100"),
            filled_at=CHECKED_AT,
        ),
    )


def _filled_transport() -> InMemoryDhanTransport:
    return InMemoryDhanTransport(
        response_status="TRADED",
        filled_quantity=Decimal("2"),
        average_traded_price=Decimal("100"),
        position_snapshots=(
            DhanPositionSnapshot(
                security_id="1333",
                exchange_segment="NSE_EQ",
                net_quantity=Decimal("10"),
                average_price=Decimal("100"),
            ),
        ),
    )


def test_resolves_exact_registered_endpoint() -> None:
    registry = AccountConnectionRegistry()
    adapter = _dhan_adapter()
    _register(registry, adapter)
    resolver = RecoveryEndpointResolver(registry, build_dhan_recovery_provider)

    endpoint = resolver.resolve(_recovery_request(_approved()))

    assert isinstance(endpoint, ResolvedRecoveryEndpoint)
    assert endpoint.account_id == AccountId("acct-1")
    assert endpoint.connection_id == BrokerConnectionId("conn-1")
    assert endpoint.broker_id == "dhan"
    assert endpoint.adapter is adapter
    assert endpoint.evidence_provider.account_id == AccountId("acct-1")
    assert endpoint.evidence_provider.connection_id == BrokerConnectionId("conn-1")


def test_wrong_account_rejected() -> None:
    registry = AccountConnectionRegistry()
    _register(registry, _dhan_adapter(account="acct-2", connection="conn-1"))
    resolver = RecoveryEndpointResolver(registry, build_dhan_recovery_provider)

    with pytest.raises(ValueError, match="account"):
        resolver.resolve(_recovery_request(_approved(account="acct-1", connection="conn-1")))


def test_wrong_connection_rejected() -> None:
    registry = AccountConnectionRegistry()
    _register(registry, _dhan_adapter(connection="conn-2"))
    resolver = RecoveryEndpointResolver(registry, build_dhan_recovery_provider)

    with pytest.raises(ValueError, match="unknown broker connection"):
        resolver.resolve(_recovery_request(_approved(connection="conn-1")))


def test_unknown_connection_rejected_without_submission() -> None:
    transport = InMemoryDhanTransport()
    registry = AccountConnectionRegistry()
    resolver = RecoveryEndpointResolver(
        registry, lambda adapter, request: build_dhan_recovery_provider(adapter, request)
    )

    with pytest.raises(ValueError, match="unknown broker connection"):
        resolver.resolve(_recovery_request(_approved()))

    assert transport.submitted == ()
    assert transport.cancelled == ()


def test_unknown_broker_rejected() -> None:
    registry = AccountConnectionRegistry()
    _register(registry, _dhan_adapter())
    resolver = RecoveryEndpointResolver(
        registry, build_dhan_recovery_provider, expected_broker_id="bogus-broker"
    )

    with pytest.raises(ValueError, match="broker"):
        resolver.resolve(_recovery_request(_approved()))


def test_disabled_connection_rejected() -> None:
    registry = AccountConnectionRegistry()
    adapter = _dhan_adapter()
    registry.register(RegisteredConnection(adapter.connection, adapter, enabled=False))
    resolver = RecoveryEndpointResolver(registry, build_dhan_recovery_provider)

    with pytest.raises(ValueError, match="disabled"):
        resolver.resolve(_recovery_request(_approved()))


def test_multiple_accounts_select_exact_connection() -> None:
    registry = AccountConnectionRegistry()
    first = _dhan_adapter(account="acct-1", connection="conn-1")
    second = _dhan_adapter(account="acct-2", connection="conn-2")
    _register(registry, first)
    _register(registry, second)
    resolver = RecoveryEndpointResolver(registry, build_dhan_recovery_provider)

    endpoint = resolver.resolve(_recovery_request(_approved(account="acct-2", connection="conn-2")))

    assert endpoint.adapter is second
    assert endpoint.connection_id == BrokerConnectionId("conn-2")


def test_persisted_connection_controls_selection_not_registration_order() -> None:
    registry = AccountConnectionRegistry()
    first_registered = _dhan_adapter(connection="conn-1")
    second_registered = _dhan_adapter(connection="conn-2")
    _register(registry, first_registered)
    _register(registry, second_registered)
    resolver = RecoveryEndpointResolver(registry, build_dhan_recovery_provider)

    endpoint = resolver.resolve(_recovery_request(_approved(connection="conn-2")))

    assert endpoint.adapter is second_registered
    assert endpoint.adapter is not first_registered


def test_recovery_performs_no_broker_submission(tmp_path) -> None:
    approved = _approved()
    database, unit_of_work = _reserve(tmp_path, approved)[0:2]
    try:
        transport = InMemoryDhanTransport()
        registry = AccountConnectionRegistry()
        _register(registry, _dhan_adapter(transport=transport))
        runner = PendingExecutionRecoveryRunner(
            unit_of_work=unit_of_work,
            provider_resolver=RecoveryEndpointResolver(
                registry, build_dhan_recovery_provider
            ).resolve_provider,
        )

        run = runner.run(checked_at=CHECKED_AT)

        assert run.pending == 1
        assert run.failed == 0
        assert transport.submitted == ()
        assert transport.cancelled == ()
    finally:
        database.close()


def test_successful_authoritative_recovery(tmp_path) -> None:
    approved = _approved()
    database, unit_of_work = _reserve(tmp_path, approved)[0:2]
    try:
        transport = _filled_transport()
        registry = AccountConnectionRegistry()
        _register(registry, _dhan_adapter(transport=transport))
        runner = PendingExecutionRecoveryRunner(
            unit_of_work=unit_of_work,
            provider_resolver=RecoveryEndpointResolver(
                registry, build_dhan_recovery_provider
            ).resolve_provider,
            local_order_provider=lambda request: _local_order(approved),
            local_position_provider=lambda request: _local_position(approved),
            local_account_provider=lambda request: _local_account(approved),
            fill_provider=lambda request, local_order: _fills(approved),
        )

        run = runner.run(checked_at=CHECKED_AT)

        assert run.resolved == 1
        assert transport.submitted == ()
        persisted = SqliteReceiptRepository(database).get_by_client_order(
            approved.order.client_order_id
        )
        assert persisted is not None
        decision = SqliteIdempotencyStore(database).check(
            approved.order.client_order_id, request_fingerprint(approved)
        )
        assert decision.existing_receipt_id == persisted.receipt_id
    finally:
        database.close()


def test_non_definitive_evidence_remains_pending(tmp_path) -> None:
    approved = _approved()
    database, unit_of_work, fingerprint = _reserve(tmp_path, approved)
    try:
        registry = AccountConnectionRegistry()
        _register(registry, _dhan_adapter())
        runner = PendingExecutionRecoveryRunner(
            unit_of_work=unit_of_work,
            provider_resolver=RecoveryEndpointResolver(
                registry, build_dhan_recovery_provider
            ).resolve_provider,
        )

        run = runner.run(checked_at=CHECKED_AT)

        assert run.pending == 1
        decision = SqliteIdempotencyStore(database).check(
            approved.order.client_order_id, fingerprint
        )
        assert decision.reservation_pending
        assert decision.existing_receipt_id is None
    finally:
        database.close()


def test_bad_context_does_not_corrupt_good_context(tmp_path) -> None:
    good = _approved()
    bad = _approved(connection="conn-unknown")
    database, unit_of_work = _reserve(tmp_path, good)[0:2]
    try:
        fingerprint = request_fingerprint(bad)
        unit_of_work.idempotency.reserve_or_get(
            bad.order.client_order_id,
            fingerprint,
            PendingExecutionContext.from_request(bad, fingerprint),
        )
        registry = AccountConnectionRegistry()
        transport = _filled_transport()
        _register(registry, _dhan_adapter(transport=transport))
        runner = PendingExecutionRecoveryRunner(
            unit_of_work=unit_of_work,
            provider_resolver=RecoveryEndpointResolver(
                registry, build_dhan_recovery_provider
            ).resolve_provider,
            local_order_provider=lambda request: _local_order(good),
            local_position_provider=lambda request: _local_position(good),
            local_account_provider=lambda request: _local_account(good),
            fill_provider=lambda request, local_order: _fills(good),
        )

        run = runner.run(checked_at=CHECKED_AT)

        assert run.resolved == 1
        assert run.failed == 1
        persisted = SqliteReceiptRepository(database).get_by_client_order(
            good.order.client_order_id
        )
        assert persisted is not None
    finally:
        database.close()


def test_startup_composition_runs_recovery_exactly_once(tmp_path) -> None:
    approved = _approved()
    database, unit_of_work = _reserve(tmp_path, approved)[0:2]
    try:
        registry = AccountConnectionRegistry()
        _register(registry, _dhan_adapter(transport=_filled_transport()))
        calls: list = []

        def factory(adapter, request):
            calls.append(request)
            return build_dhan_recovery_provider(adapter, request)

        runtime = build_application_runtime(
            unit_of_work=unit_of_work,
            registry=registry,
            evidence_factory=factory,
            expected_broker_id="dhan",
            local_order_provider=lambda request: _local_order(approved),
            local_position_provider=lambda request: _local_position(approved),
            local_account_provider=lambda request: _local_account(approved),
            fill_provider=lambda request, local_order: _fills(approved),
        )

        result = runtime.start(checked_at=CHECKED_AT)

        assert runtime.started
        assert result.recovered == 1
        assert len(calls) == 1
        with pytest.raises(RuntimeError, match="already started"):
            runtime.start(checked_at=CHECKED_AT)
        assert len(calls) == 1
    finally:
        database.close()


def test_process_recreation_resolves_pending_context(tmp_path) -> None:
    approved = _approved()
    path = tmp_path / "quantx.db"
    database_a = SqliteDatabase(path)
    try:
        unit_of_work_a = SqliteUnitOfWork(database_a)
        fingerprint = request_fingerprint(approved)
        unit_of_work_a.idempotency.reserve_or_get(
            approved.order.client_order_id,
            fingerprint,
            PendingExecutionContext.from_request(approved, fingerprint),
        )
    finally:
        database_a.close()

    database_b = SqliteDatabase(path)
    try:
        registry = AccountConnectionRegistry()
        _register(registry, _dhan_adapter(transport=_filled_transport()))
        runtime = build_application_runtime(
            unit_of_work=SqliteUnitOfWork(database_b),
            registry=registry,
            evidence_factory=build_dhan_recovery_provider,
            local_order_provider=lambda request: _local_order(approved),
            local_position_provider=lambda request: _local_position(approved),
            local_account_provider=lambda request: _local_account(approved),
            fill_provider=lambda request, local_order: _fills(approved),
        )

        result = runtime.start(checked_at=CHECKED_AT)

        assert result.recovered == 1
        persisted = SqliteReceiptRepository(database_b).get_by_client_order(
            approved.order.client_order_id
        )
        assert persisted is not None
    finally:
        database_b.close()
