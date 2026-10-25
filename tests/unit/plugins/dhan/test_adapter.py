from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
from quantx.application.pending_recovery import PendingRecoveryRun
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
    PositionEffect,
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
from quantx.domain.product_selection import ProductSelectionResolution
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import ProductCode
from quantx.execution.idempotency import NotSubmittedSource
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.receipts.models import (
    ExecutionEvidenceKind,
    ExecutionOutcome,
    ExecutionReceipt,
)
from quantx.execution.receipts.quarantine import QuarantineObservationKind
from quantx.execution.submission_preflight import BrokerPreflightRejected
from quantx.execution.trading_gate import DurableTradingGate
from quantx.india.domain import IndianExchange, IndianSegment
from quantx.india.execution_rules import IndiaRuleDecision, IndiaRuleResult
from quantx.india.market_checks import india_market_policy
from quantx.india.session_calendar import (
    IndiaSessionDecision,
    IndiaSessionPermission,
    IndiaSessionResult,
)
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteSubmissionQuarantineRepository,
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)
from quantx.plugins.dhan import (
    DhanBrokerAdapter,
    DhanInstrumentRef,
    InMemoryDhanTransport,
)
from quantx.plugins.dhan.mapping import dhan_correlation_id
from quantx.plugins.dhan.models import (
    DhanFundsSnapshot,
    DhanOrderRequest,
    DhanOrderResponse,
    DhanPositionsSnapshot,
)
from tests.unit._execution_request_proofs import approved_request, policy_verifier

_DEFAULT_PRODUCT = ProductCode("CNC")


def _instrument() -> Instrument:
    return Instrument(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def _request(
    *,
    mode: ExecutionMode = ExecutionMode.LIVE,
    order_type: OrderType = OrderType.MARKET,
    time_in_force: TimeInForce = TimeInForce.DAY,
    product: ProductCode | None = _DEFAULT_PRODUCT,
    position_effect: PositionEffect | None = PositionEffect.OPEN,
) -> ApprovedExecutionRequest:
    instrument = _instrument()
    pack_identity = {"market_pack_id": "india-equity", "rule_version": "india-products-v1"}
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=mode,
        **pack_identity,
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        order_type=order_type,
        time_in_force=time_in_force,
        limit_price=Decimal("100") if order_type is OrderType.LIMIT else None,
        stop_price=Decimal("99") if order_type in {OrderType.STOP, OrderType.STOP_LIMIT} else None,
        required_capabilities=frozenset({"ORDER_SUBMISSION"}),
        product=product,
        position_effect=position_effect,
        execution_context=context,
    )
    order = build_order_from_intent(intent)
    if product is None:
        # A request that never resolved a product: it carries no product and
        # no product proof, so the adapter's own product guard is what must
        # reject it before any transport call.
        return ApprovedExecutionRequest(
            order=order,
            execution_context=context,
            risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
            policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
            position_effect=position_effect,
        )
    return approved_request(
        order=order,
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        product=product,
        position_effect=position_effect,
    )


def _approving_india_evaluator():
    """India layer is not under test here; approve explicitly to reach it."""

    def approve(request) -> IndiaRuleResult:
        return IndiaRuleResult(
            IndiaRuleDecision.APPROVE,
            "india compatibility approved for test",
            rule_set_version="test-b3",
            provenance="test-b3",
            evaluated_at=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
            compatibility_evaluated=True,
        )

    return approve


def _approving_india_session_evaluator():
    """B4 boundary is not under test here; provide explicit session evidence."""

    def allow(request) -> IndiaSessionResult:
        return IndiaSessionResult(
            IndiaSessionDecision.ALLOW,
            "india session approved for test",
            calendar_version="test-calendar-v1",
            provenance="test-calendar",
            evaluated_at=datetime(2026, 1, 5, 10, 0, tzinfo=UTC),
            exchange=IndianExchange.NSE,
            segment=IndianSegment.EQUITY,
            session_id="regular",
            granted_permissions=frozenset({IndiaSessionPermission.ORDER_SUBMISSION}),
            calendar_evaluated=True,
        )

    return allow


