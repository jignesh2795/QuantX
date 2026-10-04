"""R0-C regression tests: recovery realism for account/position evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.application.evidence_refresh import DefinitiveEvidencePolicy
from quantx.application.operator_resolution import resolve_pending_operator
from quantx.application.pending_reconciliation import reconcile_pending_execution
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
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.integrations.reconciliation import (
    AccountFinancialState,
    OrderObservation,
    PositionState,
    StateSource,
)
from quantx.persistence.sqlite import SqliteDatabase, SqliteUnitOfWork
from quantx.plugins.dhan import DhanBrokerAdapter, DhanInstrumentRef, InMemoryDhanTransport
from quantx.plugins.dhan.models import DhanPositionSnapshot
from quantx.plugins.dhan.recovery import build_dhan_recovery_provider

CHECKED_AT = datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)
RESOLVED_AT = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)


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
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _observation(order_id, status, *, filled="0") -> OrderObservation:
    return OrderObservation(
        order_id,
        status,
        "2",
        filled,
        "dhan-test-order",
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
    )


def _local_position(*, quantity="10", observed_at=CHECKED_AT) -> PositionState:
    return PositionState(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        "NSE:TCS",
        Decimal(quantity),
        Decimal("100"),
        observed_at,
        StateSource.PAPER,
    )


def _local_account(
    *, cash="5000", margin="1200", observed_at=CHECKED_AT
) -> AccountFinancialState:
    return AccountFinancialState(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        observed_at,
        StateSource.PAPER,
        "INR",
        available_cash=Decimal(cash),
        margin_used=Decimal(margin),
    )


def _fill(request) -> Fill:
    return Fill(
        client_order_id=request.order.client_order_id,
        instrument=request.order.instrument,
        side=request.order.side,
        quantity=Decimal("2"),
        price=Decimal("100"),
        filled_at=CHECKED_AT,
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


def _target_position(*, quantity="10") -> DhanPositionSnapshot:
    return DhanPositionSnapshot("1333", "NSE_EQ", Decimal(quantity), Decimal("100"))


def _stray_position() -> DhanPositionSnapshot:
    return DhanPositionSnapshot("9999", "BSE_EQ", Decimal("5"), None)


def _filled_transport(**overrides) -> InMemoryDhanTransport:
    kwargs = {
        "response_status": "TRADED",
        "filled_quantity": Decimal("2"),
        "average_traded_price": Decimal("100"),
        "position_snapshots": (_target_position(),),
    }
    kwargs.update(overrides)
    return InMemoryDhanTransport(**kwargs)


def _uow(tmp_path):
    database = SqliteDatabase(tmp_path / "quantx.db")
    return database, SqliteUnitOfWork(database)


def _reserve(unit_of_work, request) -> str:
    fingerprint = request_fingerprint(request)
    unit_of_work.idempotency.reserve_or_get(
        request.order.client_order_id,
        fingerprint,
        PendingExecutionContext.from_request(request, fingerprint),
    )
    return fingerprint


def _provider(adapter, request):
    fingerprint = request_fingerprint(request)
    recovery_request = PendingExecutionContext.from_request(
        request, fingerprint
    ).to_recovery_request()
    return build_dhan_recovery_provider(adapter, recovery_request)


def test_cash_delta_does_not_block_recovery(tmp_path) -> None:
    """A: legitimate intraday cash movement still resolves a known order."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        adapter = _adapter(
            _filled_transport(
                funds_available_balance=Decimal("4980"),
                funds_utilized_amount=Decimal("1200"),
            )
        )

        outcome = reconcile_pending_execution(
            request,
            fingerprint=fingerprint,
            local_order=_observation(order_id, OrderLifecycleStatus.FILLED, filled="2"),
            broker_order=None,
            fills=(_fill(request),),
            provider=_provider(adapter, request),
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.live_recovery(),
            local_position=_local_position(),
            local_account=_local_account(),
        )

        assert outcome.definitive
        # Account evidence was still collected and remains visible.
        assert outcome.broker_account is not None
        assert outcome.broker_account.available_cash == Decimal("4980")
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.existing_receipt_id is not None
        assert decision.reservation_pending is False
    finally:
        database.close()


