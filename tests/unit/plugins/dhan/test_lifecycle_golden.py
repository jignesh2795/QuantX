"""Golden Dhan-to-canonical-lifecycle coverage for the QX-03 acceptance proof.

Each Dhan vendor status is exercised end to end through the same fixture:
``normalize_status`` (operation outcome plus canonical order status), the
``DhanBrokerAdapter.reconcile`` receipt (with all identity/quantity guards),
the shared ``ExecutionLifecycle`` reducer, and the recovery-observation
path. Outcome and status are asserted as distinct dimensions.
"""

from __future__ import annotations

from decimal import Decimal

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import AssetClass, OrderSide, OrderStatus, OrderType, TimeInForce
from quantx.domain.execution_request import (
    ApprovedExecutionRequest,
    PendingExecutionRecoveryRequest,
    build_order_from_intent,
)
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
from quantx.execution.order_lifecycle import OrderLifecycle, OrderLifecycleEvent
from quantx.execution.receipts.lifecycle import ExecutionLifecycle
from quantx.execution.receipts.models import (
    ExecutionEvidenceKind,
    ExecutionOutcome,
    ExecutionReceipt,
)
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.integrations.reconciliation.broker_evidence import BrokerOrderEvidenceStatus
from quantx.plugins.dhan.adapter import DhanBrokerAdapter
from quantx.plugins.dhan.mapping import normalize_status
from quantx.plugins.dhan.models import DhanInstrumentRef
from quantx.plugins.dhan.recovery import build_dhan_recovery_provider
from quantx.plugins.dhan.transport import DhanTransport, InMemoryDhanTransport