def _approving_live_risk_evaluator():
    """LIVE pre-trade risk is not under test here; approve explicitly."""

    def approve(request) -> RiskResult:
        return RiskResult(RiskDecision.APPROVE, "approved for test")

    return approve


def _started_runtime() -> ApplicationRuntime:
    class NoopRecovery:
        def run(self, *, checked_at=None) -> PendingRecoveryRun:
            return PendingRecoveryRun()

    runtime = ApplicationRuntime(pending_recovery=NoopRecovery())
    runtime.start(checked_at=datetime(2026, 1, 1, tzinfo=UTC))
    return runtime


_PRODUCT_MAP = {"CNC": "CNC", "MIS": "INTRADAY", "NRML": "MARGIN"}


def _adapter(
    transport: InMemoryDhanTransport | None = None,
    *,
    product_map: dict[str, str] | None = _PRODUCT_MAP,
) -> DhanBrokerAdapter:
    instrument = _instrument()
    connection = BrokerConnectionRef(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        "dhan",
        "NSE_EQ",
    )
    return DhanBrokerAdapter(
        _connection=connection,
        _instruments={
            instrument.instrument_id: (
                instrument,
                DhanInstrumentRef(
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    trading_symbol="TCS",
                ),
            )
        },
        _transport=transport or InMemoryDhanTransport(),
        _submit_timeout=5.0,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
        _product_map=product_map,
    )


def test_submit_translates_to_dhan_and_returns_normalized_receipt() -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    request = _request()
    receipt = _adapter(transport).submit(request)

    assert isinstance(receipt, ExecutionReceipt)
    assert receipt.outcome is ExecutionOutcome.ACCEPTED
    assert receipt.order_status is OrderStatus.ACCEPTED
    assert receipt.source == "dhan"
    assert receipt.simulated is False
    assert receipt.broker_order_id == "dhan-test-order"
    assert receipt.correlation_id == request.correlation_id
    assert transport.submitted[0].security_id == "1333"
    assert transport.submitted[0].exchange_segment == "NSE_EQ"
    assert transport.submitted[0].product_type == "CNC"
    assert transport.submitted[0].correlation_id == dhan_correlation_id(request.correlation_id)


def test_submit_uses_resolved_request_product() -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    receipt = _adapter(transport).submit(_request(product=ProductCode("MIS")))

    assert receipt.outcome is ExecutionOutcome.ACCEPTED
    assert transport.submitted[0].product_type == "INTRADAY"


def test_distinct_products_produce_distinct_wire_values_and_fingerprints() -> None:
    first = _request(product=ProductCode("CNC"))
    second = _request(product=ProductCode("MIS"))
    first_transport = InMemoryDhanTransport(response_status="PENDING")
    second_transport = InMemoryDhanTransport(response_status="PENDING")

    _adapter(first_transport).submit(first)
    _adapter(second_transport).submit(second)

    assert first_transport.submitted[0].product_type == "CNC"
    assert second_transport.submitted[0].product_type == "INTRADAY"
    assert request_fingerprint(first) != request_fingerprint(second)


def test_explicit_product_requires_configured_mapping_before_transport() -> None:
    transport = InMemoryDhanTransport()

    with pytest.raises(BrokerPreflightRejected, match="unsupported product"):
        _adapter(transport, product_map=None).submit(_request(product=ProductCode("MIS")))

    assert not transport.submitted


def _request_with_unauthenticated_product(product: ProductCode) -> ApprovedExecutionRequest:
    """Build a request whose product claim no versioned pack supports.

    The market pack rejects such a product before execution, so the request
    is written directly here: the adapter's own product guard must still
    refuse it before any transport call.
    """
    instrument = _instrument()
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
        market_pack_id="india-equity",
        rule_version="india-products-v1",
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        required_capabilities=frozenset({"ORDER_SUBMISSION"}),
        product=product,
        position_effect=PositionEffect.OPEN,
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        product=product,
        position_effect=PositionEffect.OPEN,
        product_resolution=ProductSelectionResolution(
            market=instrument.market,
            product=product,
            market_pack_id="india-equity",
            rule_version="india-products-v1",
        ),
    )


