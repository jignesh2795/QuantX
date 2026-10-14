from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from quantx.domain.enums import OrderSide, OrderStatus
from quantx.domain.orders import Fill
from quantx.domain.value_objects import InstrumentId
from quantx.execution.receipts import ExecutionOutcome, ExecutionReceipt
from quantx.execution.receipts.lifecycle import ExecutionLifecycle


def test_partial_lifecycle_generates_deterministic_continuation_identity() -> None:
    order_id = uuid4()
    lifecycle = ExecutionLifecycle(
        order_id,
        Decimal("10"),
        filled_quantity=Decimal("4"),
        status=OrderStatus.PARTIALLY_FILLED,
    )
    assert lifecycle.continuation_client_order_id(
        Decimal("6")
    ) == lifecycle.continuation_client_order_id(Decimal("6"))


def test_continuation_identity_changes_after_new_fill() -> None:
    order_id = uuid4()
    first = ExecutionLifecycle(order_id, Decimal("10"), Decimal("4"), OrderStatus.PARTIALLY_FILLED)
    second = ExecutionLifecycle(order_id, Decimal("10"), Decimal("7"), OrderStatus.PARTIALLY_FILLED)
    assert first.continuation_client_order_id(Decimal("6")) != second.continuation_client_order_id(
        Decimal("3")
    )


def test_child_receipt_updates_parent_lifecycle_without_overstating_completion() -> None:
    parent_id = uuid4()
    lifecycle = ExecutionLifecycle(
        parent_id,
        Decimal("10"),
        filled_quantity=Decimal("4"),
        status=OrderStatus.PARTIALLY_FILLED,
    )
    child_id = lifecycle.continuation_client_order_id(Decimal("6"))
    fill = Fill(
        client_order_id=child_id,
        instrument=InstrumentId(venue="TEST", symbol="ABC"),
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        price=Decimal("100"),
        filled_at=datetime.now(UTC),
    )
    receipt = ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=child_id,
        outcome=ExecutionOutcome.FILLED,
        order_status=OrderStatus.FILLED,
        executed_at=fill.filled_at,
        fills=(fill,),
        correlation_id=str(parent_id),
        order_id=child_id,
        order_quantity=Decimal("6"),
    )

    updated = lifecycle.apply(receipt)

    assert updated.filled_quantity == Decimal("6")
    assert updated.remaining_quantity == Decimal("4")
    assert updated.status is OrderStatus.PARTIALLY_FILLED
    assert updated.can_continue


def test_continuation_cannot_exceed_evidenced_remainder() -> None:
    lifecycle = ExecutionLifecycle(
        uuid4(),
        Decimal("10"),
        filled_quantity=Decimal("4"),
        status=OrderStatus.PARTIALLY_FILLED,
    )

    try:
        lifecycle.continuation_quantity(Decimal("7"))
    except ValueError as exc:
        assert "exceeds remaining" in str(exc)
    else:
        raise AssertionError("expected continuation quantity validation")


def test_partial_continuation_executes_remaining_quantity_with_parent_correlation() -> None:
    from datetime import UTC, datetime

    from quantx.domain.accounts import AccountId
    from quantx.domain.clock import FixedClock
    from quantx.domain.deployment import (
        ExecutionContext,
        ExecutionMode,
        PortfolioId,
        StrategyDeploymentId,
    )
    from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
    from quantx.domain.order_intents import TradeIntent
    from quantx.domain.risk import RiskDecision, RiskResult
    from quantx.execution.market_data import MarketSnapshot
    from quantx.execution.paper import PaperExecutionEngine

    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("p-1"),
        deployment_id=StrategyDeploymentId("d-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
    )
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        execution_context=context,
    )
    from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent

    request = ApprovedExecutionRequest(
        build_order_from_intent(intent),
        context,
        RiskResult(RiskDecision.APPROVE, "approved"),
    )
    lifecycle = ExecutionLifecycle(
        request.order.client_order_id,
        Decimal("10"),
        Decimal("4"),
        OrderStatus.PARTIALLY_FILLED,
    )
    engine = PaperExecutionEngine(clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)))
    receipt = engine.continue_partial(
        request,
        lifecycle,
        risk_result=RiskResult(RiskDecision.APPROVE, "fresh approval"),
        snapshot=MarketSnapshot(
            instrument=request.order.instrument,
            timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            ask=Decimal("100"),
        ),
    )
    assert receipt.client_order_id != request.order.client_order_id
    assert receipt.correlation_id == str(request.order.client_order_id)
    assert receipt.filled_quantity == Decimal("6")