# (Dhan status, operation outcome, canonical order status, cumulative observed
# filled quantity). Dhan's filledQty is a cumulative broker observation, so the
# last column is consumed as ``observed_filled_quantity`` on a
# CUMULATIVE_OBSERVATION receipt, never as additive ``fills``.
_GOLDEN = (
    ("TRANSIT", "ACCEPTED", OrderStatus.SUBMITTED, Decimal("0")),
    ("PENDING", "ACCEPTED", OrderStatus.ACCEPTED, Decimal("0")),
    ("PART_TRADED", "PARTIALLY_FILLED", OrderStatus.PARTIALLY_FILLED, Decimal("1")),
    ("TRADED", "FILLED", OrderStatus.FILLED, Decimal("2")),
    ("REJECTED", "REJECTED", OrderStatus.REJECTED, Decimal("0")),
    ("CANCELLED", "CANCELLED", OrderStatus.CANCELLED, Decimal("0")),
    ("EXPIRED", "EXPIRED", OrderStatus.EXPIRED, Decimal("0")),
)


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
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _adapter(transport: DhanTransport) -> DhanBrokerAdapter:
    instrument = _instrument()
    return DhanBrokerAdapter(
        _connection=BrokerConnectionRef(
            AccountId("acct-1"),
            BrokerConnectionId("conn-1"),
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
        _transport=transport,
        _submit_timeout=5.0,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
    )


def _recovery_request(request: ApprovedExecutionRequest) -> PendingExecutionRecoveryRequest:
    return PendingExecutionRecoveryRequest(
        order=request.order,
        execution_context=request.execution_context,
        parent_client_order_id=request.parent_client_order_id,
    )


def _transport_for(status: str, filled: Decimal) -> InMemoryDhanTransport:
    return InMemoryDhanTransport(
        response_status=status,
        filled_quantity=filled,
        average_traded_price=Decimal("101") if filled > 0 else None,
    )


def _assert_receipt_guards(receipt: ExecutionReceipt, request: ApprovedExecutionRequest) -> None:
    assert receipt.client_order_id == request.order.client_order_id
    assert receipt.correlation_id == request.correlation_id
    assert receipt.order_id == request.order.client_order_id
    assert receipt.order_quantity == request.order.quantity
    assert receipt.account_id == request.execution_context.account_id
    assert receipt.connection_id == request.execution_context.broker_connection_id
    assert receipt.source == "dhan"
    assert receipt.simulated is False


def test_normalize_status_golden_table() -> None:
    for dhan_status, outcome, status, _ in _GOLDEN:
        mapped_outcome, mapped_status = normalize_status(dhan_status)
        assert mapped_outcome == outcome
        assert mapped_status is status


def test_reconcile_receipt_carries_golden_outcome_and_status() -> None:
    for dhan_status, outcome, status, filled in _GOLDEN:
        request = _request()
        receipt = _adapter(_transport_for(dhan_status, filled)).reconcile(request)

        assert receipt.outcome is ExecutionOutcome(outcome)
        assert receipt.order_status is status
        assert receipt.evidence_kind is ExecutionEvidenceKind.CUMULATIVE_OBSERVATION
        assert receipt.fills == ()
        assert receipt.observed_filled_quantity == filled
        _assert_receipt_guards(receipt, request)


def test_reconciled_status_reduces_into_lifecycle() -> None:
    for dhan_status, _outcome, status, filled in _GOLDEN:
        request = _request()
        receipt = _adapter(_transport_for(dhan_status, filled)).reconcile(request)
        lifecycle = ExecutionLifecycle.rebuild(
            request.order.client_order_id,
            request.order.quantity,
            (receipt,),
        )

        assert lifecycle.filled_quantity == filled
        assert lifecycle.observed_filled_quantity == filled
        assert lifecycle.status is status


def test_partial_fill_then_cancel_retains_fill_without_continuation() -> None:
    # Dhan's filledQty is cumulative on every detail observation. Feed both
    # adapter observations through one lifecycle using cumulative quantities;
    # the second observation must not add the same fill a second time.
    request = _request()
    transport = _transport_for("PART_TRADED", Decimal("1"))
    adapter = _adapter(transport)
    partial = adapter.reconcile(request)

    assert partial.order_status is OrderStatus.PARTIALLY_FILLED
    assert partial.evidence_kind is ExecutionEvidenceKind.CUMULATIVE_OBSERVATION
    assert partial.fills == ()
    assert partial.observed_filled_quantity == Decimal("1")
    _assert_receipt_guards(partial, request)

    transport.response_status = "CANCELLED"
    cancelled = adapter.reconcile(request)

    assert cancelled.order_status is OrderStatus.CANCELLED
    assert cancelled.outcome is ExecutionOutcome.CANCELLED
    assert cancelled.evidence_kind is ExecutionEvidenceKind.CUMULATIVE_OBSERVATION
    assert cancelled.fills == ()
    assert cancelled.observed_filled_quantity == Decimal("1")
    _assert_receipt_guards(cancelled, request)

    # Both receipts are cumulative observations of total filled so far, so the
    # authoritative cancellation observation preserves the broker-reported
    # partial fill while resolving the unfilled remainder.
    receipt_lifecycle = ExecutionLifecycle.rebuild(
        request.order.client_order_id,
        request.order.quantity,
        (cancelled,),
    )
    assert receipt_lifecycle.status is OrderStatus.CANCELLED
    assert receipt_lifecycle.filled_quantity == Decimal("1")
    assert receipt_lifecycle.remaining_quantity == Decimal("1")
    assert receipt_lifecycle.is_complete
    assert not receipt_lifecycle.can_continue
    assert not receipt_lifecycle.requires_reconciliation

    # OrderLifecycle is the documented event facade over the shared canonical
    # reducer. These events carry the broker's cumulative observed quantity
    # directly, so replaying the observation does not add quantity unless the
    # broker reports an increase.
    lifecycle = OrderLifecycle(request.order.client_order_id)
    lifecycle.apply(
        OrderLifecycleEvent(
            order_id=request.order.client_order_id,
            status=OrderStatus.SUBMITTED,
            observed_at=partial.executed_at,
            source="dhan",
        )
    )
    for receipt in (partial, cancelled):
        lifecycle.reconcile(
            OrderLifecycleEvent(
                order_id=request.order.client_order_id,
                status=receipt.order_status,
                observed_at=receipt.executed_at,
                source=receipt.source,
                order_quantity=request.order.quantity,
                filled_quantity=receipt.observed_filled_quantity,
            )
        )

    assert lifecycle.status is OrderStatus.CANCELLED
    assert lifecycle.filled_quantity == Decimal("1")
    assert lifecycle.order_quantity == Decimal("2")
    assert lifecycle.order_quantity - lifecycle.filled_quantity == Decimal("1")
    assert not lifecycle.requires_reconciliation
    assert not lifecycle.anomalies


def test_recovery_observation_matches_adapter_status() -> None:
    for dhan_status, _outcome, status, filled in _GOLDEN:
        request = _request()
        transport = _transport_for(dhan_status, filled)
        provider = build_dhan_recovery_provider(_adapter(transport), _recovery_request(request))
        evidence = provider.fetch_broker_order(
            account_id=AccountId("acct-1"),
            connection_id=BrokerConnectionId("conn-1"),
            order_id=request.order.client_order_id,
        )

        assert evidence.status is BrokerOrderEvidenceStatus.FOUND
        assert evidence.observation is not None
        assert evidence.observation.status is status
        assert Decimal(evidence.observation.filled_quantity) == filled


def test_unsupported_vendor_status_stays_unknown_and_not_definitive() -> None:
    request = _request()
    receipt = _adapter(_transport_for("BOGUS_STATUS", Decimal("0"))).reconcile(request)

    assert receipt.outcome is ExecutionOutcome.UNKNOWN
    assert receipt.order_status is OrderStatus.UNKNOWN

    lifecycle = ExecutionLifecycle.rebuild(
        request.order.client_order_id,
        request.order.quantity,
        (receipt,),
    )

    assert lifecycle.status is OrderStatus.UNKNOWN
    assert lifecycle.requires_reconciliation
    assert not lifecycle.is_complete
    assert not lifecycle.can_continue
