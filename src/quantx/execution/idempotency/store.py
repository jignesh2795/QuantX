"""Small deterministic idempotency store for client-order submissions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from threading import RLock
from typing import Protocol
from uuid import UUID

from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import OrderSide, OrderStatus, OrderType, PositionEffect, TimeInForce
from quantx.domain.execution_request import (
    ApprovedExecutionRequest,
    PendingExecutionRecoveryRequest,
    validate_instrument_resolution,
    validate_order_product_symmetry,
    validate_position_effect_fields,
)
from quantx.domain.instrument_registry import InstrumentResolution
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.orders import Order
from quantx.domain.position_effect import AbsentPositionEffectResolution, PositionEvidence
from quantx.domain.product_selection import ProductSelectionResolution
from quantx.domain.value_objects import AccountId, BrokerConnectionId, InstrumentId, ProductCode

from .fingerprint import request_fingerprint


class OperatorResolutionAction(StrEnum):
    """The only explicit operator closure for an unresolvable PENDING reservation."""

    CLOSE_UNRESOLVED = "CLOSE_UNRESOLVED"


def _timedelta_microseconds(value: timedelta | None) -> int | None:
    if value is None:
        return None
    return (value.days * 86_400 + value.seconds) * 1_000_000 + value.microseconds


@dataclass(frozen=True, slots=True)
class PendingExecutionContext:
    """Persisted immutable request projection sufficient for post-restart recovery."""

    request_fingerprint: str
    order: Order
    execution_context: ExecutionContext
    parent_client_order_id: str | None = None
    product: ProductCode | None = None
    position_effect: PositionEffect | None = None
    effective_position_effect: PositionEffect | None = None
    position_evidence_cut: datetime | None = None
    position_evidence: PositionEvidence | None = None
    position_evidence_max_age: timedelta | None = None
    position_effect_approval_instant: datetime | None = None
    product_resolution: ProductSelectionResolution | None = None
    position_effect_policy_resolution: AbsentPositionEffectResolution | None = None
    instrument_resolution: InstrumentResolution | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request_fingerprint, str) or not self.request_fingerprint.strip():
            raise ValueError("pending execution context fingerprint must not be empty")
        if self.execution_context.execution_mode is not ExecutionMode.LIVE:
            raise ValueError("pending execution context must describe LIVE execution")
        validate_instrument_resolution(self.order, self.instrument_resolution)
        validate_order_product_symmetry(
            self.order,
            self.product,
            execution_context=self.execution_context,
            product_resolution=self.product_resolution,
        )
        validate_position_effect_fields(
            self.order,
            execution_context=self.execution_context,
            product=self.product,
            position_effect=self.position_effect,
            effective_position_effect=self.effective_position_effect,
            position_evidence_cut=self.position_evidence_cut,
            position_evidence=self.position_evidence,
            position_evidence_max_age=self.position_evidence_max_age,
            position_effect_approval_instant=self.position_effect_approval_instant,
            position_effect_policy_resolution=self.position_effect_policy_resolution,
        )

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
            product=request.product,
            position_effect=request.position_effect,
            effective_position_effect=request.effective_position_effect,
            position_evidence_cut=request.position_evidence_cut,
            position_evidence=request.position_evidence,
            position_evidence_max_age=request.position_evidence_max_age,
            position_effect_approval_instant=request.position_effect_approval_instant,
            product_resolution=request.product_resolution,
            position_effect_policy_resolution=request.position_effect_policy_resolution,
            instrument_resolution=request.instrument_resolution,
        )

    def to_recovery_request(self) -> PendingExecutionRecoveryRequest:
        return PendingExecutionRecoveryRequest(
            order=self.order,
            execution_context=self.execution_context,
            parent_client_order_id=self.parent_client_order_id,
            product=self.product,
            position_effect=self.position_effect,
            effective_position_effect=self.effective_position_effect,
            position_evidence_cut=self.position_evidence_cut,
            position_evidence=self.position_evidence,
            position_evidence_max_age=self.position_evidence_max_age,
            position_effect_approval_instant=self.position_effect_approval_instant,
            product_resolution=self.product_resolution,
            position_effect_policy_resolution=self.position_effect_policy_resolution,
            instrument_resolution=self.instrument_resolution,
        )

    def to_json(self) -> str:
        payload = {
            "version": 2,
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
                "product": None if self.order.product is None else str(self.order.product),
                "position_effect": (
                    None if self.order.position_effect is None else self.order.position_effect.value
                ),
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
                "market_pack_id": self.execution_context.market_pack_id,
                "rule_version": self.execution_context.rule_version,
            },
            "parent_client_order_id": (
                None if self.parent_client_order_id is None else str(self.parent_client_order_id)
            ),
            "product": None if self.product is None else str(self.product),
            "position_effect": (
                None if self.position_effect is None else self.position_effect.value
            ),
            "effective_position_effect": (
                None
                if self.effective_position_effect is None
                else self.effective_position_effect.value
            ),
            "position_evidence_cut": (
                None
                if self.position_evidence_cut is None
                else self.position_evidence_cut.isoformat()
            ),
            "position_effect_approval_instant": (
                None
                if self.position_effect_approval_instant is None
                else self.position_effect_approval_instant.isoformat()
            ),
            "position_evidence": (
                None
                if self.position_evidence is None
                else {
                    "instrument_venue": self.position_evidence.instrument.venue,
                    "instrument_symbol": self.position_evidence.instrument.symbol,
                    "quantity": str(self.position_evidence.quantity),
                    "observed_at": self.position_evidence.observed_at.isoformat(),
                    "evidence_cut": self.position_evidence.evidence_cut.isoformat(),
                    "matched": self.position_evidence.matched,
                }
            ),
            "position_evidence_max_age_microseconds": _timedelta_microseconds(
                self.position_evidence_max_age
            ),
            "product_resolution": (
                None if self.product_resolution is None else self.product_resolution.to_payload()
            ),
            "position_effect_policy_resolution": (
                None
                if self.position_effect_policy_resolution is None
                else self.position_effect_policy_resolution.to_payload()
            ),
            "instrument_resolution": (
                None
                if self.instrument_resolution is None
                else self.instrument_resolution.to_payload()
            ),
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, payload_json: str) -> PendingExecutionContext:
        try:
            payload = json.loads(payload_json)
            if not isinstance(payload, dict):
                raise ValueError("unsupported pending execution context version")
            # Version 1 is a pre-QX-05 row: it never carried instrument
            # resolution evidence. Version 2 names that evidence explicitly.
            version = payload.get("version")
            if type(version) is not int or version not in (1, 2):
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
                    None if order_data["stop_price"] is None else Decimal(order_data["stop_price"])
                ),
                time_in_force=TimeInForce(order_data["time_in_force"]),
                client_order_id=UUID(order_data["client_order_id"]),
                status=OrderStatus(order_data["status"]),
                created_at=datetime.fromisoformat(order_data["created_at"]),
                intent_id=(
                    None if order_data["intent_id"] is None else UUID(order_data["intent_id"])
                ),
                strategy_id=order_data["strategy_id"],
                strategy_version=order_data["strategy_version"],
                required_capabilities=frozenset(order_data["required_capabilities"]),
                product=ProductCode(order_data["product"]) if order_data.get("product") else None,
                position_effect=(
                    PositionEffect(order_data["position_effect"])
                    if order_data.get("position_effect")
                    else None
                ),
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
                market_pack_id=context_data.get("market_pack_id"),
                rule_version=context_data.get("rule_version"),
            )
            parent = payload["parent_client_order_id"]
            product_value = payload.get("product")
            effect_value = payload.get("position_effect")
            effective_value = payload.get("effective_position_effect")
            cut_value = payload.get("position_evidence_cut")
            evidence_value = payload.get("position_evidence")
            max_age_value = payload.get("position_evidence_max_age_microseconds")
            evidence = None
            if evidence_value is not None:
                if not isinstance(evidence_value, dict):
                    raise ValueError("pending position evidence must be an object")
                matched = evidence_value["matched"]
                if not isinstance(matched, bool):
                    raise ValueError("pending position evidence matched must be boolean")
                evidence = PositionEvidence(
                    instrument=InstrumentId(
                        evidence_value["instrument_venue"],
                        evidence_value["instrument_symbol"],
                    ),
                    quantity=Decimal(evidence_value["quantity"]),
                    observed_at=datetime.fromisoformat(evidence_value["observed_at"]),
                    evidence_cut=datetime.fromisoformat(evidence_value["evidence_cut"]),
                    matched=matched,
                )
            max_age = None if max_age_value is None else timedelta(microseconds=int(max_age_value))
            instant_value = payload.get("position_effect_approval_instant")
            product_resolution_value = payload.get("product_resolution")
            policy_resolution_value = payload.get("position_effect_policy_resolution")
            if version == 1:
                if "instrument_resolution" in payload:
                    raise ValueError(
                        "a version 1 pending execution context cannot carry an "
                        "instrument resolution"
                    )
                instrument_resolution_value = None
            else:
                instrument_resolution_value = payload["instrument_resolution"]
            product_resolution = (
                None
                if product_resolution_value is None
                else ProductSelectionResolution.from_payload(product_resolution_value)
            )
            policy_resolution = (
                None
                if policy_resolution_value is None
                else AbsentPositionEffectResolution.from_payload(policy_resolution_value)
            )
            instrument_resolution = (
                None
                if instrument_resolution_value is None
                else InstrumentResolution.from_payload(instrument_resolution_value)
            )
            restored = cls(
                request_fingerprint=payload["request_fingerprint"],
                order=order,
                execution_context=context,
                parent_client_order_id=parent,
                product=ProductCode(product_value) if product_value else None,
                position_effect=PositionEffect(effect_value) if effect_value else None,
                effective_position_effect=(
                    PositionEffect(effective_value) if effective_value else None
                ),
                position_evidence_cut=(datetime.fromisoformat(cut_value) if cut_value else None),
                position_evidence=evidence,
                position_evidence_max_age=max_age,
                position_effect_approval_instant=(
                    datetime.fromisoformat(instant_value) if instant_value else None
                ),
                product_resolution=product_resolution,
                position_effect_policy_resolution=policy_resolution,
                instrument_resolution=instrument_resolution,
            )
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid pending execution context") from exc
        # The stored digest is only trustworthy when it still describes the
        # restored execution semantics. Re-derive it with the canonical rules
        # and compare: a payload whose proof or execution fields were altered
        # while the old digest was kept is rejected instead of recovered.
        if request_fingerprint(restored) != restored.request_fingerprint:
            raise ValueError(
                "pending execution context fingerprint does not match its execution semantics"
            )
        return restored


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
class OperatorResolution:
    """Durable, auditable operator closure of an unresolved PENDING reservation.

    This is not a broker execution outcome and never produces an
    ExecutionReceipt. It records that automated evidence could not resolve
    the submission and an authorized operator explicitly closed it.
    """

    client_order_id: UUID
    request_fingerprint: str
    operator_id: str
    reason: str
    resolved_at: datetime
    action: OperatorResolutionAction = OperatorResolutionAction.CLOSE_UNRESOLVED
    evidence_reference: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.request_fingerprint, str) or not self.request_fingerprint.strip():
            raise ValueError("operator resolution fingerprint must not be empty")
        if not isinstance(self.operator_id, str) or not self.operator_id.strip():
            raise ValueError("operator identity must not be empty")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("operator resolution reason must not be empty")
        if self.resolved_at.tzinfo is None or self.resolved_at.utcoffset() is None:
            raise ValueError("resolved_at must be timezone-aware")
        if self.evidence_reference is not None and not self.evidence_reference.strip():
            raise ValueError("evidence reference must not be blank")


class NotSubmittedSource(StrEnum):
    """True provenance of a definite NOT_SUBMITTED closure.

    Only a trusted adapter's typed preflight rejection can produce this
    today. The typed source keeps the durable record machine-distinguishable
    from a human operator closure instead of relying on a sentinel string
    inside the operator identity.
    """

    ADAPTER_PREFLIGHT_REJECTION = "ADAPTER_PREFLIGHT_REJECTION"


@dataclass(frozen=True, slots=True)
class NotSubmittedResolution:
    """Durable closure of a PENDING reservation as definitively not submitted.

    Unlike :class:`OperatorResolution`, this is not a human decision and no
    human identity is recorded or implied. It records a definite local
    outcome proven without transport I/O: the trusted adapter raised the
    typed preflight rejection from local validation, so no transport
    submission was entered and no ExecutionReceipt may ever exist for this
    reservation. It is never a broker execution outcome and must never be
    presented as an operator closure.
    """

    client_order_id: UUID
    request_fingerprint: str
    source: NotSubmittedSource
    reason: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.request_fingerprint, str) or not self.request_fingerprint.strip():
            raise ValueError("not-submitted resolution fingerprint must not be empty")
        if type(self.source) is not NotSubmittedSource:
            raise ValueError("not-submitted source must be a typed provenance value")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("not-submitted resolution reason must not be empty")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")


class IdempotencyDecisionValidationError(Exception):
    """Private sentinel raised when an idempotency decision fails its non-negotiable contract."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# Legal ``(reservation_pending, reservation_acquired, has_receipt, operator_resolved,