def _receipt_with_status(
    order_id: UUID,
    order_quantity: Decimal,
    status: OrderStatus,
    filled_quantity: Decimal,
    *,
    seconds: int,
) -> ExecutionReceipt:
    """Build a deterministic receipt for reducer safety tests."""
    from datetime import timedelta

    observed_at = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)
    fills = ()
    if filled_quantity:
        fills = (
            Fill(
                client_order_id=order_id,
                instrument=InstrumentId("TEST", "ABC"),
                side=OrderSide.BUY,
                quantity=filled_quantity,
                price=Decimal("100"),
                filled_at=observed_at,
            ),
        )
    outcome = {
        OrderStatus.ACCEPTED: ExecutionOutcome.ACCEPTED,
        OrderStatus.PARTIALLY_FILLED: ExecutionOutcome.PARTIALLY_FILLED,
        OrderStatus.FILLED: ExecutionOutcome.FILLED,
        OrderStatus.CANCELLED: ExecutionOutcome.CANCELLED,
        OrderStatus.UNKNOWN: ExecutionOutcome.UNKNOWN,
    }[status]
    return ExecutionReceipt(
        request_id=uuid4(),
        client_order_id=order_id,
        outcome=outcome,
        order_status=status,
        executed_at=observed_at,
        fills=fills,
        correlation_id=str(order_id),
        order_id=order_id,
        order_quantity=order_quantity,
    )


def test_cancelled_lifecycle_retains_late_fill_and_blocks_progression() -> None:
    order_id = uuid4()
    lifecycle = ExecutionLifecycle(order_id, Decimal("10"))
    cancelled = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.CANCELLED, Decimal("0"), seconds=1
    )
    late_fill = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.PARTIALLY_FILLED, Decimal("2"), seconds=2
    )

    reduced = lifecycle.apply(cancelled).apply(late_fill)

    assert reduced.status is OrderStatus.CANCELLED
    assert reduced.filled_quantity == Decimal("2")
    assert reduced.remaining_quantity == Decimal("8")
    assert reduced.requires_reconciliation
    assert any("late fill evidence" in anomaly for anomaly in reduced.anomalies)
    assert not reduced.can_continue
    assert not reduced.is_complete


def test_full_fill_status_cannot_be_overwritten_by_later_cancel() -> None:
    order_id = uuid4()
    lifecycle = ExecutionLifecycle(order_id, Decimal("10"))
    filled = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.FILLED, Decimal("10"), seconds=1
    )
    cancelled = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.CANCELLED, Decimal("0"), seconds=2
    )

    reduced = lifecycle.apply(filled).apply(cancelled)

    assert reduced.status is OrderStatus.FILLED
    assert reduced.filled_quantity == Decimal("10")
    assert reduced.requires_reconciliation
    assert any("conflicting status CANCELLED" in anomaly for anomaly in reduced.anomalies)
    assert not reduced.can_continue
    assert not reduced.is_complete


def test_unknown_is_unresolved_and_not_complete_or_continuable() -> None:
    order_id = uuid4()
    unknown = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.UNKNOWN, Decimal("0"), seconds=1
    )

    lifecycle = ExecutionLifecycle.rebuild(order_id, Decimal("10"), (unknown,))

    assert lifecycle.status is OrderStatus.UNKNOWN
    assert lifecycle.requires_reconciliation
    assert not lifecycle.is_complete
    assert not lifecycle.can_continue