def test_margin_delta_does_not_block_recovery(tmp_path) -> None:
    """B: legitimate margin drift still resolves a known order."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        adapter = _adapter(
            _filled_transport(
                funds_available_balance=Decimal("5000"),
                funds_utilized_amount=Decimal("1350"),
            )
        )

        outcome = reconcile_pending_execution(
            request,
            fingerprint=fingerprint,
            local_order=_observation(order_id, OrderLifecycleStatus.FILLED, filled="2"),
            broker_order=None,
            fills=(_fill(request),),
            provider=_provider(adapter, request),
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.live_recovery(),
            local_position=_local_position(),
            local_account=_local_account(),
        )

        assert outcome.definitive
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.existing_receipt_id is not None
    finally:
        database.close()


def test_contradictory_account_identity_stays_pending(tmp_path) -> None:
    """C: a genuinely contradictory account binding remains fail-closed."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        adapter = _adapter(_filled_transport())
        local_account = AccountFinancialState(
            AccountId("acct-2"),
            BrokerConnectionId("conn-1"),
            CHECKED_AT,
            StateSource.PAPER,
            "INR",
            available_cash=Decimal("5000"),
            margin_used=Decimal("1200"),
        )

        outcome = reconcile_pending_execution(
            request,
            fingerprint=fingerprint,
            local_order=_observation(order_id, OrderLifecycleStatus.FILLED, filled="2"),
            broker_order=None,
            fills=(_fill(request),),
            provider=_provider(adapter, request),
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.live_recovery(),
            local_position=_local_position(),
            local_account=local_account,
        )

        assert not outcome.definitive
        assert any("account" in reason for reason in outcome.result.reasons)
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.reservation_pending is True
        assert decision.existing_receipt_id is None
    finally:
        database.close()


def test_strict_policy_still_rejects_cash_delta(tmp_path) -> None:
    """Advisory treatment is opt-in: all_required keeps exact matching."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        adapter = _adapter(_filled_transport(funds_available_balance=Decimal("4980")))

        outcome = reconcile_pending_execution(
            request,
            fingerprint=fingerprint,
            local_order=_observation(order_id, OrderLifecycleStatus.FILLED, filled="2"),
            broker_order=None,
            fills=(_fill(request),),
            provider=_provider(adapter, request),
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.all_required(),
            local_position=_local_position(),
            local_account=_local_account(),
        )

        assert not outcome.definitive
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.reservation_pending is True
    finally:
        database.close()


def test_stray_position_does_not_block_target_recovery(tmp_path) -> None:
    """D (adversarial): unmapped stray book entry cannot block the target."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        transport = _filled_transport(
            position_snapshots=(_target_position(), _stray_position())
        )
        adapter = _adapter(transport)

        # The strict whole-book listing still refuses the unmapped symbol.
        with pytest.raises(ValueError, match="no canonical instrument mapping"):
            adapter.position_states()

        outcome = reconcile_pending_execution(
            request,
            fingerprint=fingerprint,
            local_order=_observation(order_id, OrderLifecycleStatus.FILLED, filled="2"),
            broker_order=None,
            fills=(_fill(request),),
            provider=_provider(adapter, request),
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.order_and_position(),
            local_position=_local_position(),
        )

        assert outcome.definitive
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.existing_receipt_id is not None
        assert transport.submitted == ()
    finally:
        database.close()


def test_target_position_mismatch_still_blocks(tmp_path) -> None:
    """E: a quantity mismatch on the target instrument stays fail-closed."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        adapter = _adapter(_filled_transport(position_snapshots=(_target_position(),)))

        outcome = reconcile_pending_execution(
            request,
            fingerprint=fingerprint,
            local_order=_observation(order_id, OrderLifecycleStatus.FILLED, filled="2"),
            broker_order=None,
            fills=(_fill(request),),
            provider=_provider(adapter, request),
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.order_and_position(),
            local_position=_local_position(quantity="4"),
        )

        assert not outcome.definitive
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.reservation_pending is True
        assert decision.existing_receipt_id is None
    finally:
        database.close()


def test_target_position_evidence_is_authoritative(tmp_path) -> None:
    """F: target lookup returns exact broker values despite stray entries."""
    adapter = _adapter(
        _filled_transport(position_snapshots=(_target_position(), _stray_position()))
    )
    provider = _provider(adapter, _request())

    state = provider.fetch_broker_position(
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        instrument_id="NSE:TCS",
    )

    assert state is not None
    assert state.quantity == Decimal("10")
    assert state.average_price == Decimal("100")
    assert state.instrument_id == "NSE:TCS"
    assert state.account_id == AccountId("acct-1")
    assert state.connection_id == BrokerConnectionId("conn-1")
    assert provider.fetch_broker_position(
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        instrument_id="NSE:TCS",
    ) == state


def test_cnc_absence_is_not_delivery_evidence(tmp_path) -> None:
    """G/H: a missing position is absence, never inferred delivery."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        transport = InMemoryDhanTransport(
            response_status="PENDING",
            position_snapshots=(),
        )
        adapter = _adapter(transport)
        provider = _provider(adapter, request)

        # The positions endpoint reports open positions only; delivered
        # holdings are not observed here, so absence stays missing.
        assert (
            provider.fetch_broker_position(
                account_id=AccountId("acct-1"),
                connection_id=BrokerConnectionId("conn-1"),
                instrument_id="NSE:TCS",
            )
            is None
        )
        assert adapter.position_state_for("NSE:TCS") is None

        outcome = reconcile_pending_execution(
            request,
            fingerprint=fingerprint,
            local_order=None,
            broker_order=None,
            provider=provider,
            unit_of_work=unit_of_work,
            checked_at=CHECKED_AT,
            evidence_policy=DefinitiveEvidencePolicy.live_recovery(),
        )

        assert not outcome.definitive
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.reservation_pending is True
        assert decision.existing_receipt_id is None
    finally:
        database.close()