# not_submitted)`` combinations produced by the reference stores. Any other combination
# is a state no reservation store can reach, so it is rejected rather than interpreted.
_LEGAL_DECISION_STATES: frozenset[tuple[bool, bool, bool, bool, bool]] = frozenset(
    {
        # No reservation row exists yet (``check`` on an unseen client order).
        (False, False, False, False, False),
        # Row exists with no receipt and no closure (``check`` on a held reservation).
        (True, False, False, False, False),
        # This ``reserve_or_get`` call acquired the row.
        (True, True, False, False, False),
        # A receipt completed the reservation.
        (False, False, True, False, False),
        # An operator closed the reservation.
        (False, False, False, True, False),
        # The adapter proved the request was never submitted.
        (False, False, False, False, True),
    }
)


def _exact_bool_violation(decision: IdempotencyDecision) -> str | None:
    """Reject non-bool flags before any state comparison.

    ``True == 1`` makes an integer flag indistinguishable from a real ``True``
    inside a state tuple, so the type is checked before the matrix lookup.
    """
    for name, value in (
        ("reservation_pending", decision.reservation_pending),
        ("reservation_acquired", decision.reservation_acquired),
        ("operator_resolved", decision.operator_resolved),
    ):
        if type(value) is not bool:
            return f"idempotency decision {name} is not an exact bool"
    return None