def test_submit_rejects_unsupported_product_before_transport() -> None:
    transport = InMemoryDhanTransport()

    with pytest.raises(BrokerPreflightRejected, match="unsupported product"):
        _adapter(transport).submit(_request_with_unauthenticated_product(ProductCode("MTF")))

    assert not transport.submitted


def test_request_without_resolved_product_is_rejected_before_transport() -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")

    with pytest.raises(BrokerPreflightRejected, match="resolved product"):
        _adapter(transport).submit(_request(product=None))

    assert not transport.submitted


def test_instrument_reference_carries_no_product_default() -> None:
    assert not hasattr(_adapter()._instruments[_instrument().instrument_id][1], "product_type")


def test_submit_rejects_wrong_account_for_bound_connection() -> None:
    request = _request()
    wrong_context = replace(
        request.execution_context,
        account_id=AccountId("other-account"),
    )
    wrong_request = replace(request, execution_context=wrong_context)

    with pytest.raises(ValueError, match="account"):
        _adapter().submit(wrong_request)


def test_submit_rejects_wrong_connection_for_bound_connection() -> None:
    request = _request()
    wrong_context = replace(
        request.execution_context,
        broker_connection_id=BrokerConnectionId("other-connection"),
    )
    wrong_request = replace(request, execution_context=wrong_context)

    with pytest.raises(ValueError, match="connection"):
        _adapter().submit(wrong_request)


def test_submit_rejects_unsupported_dhan_validity_before_transport() -> None:
    transport = InMemoryDhanTransport()
    request = _request(time_in_force=TimeInForce.GTC)

    with pytest.raises(ValueError, match="DAY/IOC"):
        _adapter(transport).submit(request)

    assert transport.submitted == ()


def test_reconcile_rejects_mismatched_broker_correlation_id() -> None:
    class MismatchedCorrelationTransport(InMemoryDhanTransport):
        def reconcile(self, correlation_id, *, timeout):  # type: ignore[no-untyped-def]
            detail = super().reconcile(correlation_id, timeout=timeout)
            return replace(detail, correlation_id="some-other-correlation")

    receipt = _adapter(
        MismatchedCorrelationTransport(
            response_status="TRADED",
            filled_quantity=Decimal("2"),
            average_traded_price=Decimal("101"),
        )
    ).reconcile(_request())

    assert receipt.outcome is ExecutionOutcome.UNKNOWN
    assert receipt.order_status is OrderStatus.UNKNOWN
    assert "mismatched correlation" in receipt.message


def test_reconcile_fails_closed_when_broker_omits_correlation_echo() -> None:
    """A success observation without the correlation echo is not bindable evidence."""

    class AbsentCorrelationTransport(InMemoryDhanTransport):
        def reconcile(self, correlation_id, *, timeout):  # type: ignore[no-untyped-def]
            detail = super().reconcile(correlation_id, timeout=timeout)
            return replace(detail, correlation_id=None)

    receipt = _adapter(
        AbsentCorrelationTransport(
            response_status="TRADED",
            filled_quantity=Decimal("2"),
            average_traded_price=Decimal("101"),
        )
    ).reconcile(_request())

    assert receipt.outcome is ExecutionOutcome.UNKNOWN
    assert receipt.order_status is OrderStatus.UNKNOWN
    assert "did not confirm the correlation id" in receipt.message


def test_adapter_receipts_satisfy_live_identity_contract() -> None:
    """Submit, cancel, and reconcile receipts are bound to the approved request."""
    from quantx.execution.receipts.identity import validate_live_receipt_identity

    transport = InMemoryDhanTransport(response_status="PENDING")
    adapter = _adapter(transport)
    request = _request()

    submitted = adapter.submit(request)
    assert validate_live_receipt_identity(request, submitted) is None

    cancelled = adapter.cancel(request)
    assert cancelled.outcome is ExecutionOutcome.CANCELLED
    assert validate_live_receipt_identity(request, cancelled) is None

    reconciled = adapter.reconcile(request)
    assert reconciled.outcome is ExecutionOutcome.ACCEPTED
    assert validate_live_receipt_identity(request, reconciled) is None