def test_unknown_requires_authoritative_reconciliation_to_resolve() -> None:
    order_id = uuid4()
    unknown = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.UNKNOWN, Decimal("0"), seconds=1
    )
    accepted = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.ACCEPTED, Decimal("0"), seconds=2
    )

    ordinary_reduction = ExecutionLifecycle.rebuild(
        order_id, Decimal("10"), (unknown, accepted)
    )
    reconciled = ExecutionLifecycle.rebuild(
        order_id,
        Decimal("10"),
        (unknown, accepted),
        authoritative_reconciliation=True,
    )

    assert ordinary_reduction.status is OrderStatus.UNKNOWN
    assert ordinary_reduction.requires_reconciliation
    assert not ordinary_reduction.is_complete
    assert reconciled.status is OrderStatus.ACCEPTED
    assert not reconciled.requires_reconciliation
    assert not reconciled.can_continue


def test_partial_fill_then_cancel_is_complete_but_not_continuable() -> None:
    order_id = uuid4()
    partial = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.PARTIALLY_FILLED, Decimal("4"), seconds=1
    )
    cancelled = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.CANCELLED, Decimal("0"), seconds=2
    )

    lifecycle = ExecutionLifecycle(order_id, Decimal("10")).apply(partial).apply(cancelled)

    assert lifecycle.status is OrderStatus.CANCELLED
    assert lifecycle.filled_quantity == Decimal("4")
    assert lifecycle.remaining_quantity == Decimal("6")
    assert lifecycle.is_complete
    assert not lifecycle.can_continue
    assert not lifecycle.requires_reconciliation


def test_rebuild_orders_conflicting_receipts_deterministically() -> None:
    order_id = uuid4()
    cancelled = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.CANCELLED, Decimal("0"), seconds=1
    )
    late_fill = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.PARTIALLY_FILLED, Decimal("2"), seconds=2
    )

    first = ExecutionLifecycle.rebuild(order_id, Decimal("10"), (cancelled, late_fill))
    reversed_input = ExecutionLifecycle.rebuild(order_id, Decimal("10"), (late_fill, cancelled))

    assert first == reversed_input
    assert first.status is OrderStatus.CANCELLED
    assert first.filled_quantity == Decimal("2")
    assert first.requires_reconciliation


def test_apply_rejects_cumulative_overfill() -> None:
    order_id = uuid4()
    partial = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.PARTIALLY_FILLED, Decimal("8"), seconds=1
    )
    additional = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.PARTIALLY_FILLED, Decimal("3"), seconds=2
    )

    lifecycle = ExecutionLifecycle.rebuild(order_id, Decimal("10"), (partial,))

    try:
        lifecycle.apply(additional)
    except ValueError as exc:
        assert "cumulative fills exceed order quantity" in str(exc)
    else:
        raise AssertionError("overfill must be rejected")


def test_conflicting_duplicate_receipt_identity_remains_an_error() -> None:
    from dataclasses import replace

    order_id = uuid4()
    receipt = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.PARTIALLY_FILLED, Decimal("2"), seconds=1
    )
    conflicting = replace(receipt, message="different content with the same receipt ID")

    try:
        ExecutionLifecycle.rebuild(order_id, Decimal("10"), (receipt, conflicting))
    except ValueError as exc:
        assert "receipt ID maps to conflicting receipt data" in str(exc)
    else:
        raise AssertionError("conflicting receipt identities must be rejected")


def test_authoritative_cancel_confirmation_cannot_hide_full_fill_conflict() -> None:
    order_id = uuid4()
    cancelled = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.CANCELLED, Decimal("0"), seconds=1
    )
    late_fill_a = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.PARTIALLY_FILLED, Decimal("6"), seconds=2
    )
    late_fill_b = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.PARTIALLY_FILLED, Decimal("4"), seconds=3
    )
    confirming_cancel = _receipt_with_status(
        order_id, Decimal("10"), OrderStatus.CANCELLED, Decimal("0"), seconds=4
    )

    lifecycle = (
        ExecutionLifecycle(order_id, Decimal("10"))
        .apply(cancelled)
        .apply(late_fill_a)
        .apply(late_fill_b)
        .apply(confirming_cancel, authoritative_reconciliation=True)
    )

    assert lifecycle.status is OrderStatus.CANCELLED
    assert lifecycle.filled_quantity == Decimal("10")
    assert lifecycle.requires_reconciliation
    assert not lifecycle.is_complete
    assert not lifecycle.can_continue