def validate_decision_state(decision: IdempotencyDecision) -> str | None:
    """Non-raising validator for the decision state matrix.

    Only the states the in-memory and SQLite stores can actually produce are
    accepted. A decision outside that set - for example an acquired reservation
    that is not pending, or a receipt on a pending or acquired reservation -
    never reaches submission.
    """
    violation = _exact_bool_violation(decision)
    if violation is not None:
        return violation
    state = (
        decision.reservation_pending,
        decision.reservation_acquired,
        decision.existing_receipt_id is not None,
        decision.operator_resolved,
        decision.not_submitted_resolution is not None,
    )
    if state not in _LEGAL_DECISION_STATES:
        return "idempotency decision is not a state the reservation store can produce"
    return None


def _resolution_matches_decision(
    resolution: OperatorResolution | NotSubmittedResolution,
    decision: IdempotencyDecision,
) -> bool:
    """A closure record is evidence only about the client order it closes.

    The record carries its own identity, and a record closing a different order
    says nothing about this one. Both fields are compared exactly, with the
    types checked first so a string-typed id cannot compare equal by accident.
    """
    return (
        type(resolution.client_order_id) is UUID
        and resolution.client_order_id == decision.client_order_id
        and type(resolution.request_fingerprint) is str
        and resolution.request_fingerprint == decision.request_fingerprint
    )


