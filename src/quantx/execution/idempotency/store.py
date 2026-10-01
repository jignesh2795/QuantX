"""Small deterministic idempotency store for client-order submissions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from threading import RLock
from typing import Protocol
from uuid import UUID

from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import OrderSide, OrderStatus, OrderType, TimeInForce
from quantx.domain.execution_request import (
    ApprovedExecutionRequest,
    PendingExecutionRecoveryRequest,
)
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.orders import Order
from quantx.domain.value_objects import AccountId, BrokerConnectionId, InstrumentId


@dataclass(frozen=True, slots=True)
class PendingExecutionContext:
    """Persisted immutable request projection sufficient for post-restart recovery."""

    request_fingerprint: str
    order: Order
    execution_context: ExecutionContext
    parent_client_order_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request_fingerprint, str) or not self.request_fingerprint.strip():
            raise ValueError("pending execution context fingerprint must not be empty")
        if self.execution_context.execution_mode is not ExecutionMode.LIVE:
            raise ValueError("pending execution context must describe LIVE execution")

    @classmethod
    def from_request(
        cls,
        request: ApprovedExecutionRequest,
        request_fingerprint: str,
    ) -> PendingExecutionContext:
        return cls(
            request_fingerprint=request_fingerprint,
            order=request.order,
            execution_context=request.execution_context,
            parent_client_order_id=request.parent_client_order_id,
        )

    def to_recovery_request(self) -> PendingExecutionRecoveryRequest:
        return PendingExecutionRecoveryRequest(
            order=self.order,
            execution_context=self.execution_context,
            parent_client_order_id=self.parent_client_order_id,
        )

    def to_json(self) -> str:
        payload = {
            "version": 1,
            "request_fingerprint": self.request_fingerprint,
            "order": {
                "client_order_id": str(self.order.client_order_id),
                "instrument_venue": self.order.instrument.venue,
                "instrument_symbol": self.order.instrument.symbol,
                "side": self.order.side.value,
                "order_type": self.order.order_type.value,
                "quantity": str(self.order.quantity),
                "limit_price": (
                    None if self.order.limit_price is None else str(self.order.limit_price)
                ),
                "stop_price": (
                    None if self.order.stop_price is None else str(self.order.stop_price)
                ),
                "time_in_force": self.order.time_in_force.value,
                "status": self.order.status.value,
                "created_at": self.order.created_at.isoformat(),
                "intent_id": None if self.order.intent_id is None else str(self.order.intent_id),
                "strategy_id": self.order.strategy_id,
                "strategy_version": self.order.strategy_version,
                "required_capabilities": sorted(self.order.required_capabilities),
            },
            "execution_context": {
                "account_id": self.execution_context.account_id.value,
                "portfolio_id": self.execution_context.portfolio_id.value,
                "deployment_id": self.execution_context.deployment_id.value,
                "market_region": self.execution_context.market.region.value,
                "market_family": self.execution_context.market.family.value,
                "market_venue": self.execution_context.market.venue,
                "market_country": self.execution_context.market.country_code,
                "broker_connection_id": (
                    None
                    if self.execution_context.broker_connection_id is None
                    else self.execution_context.broker_connection_id.value
                ),
                "execution_mode": self.execution_context.execution_mode.value,
            },
            "parent_client_order_id": (
                None if self.parent_client_order_id is None else str(self.parent_client_order_id)
            ),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, payload_json: str) -> PendingExecutionContext:
        try:
            payload = json.loads(payload_json)
            if not isinstance(payload, dict) or payload.get("version") != 1:
                raise ValueError("unsupported pending execution context version")
            order_data = payload["order"]
            context_data = payload["execution_context"]
            order = Order(
                instrument=InstrumentId(
                    order_data["instrument_venue"],
                    order_data["instrument_symbol"],
                ),
                side=OrderSide(order_data["side"]),
                order_type=OrderType(order_data["order_type"]),
                quantity=Decimal(order_data["quantity"]),
                limit_price=(
                    None
                    if order_data["limit_price"] is None
                    else Decimal(order_data["limit_price"])
                ),
                stop_price=(
                    None
                    if order_data["stop_price"] is None
                    else Decimal(order_data["stop_price"])
                ),
                time_in_force=TimeInForce(order_data["time_in_force"]),
                client_order_id=UUID(order_data["client_order_id"]),
                status=OrderStatus(order_data["status"]),
                created_at=datetime.fromisoformat(order_data["created_at"]),
                intent_id=(
                    None
                    if order_data["intent_id"] is None
                    else UUID(order_data["intent_id"])
                ),
                strategy_id=order_data["strategy_id"],
                strategy_version=order_data["strategy_version"],
                required_capabilities=frozenset(order_data["required_capabilities"]),
            )
            context = ExecutionContext(
                account_id=AccountId(context_data["account_id"]),
                portfolio_id=PortfolioId(context_data["portfolio_id"]),
                deployment_id=StrategyDeploymentId(context_data["deployment_id"]),
                market=MarketContext(
                    MarketRegion(context_data["market_region"]),
                    MarketFamily(context_data["market_family"]),
                    context_data["market_venue"],
                    context_data["market_country"],
                ),
                broker_connection_id=(
                    None
                    if context_data["broker_connection_id"] is None
                    else BrokerConnectionId(context_data["broker_connection_id"])
                ),
                execution_mode=ExecutionMode(context_data["execution_mode"]),
            )
            parent = payload["parent_client_order_id"]
            return cls(
                request_fingerprint=payload["request_fingerprint"],
                order=order,
                execution_context=context,
                parent_client_order_id=parent,
            )
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid pending execution context") from exc


@dataclass(frozen=True, slots=True)
class PendingExecutionRecoveryRecord:
    """One durable pending row, including safe decode failures."""

    client_order_id: str
    request_fingerprint: str
    context: PendingExecutionContext | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if (self.context is None) == (self.error is None):
            raise ValueError("pending recovery record needs context or error")



@dataclass(frozen=True, slots=True)
class IdempotencyDecision:
    client_order_id: UUID
    request_fingerprint: str
    existing_receipt_id: UUID | None = None
    reservation_pending: bool = False
    reservation_acquired: bool = False
    pending_context: PendingExecutionContext | None = None


class IdempotencyStore(Protocol):
    def check(self, client_order_id: UUID, request_fingerprint: str) -> IdempotencyDecision: ...

    def reserve_or_get(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        pending_context: PendingExecutionContext | None = None,
    ) -> IdempotencyDecision: ...

    def complete(
        self, client_order_id: UUID, request_fingerprint: str, receipt_id: UUID
    ) -> None: ...

    def resolve_pending(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        receipt_id: UUID,
    ) -> None: ...

    def list_pending_recovery_records(self) -> tuple[PendingExecutionRecoveryRecord, ...]: ...

    def list_pending_contexts(self) -> tuple[PendingExecutionContext, ...]: ...


class InMemoryIdempotencyStore:
    """Process-local reference implementation; production storage is replaceable."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._fingerprints: dict[UUID, str] = {}
        self._receipts: dict[UUID, UUID] = {}
        self._contexts: dict[UUID, PendingExecutionContext] = {}

    def check(self, client_order_id: UUID, request_fingerprint: str) -> IdempotencyDecision:
        with self._lock:
            existing = self._fingerprints.get(client_order_id)
            if existing is not None and existing != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            return IdempotencyDecision(
                client_order_id=client_order_id,
                request_fingerprint=request_fingerprint,
                existing_receipt_id=self._receipts.get(client_order_id),
                reservation_pending=existing is not None and client_order_id not in self._receipts,
                pending_context=self._contexts.get(client_order_id),
            )

    def reserve_or_get(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        pending_context: PendingExecutionContext | None = None,
    ) -> IdempotencyDecision:
        with self._lock:
            decision = self.check(client_order_id, request_fingerprint)
            if decision.existing_receipt_id is not None or decision.reservation_pending:
                return decision
            self._fingerprints[client_order_id] = request_fingerprint
            if pending_context is not None:
                self._contexts[client_order_id] = pending_context
            return IdempotencyDecision(
                client_order_id=client_order_id,
                request_fingerprint=request_fingerprint,
                reservation_pending=True,
                reservation_acquired=True,
                pending_context=pending_context,
            )

    def complete(self, client_order_id: UUID, request_fingerprint: str, receipt_id: UUID) -> None:
        with self._lock:
            existing = self._fingerprints.get(client_order_id)
            if existing is None:
                raise ValueError("cannot complete an unreserved client_order_id")
            if existing != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            if client_order_id in self._receipts:
                raise ValueError("cannot complete an already completed client_order_id")
            self._receipts[client_order_id] = receipt_id

    def resolve_pending(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        receipt_id: UUID,
    ) -> None:
        with self._lock:
            decision = self.check(client_order_id, request_fingerprint)
            if not decision.reservation_pending:
                raise ValueError("cannot resolve a non-pending idempotency reservation")
            if self._receipts.get(client_order_id) is not None:
                raise ValueError("cannot overwrite an existing receipt")
            self._receipts[client_order_id] = receipt_id

    def list_pending_recovery_records(self) -> tuple[PendingExecutionRecoveryRecord, ...]:
        with self._lock:
            return tuple(
                PendingExecutionRecoveryRecord(
                    client_order_id=str(client_order_id),
                    request_fingerprint=self._fingerprints[client_order_id],
                    context=context,
                )
                for client_order_id, context in self._contexts.items()
                if client_order_id not in self._receipts
            )

    def list_pending_contexts(self) -> tuple[PendingExecutionContext, ...]:
        return tuple(
            record.context
            for record in self.list_pending_recovery_records()
            if record.context is not None
        )