def test_reconcile_rejects_fill_above_canonical_order_quantity() -> None:
    transport = InMemoryDhanTransport(
        response_status="TRADED",
        filled_quantity=Decimal("3"),
        average_traded_price=Decimal("101"),
    )

    with pytest.raises(ValueError, match="exceeds canonical order quantity"):
        _adapter(transport).reconcile(_request())


def test_reconcile_rejects_filled_quantity_without_price() -> None:
    transport = InMemoryDhanTransport(
        response_status="TRADED",
        filled_quantity=Decimal("2"),
        average_traded_price=None,
    )

    with pytest.raises(ValueError, match="requires an average traded price"):
        _adapter(transport).reconcile(_request())


def test_reconcile_maps_trade_as_cumulative_observation() -> None:
    transport = InMemoryDhanTransport(
        response_status="TRADED",
        filled_quantity=Decimal("2"),
        average_traded_price=Decimal("101.25"),
    )
    request = _request()
    receipt = _adapter(transport).reconcile(request)

    assert receipt.outcome is ExecutionOutcome.FILLED
    assert receipt.order_status is OrderStatus.FILLED
    # Cumulative observation: no synthetic Fill with a random execution id.
    assert receipt.evidence_kind is ExecutionEvidenceKind.CUMULATIVE_OBSERVATION
    assert receipt.fills == ()
    assert receipt.observed_filled_quantity == Decimal("2")
    # Average traded price retained as observation metadata, not a fill price.
    assert receipt.observed_average_price == Decimal("101.25")


def test_reconcile_preserves_partial_trade_status() -> None:
    transport = InMemoryDhanTransport(
        response_status="PART_TRADED",
        filled_quantity=Decimal("1"),
        average_traded_price=Decimal("101"),
    )
    receipt = _adapter(transport).reconcile(_request())

    assert receipt.outcome is ExecutionOutcome.PARTIALLY_FILLED
    assert receipt.order_status is OrderStatus.PARTIALLY_FILLED
    assert receipt.evidence_kind is ExecutionEvidenceKind.CUMULATIVE_OBSERVATION
    assert receipt.fills == ()
    assert receipt.observed_filled_quantity == Decimal("1")
    assert receipt.observed_average_price == Decimal("101")


def test_cancel_uses_dhan_safe_correlation_identifier() -> None:
    transport = InMemoryDhanTransport()
    request = _request()
    receipt = _adapter(transport).cancel(request)

    assert receipt.outcome is ExecutionOutcome.CANCELLED
    assert transport.cancelled == (dhan_correlation_id(request.correlation_id),)


def test_unknown_transport_failure_fails_closed() -> None:
    class FailingTransport(InMemoryDhanTransport):
        def submit(self, request, *, timeout):  # type: ignore[no-untyped-def]
            raise RuntimeError("network unavailable")

    receipt = _adapter(FailingTransport()).submit(_request())

    assert receipt.outcome is ExecutionOutcome.UNKNOWN
    assert receipt.order_status is OrderStatus.UNKNOWN
    assert "network unavailable" in receipt.message


def test_unknown_broker_status_maps_to_unknown() -> None:
    receipt = _adapter(InMemoryDhanTransport(response_status="NEW_STATUS")).submit(_request())

    assert receipt.outcome is ExecutionOutcome.UNKNOWN
    assert receipt.order_status is OrderStatus.UNKNOWN


def test_market_segment_mismatch_is_rejected() -> None:
    instrument = _instrument()
    wrong = replace(
        instrument,
        market=MarketContext(
            MarketRegion.INDIA,
            MarketFamily.EQUITY,
            "BSE",
            "IN",
        ),
    )
    connection = BrokerConnectionRef(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        "dhan",
        "BSE_EQ",
    )
    adapter = DhanBrokerAdapter(
        _connection=connection,
        _instruments={
            wrong.instrument_id: (
                wrong,
                DhanInstrumentRef(
                    security_id="1333",
                    exchange_segment="NSE_EQ",
                    trading_symbol="TCS",
                ),
            )
        },
        _transport=InMemoryDhanTransport(),
        _submit_timeout=5.0,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
    )

    with pytest.raises(ValueError, match="market venue"):
        adapter.submit(_request())