def validate_decision_for_request(
    decision: IdempotencyDecision,
    *,
    client_order_id: UUID,
    request_fingerprint: str,
) -> str | None:
    """Non-raising validator binding a decision to the request being dispatched.

    A decision is evidence about one client order. It is usable only when its
    identity is exactly the identity of the request about to be dispatched, so
    a foreign client order id or fingerprint is rejected even when the decision
    is otherwise structurally valid.
    """
    if type(decision.client_order_id) is not UUID:
        return "idempotency decision client_order_id is not an exact UUID"
    if decision.client_order_id != client_order_id:
        return "idempotency decision client_order_id does not match the request"
    if type(decision.request_fingerprint) is not str or not decision.request_fingerprint:
        return "idempotency decision fingerprint is not a non-empty string"
    if decision.request_fingerprint != request_fingerprint:
        return "idempotency decision fingerprint does not match the request"
    if decision.existing_receipt_id is not None and type(decision.existing_receipt_id) is not UUID:
        return "existing receipt id is not an exact UUID"
    if decision.operator_resolution is not None:
        if decision.operator_resolved is not True:
            return "operator resolution is present but the decision is not operator-resolved"
        if not isinstance(decision.operator_resolution, OperatorResolution):
            return "operator-resolved decision requires a typed OperatorResolution"
        if not _resolution_matches_decision(decision.operator_resolution, decision):
            return "operator resolution does not belong to this idempotency decision"
    elif decision.operator_resolved is True:
        return "operator-resolved decision requires a typed OperatorResolution"
    if decision.not_submitted_resolution is not None:
        if not isinstance(decision.not_submitted_resolution, NotSubmittedResolution):
            return "not-submitted decision requires a typed NotSubmittedResolution"
        if not _resolution_matches_decision(decision.not_submitted_resolution, decision):
            return "not-submitted resolution does not belong to this idempotency decision"
    context = decision.pending_context
    if context is not None:
        if not isinstance(context, PendingExecutionContext):
            return "pending execution context is not a typed PendingExecutionContext"
        if context.request_fingerprint != decision.request_fingerprint:
            return "pending execution context fingerprint does not match the decision"
        if context.order.client_order_id != decision.client_order_id:
            return "pending execution context client_order_id does not match the decision"
        mode = context.execution_context.execution_mode
        if type(mode) is not ExecutionMode:
            return "pending execution context mode is not an exact ExecutionMode"
        if mode is not ExecutionMode.LIVE:
            return "pending execution context mode must be LIVE"
    return None