def _runner(unit_of_work, adapter, request, **overrides):
    from quantx.application.pending_recovery import PendingExecutionRecoveryRunner

    fingerprint = request_fingerprint(request)
    context_providers = {
        "local_order_provider": lambda recovered: _observation(
            recovered.order.client_order_id,
            OrderLifecycleStatus.FILLED,
            filled="2",
        ),
        "local_position_provider": lambda recovered: _local_position(),
        "local_account_provider": lambda recovered: _local_account(),
        "fill_provider": lambda recovered, _: (
            Fill(
                client_order_id=recovered.order.client_order_id,
                instrument=recovered.order.instrument,
                side=recovered.order.side,
                quantity=Decimal("2"),
                price=Decimal("100"),
                filled_at=CHECKED_AT,
            ),
        ),
    }
    context_providers.update(overrides)
    return (
        PendingExecutionRecoveryRunner(
            unit_of_work=unit_of_work,
            provider_resolver=lambda recovered: build_dhan_recovery_provider(
                adapter, recovered
            ),
            **context_providers,
        ),
        fingerprint,
    )


def test_live_recovery_resolves_fully_matching_order(tmp_path) -> None:
    """I/M: end-to-end live recovery resolves, submits nothing, resolves nobody."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        transport = _filled_transport()
        adapter = _adapter(transport)
        runner, _ = _runner(unit_of_work, adapter, request)

        run = runner.run(checked_at=CHECKED_AT)

        assert run.resolved == 1
        from quantx.persistence.sqlite import SqliteReceiptRepository

        persisted = SqliteReceiptRepository(database).get_by_client_order(order_id)
        assert persisted is not None
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.existing_receipt_id == persisted.receipt_id
        assert transport.submitted == ()
        assert unit_of_work.idempotency.get_operator_resolution(order_id, fingerprint) is None
    finally:
        database.close()


def test_unknown_evidence_leaves_pending_without_resolution(tmp_path) -> None:
    """J/M: non-definitive recovery writes neither receipt nor resolution."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)

        class FailingTransport(InMemoryDhanTransport):
            def reconcile(self, correlation_id: str, *, timeout: float):
                raise RuntimeError("broker unreachable")

        adapter = _adapter(FailingTransport())
        runner, _ = _runner(
            unit_of_work,
            adapter,
            request,
            local_order_provider=lambda recovered: None,
            local_position_provider=lambda recovered: None,
            local_account_provider=lambda recovered: None,
            fill_provider=lambda recovered, _: (),
        )
        run = runner.run(checked_at=CHECKED_AT)

        assert run.attempted == 1
        assert run.resolved == 0
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.reservation_pending is True
        from quantx.persistence.sqlite import SqliteReceiptRepository

        assert SqliteReceiptRepository(database).get_by_client_order(order_id) is None
        assert unit_of_work.idempotency.get_operator_resolution(order_id, fingerprint) is None
    finally:
        database.close()


def test_recovery_excludes_operator_resolved(tmp_path) -> None:
    """K: operator-resolved reservations never re-enter recovery."""
    database, unit_of_work = _uow(tmp_path)
    try:
        request = _request()
        order_id = request.order.client_order_id
        fingerprint = _reserve(unit_of_work, request)
        resolve_pending_operator(
            unit_of_work=unit_of_work,
            client_order_id=order_id,
            request_fingerprint=fingerprint,
            operator_id="ops-1",
            reason="broker never received this",
            resolved_at=RESOLVED_AT,
        )
        transport = _filled_transport()
        runner, _ = _runner(unit_of_work, _adapter(transport), request)
        run = runner.run(checked_at=CHECKED_AT)

        assert run.attempted == 0
        decision = unit_of_work.idempotency.check(order_id, fingerprint)
        assert decision.operator_resolved is True
        assert transport.submitted == ()
    finally:
        database.close()