def test_dhan_adapter_composes_with_live_execution_orchestrator(tmp_path) -> None:
    adapter = _adapter(InMemoryDhanTransport(response_status="PENDING"))
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        result = ExecutionOrchestrator(
            unit_of_work=SqliteUnitOfWork(database),
            trading_gate=DurableTradingGate(
                SqliteTradingGateStateStore(database), default_enabled=True
            ),
            submission_quarantine=SqliteSubmissionQuarantineRepository(database),
            live_risk_evaluator=_approving_live_risk_evaluator(),
            application_runtime=_started_runtime(),
            market_policy=india_market_policy(
                session_evaluator=_approving_india_session_evaluator(),
                rule_evaluator=_approving_india_evaluator(),
            ),
            policy_verifier=policy_verifier(),
        ).execute(_request(), broker=adapter)
    finally:
        database.close()

    assert result.status is ExecutionDispatchStatus.EXECUTED
    assert result.receipt is not None
    assert result.receipt.source == "dhan"


def test_account_state_produces_canonical_broker_observation() -> None:
    from quantx.integrations.reconciliation import StateSource

    transport = InMemoryDhanTransport(
        funds_available_balance=Decimal("5000"),
        funds_utilized_amount=Decimal("1200"),
    )
    state = _adapter(transport).account_state()

    assert state.account_id == AccountId("acct-1")
    assert state.connection_id == BrokerConnectionId("conn-1")
    assert state.source is StateSource.BROKER
    assert state.currency == "INR"
    assert state.available_cash == Decimal("5000")
    assert state.margin_used == Decimal("1200")
    assert state.equity is None
    assert state.margin_available is None


def test_account_state_missing_funds_remain_none_not_zero() -> None:
    transport = InMemoryDhanTransport(
        funds_available_balance=None,
        funds_utilized_amount=None,
    )
    state = _adapter(transport).account_state()

    assert state.available_cash is None
    assert state.margin_used is None


def test_position_states_map_known_broker_instruments() -> None:
    from quantx.integrations.reconciliation import StateSource
    from quantx.plugins.dhan.models import DhanPositionSnapshot

    transport = InMemoryDhanTransport(
        position_snapshots=(DhanPositionSnapshot("1333", "NSE_EQ", Decimal("10"), Decimal("100")),)
    )
    states = _adapter(transport).position_states()

    assert len(states) == 1
    assert states[0].account_id == AccountId("acct-1")
    assert states[0].connection_id == BrokerConnectionId("conn-1")
    assert states[0].instrument_id == "NSE:TCS"
    assert states[0].quantity == Decimal("10")
    assert states[0].average_price == Decimal("100")
    assert states[0].source is StateSource.BROKER


def test_position_states_with_unmapped_broker_position_fails_closed() -> None:
    from quantx.plugins.dhan.models import DhanPositionSnapshot

    transport = InMemoryDhanTransport(
        position_snapshots=(DhanPositionSnapshot("9999", "BSE_EQ", Decimal("5"), None),)
    )

    with pytest.raises(ValueError, match="no canonical instrument mapping"):
        _adapter(transport).position_states()


def test_position_states_with_unavailable_observation_fails_closed() -> None:
    transport = InMemoryDhanTransport(
        positions_available=False,
        positions_message="network unavailable",
    )

    with pytest.raises(ValueError, match="unavailable"):
        _adapter(transport).position_states()