@dataclass(frozen=True, slots=True)
class IdempotencyDecision:
    client_order_id: UUID
    request_fingerprint: str
    existing_receipt_id: UUID | None = None
    reservation_pending: bool = False
    reservation_acquired: bool = False
    pending_context: PendingExecutionContext | None = None
    operator_resolved: bool = False
    operator_resolution: OperatorResolution | None = None
    not_submitted_resolution: NotSubmittedResolution | None = None

    def __post_init__(self) -> None:
        if self.operator_resolved != (self.operator_resolution is not None):
            raise ValueError("operator-resolved decision requires its resolution record")
        if self.not_submitted_resolution is not None:
            if self.reservation_pending:
                raise ValueError("a not-submitted closure cannot leave the reservation pending")
            if self.operator_resolution is not None:
                raise ValueError("operator and not-submitted resolutions are mutually exclusive")
            if self.not_submitted_resolution.client_order_id != self.client_order_id:
                raise ValueError("not-submitted decision client_order_id mismatch")
            if self.not_submitted_resolution.request_fingerprint != self.request_fingerprint:
                raise ValueError("not-submitted decision fingerprint mismatch")


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

    def resolve_operator(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        *,
        operator_id: str,
        reason: str,
        resolved_at: datetime,
        action: OperatorResolutionAction = OperatorResolutionAction.CLOSE_UNRESOLVED,
        evidence_reference: str | None = None,
    ) -> OperatorResolution: ...

    def get_operator_resolution(
        self, client_order_id: UUID, request_fingerprint: str
    ) -> OperatorResolution | None: ...

    def record_not_submitted(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        *,
        source: NotSubmittedSource,
        reason: str,
        recorded_at: datetime,
    ) -> NotSubmittedResolution: ...

    def get_not_submitted(
        self, client_order_id: UUID, request_fingerprint: str
    ) -> NotSubmittedResolution | None: ...

    def list_pending_recovery_records(self) -> tuple[PendingExecutionRecoveryRecord, ...]: ...

    def list_pending_contexts(self) -> tuple[PendingExecutionContext, ...]: ...


