"""Durable SQLite idempotency contracts proven across real close/reopen cycles.

Every test reconstructs the store from the same database file so persistence is
demonstrated by observable behaviour after reopening, never by an in-memory
stand-in. These invariants protect the execution control path: a lost or
duplicated reservation can cause a double broker submission, and a reused
``client_order_id`` with different content must never be silently accepted.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.enums import AssetClass, OrderSide, OrderType, TimeInForce
from quantx.domain.execution_request import (
    ApprovedExecutionRequest,
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
from quantx.execution.idempotency import (
    OperatorResolutionAction,
    PendingExecutionContext,
)
from quantx.persistence.sqlite import SqliteDatabase, SqliteIdempotencyStore

FINGERPRINT = "a" * 64
OTHER_FINGERPRINT = "b" * 64
RESOLVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


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


def _approved_request(client_order_id: UUID | None = None) -> ApprovedExecutionRequest:
    instrument = _instrument()
    from quantx.domain.deployment import (
        ExecutionContext,
        ExecutionMode,
        PortfolioId,
        StrategyDeploymentId,
    )

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
        required_margin=Decimal("0"),
        execution_context=context,
    )
    order = build_order_from_intent(intent)
    if client_order_id is not None:
        order = replace(order, client_order_id=client_order_id)
    return ApprovedExecutionRequest(
        order=order,
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _pending_context(
    client_order_id: UUID,
    fingerprint: str = FINGERPRINT,
) -> PendingExecutionContext:
    return PendingExecutionContext.from_request(_approved_request(client_order_id), fingerprint)


def _store(path: Path) -> SqliteIdempotencyStore:
    return SqliteIdempotencyStore(SqliteDatabase(path))


# Durable reservation survives close/reopen and is never re-acquired.


def test_reservation_survives_close_and_reopen(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    client_order_id = uuid4()

    with SqliteDatabase(path) as database:
        decision = SqliteIdempotencyStore(database).reserve_or_get(client_order_id, FINGERPRINT)

    assert decision.reservation_acquired is True
    assert decision.reservation_pending is True

    with SqliteDatabase(path) as reopened:
        decision = SqliteIdempotencyStore(reopened).reserve_or_get(client_order_id, FINGERPRINT)

    assert decision.reservation_acquired is False
    assert decision.reservation_pending is True
    assert decision.existing_receipt_id is None


def test_completed_receipt_survives_close_and_reopen(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    client_order_id = uuid4()
    receipt_id = uuid4()

    with SqliteDatabase(path) as database:
        store = SqliteIdempotencyStore(database)
        store.reserve_or_get(client_order_id, FINGERPRINT)
        store.complete(client_order_id, FINGERPRINT, receipt_id)

    with SqliteDatabase(path) as reopened:
        decision = SqliteIdempotencyStore(reopened).check(client_order_id, FINGERPRINT)

    assert decision.existing_receipt_id == receipt_id
    assert decision.reservation_pending is False


# A client_order_id reused with different content must fail closed, durably.


def test_reused_client_order_id_with_different_fingerprint_is_rejected(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    client_order_id = uuid4()

    with SqliteDatabase(path) as database:
        SqliteIdempotencyStore(database).reserve_or_get(client_order_id, FINGERPRINT)

    with SqliteDatabase(path) as reopened:
        store = SqliteIdempotencyStore(reopened)
        with pytest.raises(ValueError, match="reused with a different request"):
            store.check(client_order_id, OTHER_FINGERPRINT)
        with pytest.raises(ValueError, match="reused with a different request"):
            store.reserve_or_get(client_order_id, OTHER_FINGERPRINT)
        with pytest.raises(ValueError, match="reused with a different request"):
            store.complete(client_order_id, OTHER_FINGERPRINT, uuid4())


def test_pending_context_fingerprint_mismatch_is_rejected_before_write(tmp_path) -> None:
    client_order_id = uuid4()

    with SqliteDatabase(tmp_path / "quantx.db") as database:
        store = SqliteIdempotencyStore(database)
        with pytest.raises(ValueError, match="fingerprint does not match"):
            store.reserve_or_get(
                client_order_id,
                FINGERPRINT,
                _pending_context(client_order_id, OTHER_FINGERPRINT),
            )

        assert store.check(client_order_id, FINGERPRINT).reservation_acquired is False


# Operator resolution is durable and blocks completion/second resolution.


def test_operator_resolution_survives_close_and_reopen(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    client_order_id = uuid4()

    with SqliteDatabase(path) as database:
        store = SqliteIdempotencyStore(database)
        store.reserve_or_get(client_order_id, FINGERPRINT)
        store.resolve_operator(
            client_order_id,
            FINGERPRINT,
            operator_id="operator-1",
            reason="unresolvable pending order",
            resolved_at=RESOLVED_AT,
            action=OperatorResolutionAction.CLOSE_UNRESOLVED,
        )

    with SqliteDatabase(path) as reopened:
        store = SqliteIdempotencyStore(reopened)
        decision = store.check(client_order_id, FINGERPRINT)

        assert decision.operator_resolved is True
        assert decision.reservation_pending is False
        assert decision.operator_resolution is not None
        assert decision.operator_resolution.operator_id == "operator-1"

        with pytest.raises(ValueError, match="cannot complete an operator-resolved"):
            store.complete(client_order_id, FINGERPRINT, uuid4())


def test_operator_resolution_rejects_completed_reservation(tmp_path) -> None:
    client_order_id = uuid4()

    with SqliteDatabase(tmp_path / "quantx.db") as database:
        store = SqliteIdempotencyStore(database)
        store.reserve_or_get(client_order_id, FINGERPRINT)
        store.complete(client_order_id, FINGERPRINT, uuid4())

        with pytest.raises(ValueError, match="cannot operator-resolve a completed"):
            store.resolve_operator(
                client_order_id,
                FINGERPRINT,
                operator_id="operator-1",
                reason="too late",
                resolved_at=RESOLVED_AT,
            )


def test_operator_resolution_rejects_different_fingerprint(tmp_path) -> None:
    client_order_id = uuid4()

    with SqliteDatabase(tmp_path / "quantx.db") as database:
        store = SqliteIdempotencyStore(database)
        store.reserve_or_get(client_order_id, FINGERPRINT)

        with pytest.raises(ValueError, match="reused with a different request"):
            store.resolve_operator(
                client_order_id,
                OTHER_FINGERPRINT,
                operator_id="operator-1",
                reason="mismatched request",
                resolved_at=RESOLVED_AT,
            )


def test_operator_resolution_is_at_most_once_across_reopen(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    client_order_id = uuid4()

    with SqliteDatabase(path) as database:
        SqliteIdempotencyStore(database).reserve_or_get(client_order_id, FINGERPRINT)

    with SqliteDatabase(path) as reopened:
        store = SqliteIdempotencyStore(reopened)
        store.resolve_operator(
            client_order_id,
            FINGERPRINT,
            operator_id="operator-1",
            reason="first",
            resolved_at=RESOLVED_AT,
        )

        with pytest.raises(ValueError, match="already operator-resolved"):
            store.resolve_operator(
                client_order_id,
                FINGERPRINT,
                operator_id="operator-2",
                reason="second",
                resolved_at=RESOLVED_AT,
            )


# Completion guards.


def test_complete_rejects_unreserved_client_order_id(tmp_path) -> None:
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        store = SqliteIdempotencyStore(database)
        with pytest.raises(ValueError, match="cannot complete an unreserved"):
            store.complete(uuid4(), FINGERPRINT, uuid4())


def test_complete_is_not_repeatable_after_reopen(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    client_order_id = uuid4()

    with SqliteDatabase(path) as database:
        store = SqliteIdempotencyStore(database)
        store.reserve_or_get(client_order_id, FINGERPRINT)
        store.complete(client_order_id, FINGERPRINT, uuid4())

    with SqliteDatabase(path) as reopened:
        store = SqliteIdempotencyStore(reopened)
        with pytest.raises(ValueError, match="already completed"):
            store.complete(client_order_id, FINGERPRINT, uuid4())


# Pending context durability and malformed-context isolation.


def test_pending_context_survives_close_and_reopen(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    client_order_id = uuid4()
    context = _pending_context(client_order_id)

    with SqliteDatabase(path) as database:
        SqliteIdempotencyStore(database).reserve_or_get(client_order_id, FINGERPRINT, context)

    with SqliteDatabase(path) as reopened:
        store = SqliteIdempotencyStore(reopened)
        decision = store.check(client_order_id, FINGERPRINT)
        contexts = store.list_pending_contexts()
        records = store.list_pending_recovery_records()

    assert decision.pending_context is not None
    assert decision.pending_context.request_fingerprint == FINGERPRINT
    assert len(contexts) == 1
    assert contexts[0].request_fingerprint == FINGERPRINT
    assert len(records) == 1
    assert records[0].context is not None
    assert records[0].error is None


def test_operator_resolved_context_is_excluded_from_pending_recovery(tmp_path) -> None:
    client_order_id = uuid4()

    with SqliteDatabase(tmp_path / "quantx.db") as database:
        store = SqliteIdempotencyStore(database)
        store.reserve_or_get(client_order_id, FINGERPRINT, _pending_context(client_order_id))
        store.resolve_operator(
            client_order_id,
            FINGERPRINT,
            operator_id="operator-1",
            reason="closed",
            resolved_at=RESOLVED_AT,
        )

        assert store.list_pending_contexts() == ()
        assert store.list_pending_recovery_records() == ()


def test_resolve_pending_persists_receipt_across_reopen(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    client_order_id = uuid4()
    receipt_id = uuid4()

    with SqliteDatabase(path) as database:
        store = SqliteIdempotencyStore(database)
        store.reserve_or_get(client_order_id, FINGERPRINT)
        store.resolve_pending(client_order_id, FINGERPRINT, receipt_id)

    with SqliteDatabase(path) as reopened:
        decision = SqliteIdempotencyStore(reopened).check(client_order_id, FINGERPRINT)

    assert decision.existing_receipt_id == receipt_id
    assert decision.reservation_pending is False


# Concurrency: exactly one acquirer, even across separate connections.


def test_concurrent_reservation_acquires_exactly_once(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    client_order_id = uuid4()

    with SqliteDatabase(path) as database:
        SqliteIdempotencyStore(database).reserve_or_get(client_order_id, FINGERPRINT)

    def _attempt(_: int) -> bool:
        store = _store(path)
        try:
            return store.reserve_or_get(client_order_id, FINGERPRINT).reservation_acquired
        finally:
            store._database.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(_attempt, range(8)))

    assert results.count(True) == 0


def test_closed_database_fails_closed_rather_than_reserving(tmp_path) -> None:
    client_order_id = uuid4()
    database = SqliteDatabase(tmp_path / "quantx.db")
    store = SqliteIdempotencyStore(database)
    database.close()

    with pytest.raises(sqlite3.ProgrammingError):
        store.reserve_or_get(client_order_id, FINGERPRINT)