def test_whole_account_position_evidence_is_fail_closed_and_observes_both_surfaces() -> None:
    from quantx.domain.risk_evidence import EvidenceStatus, PositionSurface
    from quantx.plugins.dhan.models import DhanHoldingSnapshot, DhanPositionSnapshot

    transport = InMemoryDhanTransport(
        position_snapshots=(
            DhanPositionSnapshot(
                "1333",
                "NSE_EQ",
                Decimal("10"),
                Decimal("100"),
                product_type="CNC",
                position_type="LONG",
                multiplier=Decimal("1"),
            ),
        ),
        holding_snapshots=(
            DhanHoldingSnapshot(
                "1333",
                "ALL",
                total_quantity=Decimal("10"),
                average_cost_price=Decimal("100"),
            ),
        ),
    )

    evidence = _adapter(transport).whole_account_position_evidence(
        observed_at=datetime(2026, 1, 1, tzinfo=UTC)
    )

    assert evidence.completeness is EvidenceStatus.INCOMPLETE
    assert evidence.positions == ()
    assert {surface.surface for surface in evidence.surfaces} == {
        PositionSurface.POSITIONS,
        PositionSurface.HOLDINGS,
        PositionSurface.MARKS,
    }
    assert "DHAN_CROSS_SURFACE_OVERLAP_POLICY_UNPROVEN" in evidence.blockers
    assert any(
        blocker.startswith("DHAN_HOLDINGS_VENUE_IDENTITY_UNPROVEN") for blocker in evidence.blockers
    )
    assert not any(
        blocker.startswith("DHAN_CROSS_SURFACE_OVERLAP:") for blocker in evidence.blockers
    )


def test_whole_account_position_evidence_rejects_a_naive_observation_instant() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _adapter().whole_account_position_evidence(observed_at=datetime(2026, 1, 1))


@dataclass(slots=True)
class _TimeoutRecordingTransport:
    """Record read timeouts while delegating to an in-memory transport."""

    seen_timeouts: list[float] = field(default_factory=list)
    _inner: InMemoryDhanTransport = field(default_factory=InMemoryDhanTransport)

    def health(self, *, timeout: float = 10.0) -> bool:
        self.seen_timeouts.append(timeout)
        return self._inner.health(timeout=timeout)

    def fund_limits(self, *, timeout: float = 10.0) -> DhanFundsSnapshot:
        self.seen_timeouts.append(timeout)
        return self._inner.fund_limits(timeout=timeout)

    def positions(self, *, timeout: float = 10.0) -> DhanPositionsSnapshot:
        self.seen_timeouts.append(timeout)
        return self._inner.positions(timeout=timeout)


def test_adapter_threads_configured_read_timeout_to_observations() -> None:
    transport = _TimeoutRecordingTransport()
    adapter = replace(_adapter(transport), _read_timeout=2.5)

    assert adapter.health() is True
    adapter.account_state()
    adapter.position_states()

    assert transport.seen_timeouts == [2.5, 2.5, 2.5]


def test_adapter_read_timeout_defaults_to_bounded_constant() -> None:
    from quantx.plugins.dhan.transport import DEFAULT_READ_TIMEOUT_SECONDS

    transport = _TimeoutRecordingTransport()
    adapter = _adapter(transport)

    assert adapter.health() is True

    assert transport.seen_timeouts == [DEFAULT_READ_TIMEOUT_SECONDS]


def test_adapter_rejects_non_positive_read_timeout() -> None:
    bad_values: tuple[object, ...] = (
        0,
        -1.0,
        True,
        "5",
        float("nan"),
        float("inf"),
        float("-inf"),
    )
    for bad in bad_values:
        with pytest.raises(ValueError, match="_read_timeout"):
            replace(_adapter(), _read_timeout=bad)


def _quarantine_orchestrator(database) -> ExecutionOrchestrator:
    return ExecutionOrchestrator(
        unit_of_work=SqliteUnitOfWork(database),
        trading_gate=DurableTradingGate(
            SqliteTradingGateStateStore(database), default_enabled=True
        ),
        application_runtime=_started_runtime(),
        market_policy=india_market_policy(
            session_evaluator=_approving_india_session_evaluator(),
            rule_evaluator=_approving_india_evaluator(),
        ),
        submission_quarantine=SqliteSubmissionQuarantineRepository(database),
        live_risk_evaluator=_approving_live_risk_evaluator(),
        policy_verifier=policy_verifier(),
    )