class InMemoryIdempotencyStore:
    """Process-local reference implementation; production storage is replaceable."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._fingerprints: dict[UUID, str] = {}
        self._receipts: dict[UUID, UUID] = {}
        self._contexts: dict[UUID, PendingExecutionContext] = {}
        self._resolutions: dict[UUID, OperatorResolution] = {}
        self._not_submitted: dict[UUID, NotSubmittedResolution] = {}

    def check(self, client_order_id: UUID, request_fingerprint: str) -> IdempotencyDecision:
        with self._lock:
            existing = self._fingerprints.get(client_order_id)
            if existing is not None and existing != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            resolution = self._resolutions.get(client_order_id)
            if resolution is not None and resolution.request_fingerprint != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            not_submitted = self._not_submitted.get(client_order_id)
            if (
                not_submitted is not None
                and not_submitted.request_fingerprint != request_fingerprint
            ):
                raise ValueError("client_order_id was reused with a different request")
            return IdempotencyDecision(
                client_order_id=client_order_id,
                request_fingerprint=request_fingerprint,
                existing_receipt_id=self._receipts.get(client_order_id),
                reservation_pending=(
                    existing is not None
                    and client_order_id not in self._receipts
                    and client_order_id not in self._resolutions
                    and client_order_id not in self._not_submitted
                ),
                pending_context=self._contexts.get(client_order_id),
                operator_resolved=resolution is not None,
                operator_resolution=resolution,
                not_submitted_resolution=not_submitted,
            )

    def reserve_or_get(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        pending_context: PendingExecutionContext | None = None,
    ) -> IdempotencyDecision:
        with self._lock:
            decision = self.check(client_order_id, request_fingerprint)
            if (
                decision.existing_receipt_id is not None
                or decision.reservation_pending
                or decision.operator_resolved
                or decision.not_submitted_resolution is not None
            ):
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
            if client_order_id in self._resolutions:
                raise ValueError("cannot complete an operator-resolved reservation")
            if client_order_id in self._not_submitted:
                raise ValueError("cannot complete a reservation closed as not submitted")
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
            if decision.operator_resolved:
                raise ValueError("cannot resolve an operator-resolved reservation")
            if decision.not_submitted_resolution is not None:
                raise ValueError("cannot resolve a reservation closed as not submitted")
            if not decision.reservation_pending:
                raise ValueError("cannot resolve a non-pending idempotency reservation")
            if self._receipts.get(client_order_id) is not None:
                raise ValueError("cannot overwrite an existing receipt")
            self._receipts[client_order_id] = receipt_id

    def resolve_operator(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        *,
        operator_id: str,
        reason: str,
        resolved_at: datetime,
        action: OperatorResolutionAction = OperatorResolutionAction.CLOSE_UNRESOLVED,
        evidence_reference: str | None = None,
    ) -> OperatorResolution:
        with self._lock:
            existing = self._fingerprints.get(client_order_id)
            if existing is None:
                raise ValueError("cannot resolve an unreserved client_order_id")
            if existing != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            if client_order_id in self._receipts:
                raise ValueError("cannot operator-resolve a completed reservation")
            if client_order_id in self._resolutions:
                raise ValueError("reservation is already operator-resolved")
            if client_order_id in self._not_submitted:
                raise ValueError("cannot operator-resolve a reservation closed as not submitted")
            resolution = OperatorResolution(
                client_order_id=client_order_id,
                request_fingerprint=request_fingerprint,
                operator_id=operator_id,
                reason=reason,
                resolved_at=resolved_at,
                action=action,
                evidence_reference=evidence_reference,
            )
            self._resolutions[client_order_id] = resolution
            return resolution

    def get_operator_resolution(
        self, client_order_id: UUID, request_fingerprint: str
    ) -> OperatorResolution | None:
        with self._lock:
            resolution = self._resolutions.get(client_order_id)
            if resolution is None:
                return None
            if resolution.request_fingerprint != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            return resolution

    def record_not_submitted(
        self,
        client_order_id: UUID,
        request_fingerprint: str,
        *,
        source: NotSubmittedSource,
        reason: str,
        recorded_at: datetime,
    ) -> NotSubmittedResolution:
        """Durably close a PENDING reservation as definitively not submitted.

        Fail-closed: the reservation must exist and still be PENDING, the
        fingerprint must match, and neither a receipt, an operator closure,
        nor a prior not-submitted closure may exist. No receipt is created
        and no human identity is recorded or implied.
        """
        with self._lock:
            existing = self._fingerprints.get(client_order_id)
            if existing is None:
                raise ValueError("cannot close an unreserved client_order_id as not submitted")
            if existing != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            if client_order_id in self._receipts:
                raise ValueError("cannot close a completed reservation as not submitted")
            if client_order_id in self._resolutions:
                raise ValueError("reservation is already operator-resolved")
            if client_order_id in self._not_submitted:
                raise ValueError("reservation is already closed as not submitted")
            resolution = NotSubmittedResolution(
                client_order_id=client_order_id,
                request_fingerprint=request_fingerprint,
                source=source,
                reason=reason,
                recorded_at=recorded_at,
            )
            self._not_submitted[client_order_id] = resolution
            return resolution

    def get_not_submitted(
        self, client_order_id: UUID, request_fingerprint: str
    ) -> NotSubmittedResolution | None:
        with self._lock:
            resolution = self._not_submitted.get(client_order_id)
            if resolution is None:
                return None
            if resolution.request_fingerprint != request_fingerprint:
                raise ValueError("client_order_id was reused with a different request")
            return resolution

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
                and client_order_id not in self._resolutions
                and client_order_id not in self._not_submitted
            )

    def list_pending_contexts(self) -> tuple[PendingExecutionContext, ...]:
        return tuple(
            record.context
            for record in self.list_pending_recovery_records()
            if record.context is not None
        )