def test_dhan_preflight_failure_is_known_not_submitted_with_durable_closure(tmp_path) -> None:
    """A wire-request validation failure before transport is NOT_SUBMITTED.

    The outcome is a known local block with a durably closed reservation —
    never an ambiguous possible external submission, never a fabricated
    human operator decision — and no transport call is made, on the first
    attempt or any replay.
    """
    transport = InMemoryDhanTransport()
    adapter = _adapter(transport)
    path = tmp_path / "quantx.db"
    database = SqliteDatabase(path)
    try:
        unit_of_work = SqliteUnitOfWork(database)
        orchestrator = _quarantine_orchestrator(database)
        request = _request(time_in_force=TimeInForce.GTC)
        fingerprint = request_fingerprint(request)
        result = orchestrator.execute(request, broker=adapter)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "submission was not sent" in result.reason
        assert transport.submitted == ()
        decision = unit_of_work.idempotency.check(request.order.client_order_id, fingerprint)
        assert decision.operator_resolved is False
        assert decision.operator_resolution is None
        assert decision.reservation_pending is False
        resolution = decision.not_submitted_resolution
        assert resolution is not None
        assert resolution.source is NotSubmittedSource.ADAPTER_PREFLIGHT_REJECTION
        assert "DAY/IOC" in resolution.reason
        assert resolution.request_fingerprint == fingerprint
        assert (
            unit_of_work.idempotency.get_operator_resolution(
                request.order.client_order_id, fingerprint
            )
            is None
        )
        pending_ids = {
            record.client_order_id
            for record in unit_of_work.idempotency.list_pending_recovery_records()
        }
        assert str(request.order.client_order_id) not in pending_ids
    finally:
        database.close()

    database_b = SqliteDatabase(path)
    try:
        unit_of_work_b = SqliteUnitOfWork(database_b)
        transport_b = InMemoryDhanTransport()
        orchestrator_b = _quarantine_orchestrator(database_b)
        replay = orchestrator_b.execute(request, broker=_adapter(transport_b))
        assert replay.status is ExecutionDispatchStatus.BLOCKED
        assert "durably closed as not submitted" in replay.reason
        assert transport_b.submitted == ()
        decision_b = unit_of_work_b.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision_b.operator_resolved is False
        assert decision_b.reservation_pending is False
        assert decision_b.not_submitted_resolution is not None
    finally:
        database_b.close()


def test_dhan_transport_failure_after_send_is_unknown_quarantined_and_not_retried(tmp_path) -> None:
    """A transport failure after submission may have begun stays UNKNOWN.

    The uncertainty is quarantined for reconciliation, the reservation
    stays pending, and no replay automatically resubmits.
    """

    class MidFlightFailureTransport(InMemoryDhanTransport):
        def __init__(self) -> None:
            super().__init__()
            self.submit_attempts = 0

        def submit(self, request: DhanOrderRequest, *, timeout: float) -> DhanOrderResponse:
            self.submit_attempts += 1
            raise RuntimeError("connection reset mid-flight")

    transport = MidFlightFailureTransport()
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        unit_of_work = SqliteUnitOfWork(database)
        quarantine = SqliteSubmissionQuarantineRepository(database)
        orchestrator = _quarantine_orchestrator(database)
        adapter = _adapter(transport)
        request = _request()
        result = orchestrator.execute(request, broker=adapter)

        # The Dhan adapter normalizes a mid-flight transport failure into an
        # UNKNOWN receipt; the orchestrator reports uncertainty and keeps
        # that receipt out of the canonical store.
        assert result.status is ExecutionDispatchStatus.UNKNOWN
        assert result.receipt is not None
        assert result.receipt.outcome is ExecutionOutcome.UNKNOWN
        assert "broker returned an UNKNOWN receipt" in result.reason
        assert transport.submit_attempts == 1
        assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
        observations = quarantine.list_by_client_order(request.order.client_order_id)
        assert len(observations) == 1
        assert observations[0].kind is QuarantineObservationKind.BROKER_UNKNOWN
        decision = unit_of_work.idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending

        replay = orchestrator.execute(request, broker=adapter)
        assert replay.status is ExecutionDispatchStatus.UNKNOWN
        assert transport.submit_attempts == 1
    finally:
        database.close()
