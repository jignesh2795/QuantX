"""Order-level execution lifecycle state derived from immutable receipts."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from quantx.domain.enums import OrderStatus
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.orders import Order
from quantx.domain.policy import PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult

from ..order_lifecycle import _reduce_order_status, is_terminal_order_status
from .models import ExecutionEvidenceKind, ExecutionReceipt


@dataclass(frozen=True, slots=True)
class ExecutionLifecycle:
    client_order_id: UUID | str
    order_quantity: Decimal
    filled_quantity: Decimal = Decimal("0")
    status: OrderStatus = OrderStatus.CREATED
    requires_reconciliation: bool = False
    anomalies: tuple[str, ...] = ()
    observed_filled_quantity: Decimal | None = None
    # Tracks whether any additive execution-delta evidence has been applied.
    # Cumulative observations after deltas (or vice versa) are mixed provenance
    # and cannot be reconciled without disjointness proof.  A lifecycle fed
    # only cumulative observations must remain clean, even once positive.
    delta_evidence_seen: bool = False

    def __post_init__(self) -> None:
        if self.order_quantity <= 0:
            raise ValueError("order_quantity must be positive")
        if self.filled_quantity < 0 or self.filled_quantity > self.order_quantity:
            raise ValueError("filled_quantity must be within order quantity")
        if self.status is OrderStatus.UNKNOWN and not self.requires_reconciliation:
            object.__setattr__(self, "requires_reconciliation", True)
        if any(not anomaly.strip() for anomaly in self.anomalies):
            raise ValueError("lifecycle anomalies must be non-empty")

    @property
    def remaining_quantity(self) -> Decimal:
        return self.order_quantity - self.filled_quantity

    @property
    def can_continue(self) -> bool:
        """Whether another separately approved execution may target the remainder.

        An anomaly or UNKNOWN state blocks progression even when partial fill
        evidence exists. A new child requires a clean, reconciled remainder.
        """
        return (
            not self.requires_reconciliation
            and self.remaining_quantity > 0
            and self.status is OrderStatus.PARTIALLY_FILLED
        )

    def continuation_client_order_id(self, requested_quantity: Decimal) -> UUID:
        """Derive a deterministic child identity for this continuation attempt."""
        quantity = self.continuation_quantity(requested_quantity)
        namespace = (
            self.client_order_id
            if isinstance(self.client_order_id, UUID)
            else uuid5(NAMESPACE_URL, str(self.client_order_id))
        )
        return uuid5(namespace, f"continuation:{self.filled_quantity}:{quantity}")

    def continuation_request(
        self,
        request: ApprovedExecutionRequest,
        *,
        risk_result: RiskResult,
        policy_result: PolicyResult | None = None,
        required_margin: Decimal = Decimal("0"),
        requested_quantity: Decimal | None = None,
    ) -> ApprovedExecutionRequest:
        """Build a separately approved request for only the evidenced remainder."""
        if request.order.client_order_id != self.client_order_id:
            raise ValueError("request client_order_id does not match lifecycle")
        quantity = self.continuation_quantity(requested_quantity)
        if risk_result.decision is not RiskDecision.APPROVE:
            raise ValueError("continuation requires a fresh approved risk result")
        if required_margin < 0:
            raise ValueError("required_margin cannot be negative")
        child_order = Order(
            instrument=request.order.instrument,
            side=request.order.side,
            order_type=request.order.order_type,
            quantity=quantity,
            limit_price=request.order.limit_price,
            stop_price=request.order.stop_price,
            time_in_force=request.order.time_in_force,
            intent_id=request.order.intent_id,
            client_order_id=self.continuation_client_order_id(quantity),
            strategy_id=request.order.strategy_id,
            strategy_version=request.order.strategy_version,
            required_capabilities=request.order.required_capabilities,
            product=request.order.product,
            position_effect=request.order.position_effect,
        )
        return ApprovedExecutionRequest(
            order=child_order,
            execution_context=request.execution_context,
            risk_result=risk_result,
            policy_result=policy_result,
            required_margin=required_margin,
            parent_client_order_id=str(self.client_order_id),
            product=request.product,
            position_effect=request.position_effect,
            effective_position_effect=request.effective_position_effect,
            position_evidence_cut=request.position_evidence_cut,
            position_evidence=request.position_evidence,
            position_evidence_max_age=request.position_evidence_max_age,
        )

    def continuation_quantity(self, requested_quantity: Decimal | None = None) -> Decimal:
        """Return a safe continuation quantity without creating a new order.

        A continuation must be a new, separately approved execution request.
        This method only constrains its quantity to the currently evidenced
        remainder; it never reuses the original client-order identity.
        """
        if not self.can_continue:
            raise ValueError("execution lifecycle has no remaining partially-filled quantity")
        if requested_quantity is None:
            return self.remaining_quantity
        if requested_quantity <= 0:
            raise ValueError("continuation quantity must be positive")
        if requested_quantity > self.remaining_quantity:
            raise ValueError("continuation quantity exceeds remaining order quantity")
        return requested_quantity

    @property
    def is_complete(self) -> bool:
        """Whether this order has a resolved final state.

        UNKNOWN and any unresolved contradiction are not complete: they require
        authoritative reconciliation. A clean cancelled/rejected order may be
        complete while still having a positive, unfilled remainder.
        """
        if self.status is OrderStatus.UNKNOWN or self.requires_reconciliation:
            return False
        return self.remaining_quantity == 0 or self.status in {
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.FAILED,
        }

    @classmethod
    def rebuild(
        cls,
        client_order_id: UUID | str,
        order_quantity: Decimal,
        receipts: tuple[ExecutionReceipt, ...] | list[ExecutionReceipt],
        *,
        correlation_id: UUID | str | None = None,
    ) -> ExecutionLifecycle:
        """Reconstruct lifecycle from receipts without granting reconciliation authority."""
        return cls._rebuild(
            client_order_id,
            order_quantity,
            receipts,
            correlation_id=correlation_id,
            reconciliation_authorized=False,
        )

    @classmethod
    def rebuild_from_reconciliation(
        cls,
        client_order_id: UUID | str,
        order_quantity: Decimal,
        receipts: tuple[ExecutionReceipt, ...] | list[ExecutionReceipt],
        *,
        correlation_id: UUID | str | None = None,
    ) -> ExecutionLifecycle:
        """Rebuild through the explicit trusted reconciliation entrypoint."""
        return cls._rebuild(
            client_order_id,
            order_quantity,
            receipts,
            correlation_id=correlation_id,
            reconciliation_authorized=True,
        )

    @classmethod
    def _rebuild(
        cls,
        client_order_id: UUID | str,
        order_quantity: Decimal,
        receipts: tuple[ExecutionReceipt, ...] | list[ExecutionReceipt],
        *,
        correlation_id: UUID | str | None,
        reconciliation_authorized: bool,
    ) -> ExecutionLifecycle:
        unique: dict[UUID, ExecutionReceipt] = {}
        for receipt in receipts:
            existing = unique.get(receipt.receipt_id)
            if existing is not None:
                if existing != receipt:
                    raise ValueError("receipt ID maps to conflicting receipt data")
                continue
            unique[receipt.receipt_id] = receipt

        lifecycle = cls(client_order_id, order_quantity)
        ordered = sorted(
            unique.values(),
            key=lambda receipt: (receipt.executed_at, str(receipt.receipt_id)),
        )
        for receipt in ordered:
            lifecycle = lifecycle._apply_receipt(
                receipt,
                correlation_id=correlation_id,
                reconciliation_authorized=reconciliation_authorized,
            )
        return lifecycle

    def apply(
        self,
        receipt: ExecutionReceipt,
        *,
        correlation_id: UUID | str | None = None,
    ) -> ExecutionLifecycle:
        """Apply ordinary receipt evidence; UNKNOWN cannot be resolved here."""
        return self._apply_receipt(
            receipt,
            correlation_id=correlation_id,
            reconciliation_authorized=False,
        )

    def apply_from_reconciliation(
        self,
        receipt: ExecutionReceipt,
        *,
        correlation_id: UUID | str | None = None,
    ) -> ExecutionLifecycle:
        """Apply a receipt through the explicit trusted reconciliation path."""
        return self._apply_receipt(
            receipt,
            correlation_id=correlation_id,
            reconciliation_authorized=True,
        )

    def _apply_receipt(
        self,
        receipt: ExecutionReceipt,
        *,
        correlation_id: UUID | str | None,
        reconciliation_authorized: bool,
    ) -> ExecutionLifecycle:
        accepted_correlation = (
            str(correlation_id) if correlation_id is not None else str(self.client_order_id)
        )
        if (
            receipt.client_order_id != self.client_order_id
            and receipt.correlation_id != accepted_correlation
        ):
            raise ValueError("receipt does not belong to lifecycle")

        # Determine the quantity contribution based on evidence kind.
        anomaly_list = list(self.anomalies)

        def flag_anomaly(message: str) -> None:
            if message not in anomaly_list:
                anomaly_list.append(message)

        if receipt.evidence_kind is ExecutionEvidenceKind.EXECUTION_DELTAS:
            new_filled = self.filled_quantity + receipt.filled_quantity
            if receipt.filled_quantity == Decimal("0"):
                # Zero-fill delta receipt contributes status only; preserve
                # existing observed_filled_quantity
                new_observed = self.observed_filled_quantity
            else:
                new_observed = None
            new_delta_seen = self.delta_evidence_seen or receipt.filled_quantity > Decimal("0")
            if new_delta_seen and self.observed_filled_quantity is not None:
                flag_anomaly(
                    "mixed cumulative observation and execution delta evidence without "
                    "disjointness proof"
                )
                return ExecutionLifecycle(
                    client_order_id=self.client_order_id,
                    order_quantity=self.order_quantity,
                    filled_quantity=self.filled_quantity,
                    status=OrderStatus.UNKNOWN,
                    requires_reconciliation=True,
                    anomalies=tuple(anomaly_list),
                    observed_filled_quantity=self.observed_filled_quantity,
                    delta_evidence_seen=self.delta_evidence_seen,
                )
            if new_filled > self.order_quantity:
                raise ValueError("cumulative fills exceed order quantity")
        elif receipt.evidence_kind is ExecutionEvidenceKind.CUMULATIVE_OBSERVATION:
            if self.delta_evidence_seen:
                flag_anomaly(
                    "mixed cumulative observation and execution delta evidence without "
                    "disjointness proof"
                )
                return ExecutionLifecycle(
                    client_order_id=self.client_order_id,
                    order_quantity=self.order_quantity,
                    filled_quantity=self.filled_quantity,
                    status=OrderStatus.UNKNOWN,
                    requires_reconciliation=True,
                    anomalies=tuple(anomaly_list),
                    observed_filled_quantity=self.observed_filled_quantity,
                    delta_evidence_seen=self.delta_evidence_seen,
                )
            observed = receipt.observed_filled_quantity
            assert observed is not None  # validated at receipt construction
            prev_observed = self.observed_filled_quantity
            if prev_observed is not None:
                if observed < prev_observed:
                    flag_anomaly(
                        f"cumulative observation decreased from {prev_observed} to {observed}"
                    )
                    return ExecutionLifecycle(
                        client_order_id=self.client_order_id,
                        order_quantity=self.order_quantity,
                        filled_quantity=self.filled_quantity,
                        status=OrderStatus.UNKNOWN,
                        requires_reconciliation=True,
                        anomalies=tuple(anomaly_list),
                        observed_filled_quantity=prev_observed,
                        delta_evidence_seen=self.delta_evidence_seen,
                    )
                if observed == prev_observed:
                    # Repeated identical cumulative quantity: no change.
                    new_filled = self.filled_quantity
                    new_observed = observed
                else:
                    new_filled = observed
                    new_observed = observed
            else:
                new_filled = observed
                new_observed = observed
            new_delta_seen = self.delta_evidence_seen
            if new_filled > self.order_quantity:
                flag_anomaly(
                    f"cumulative observation {new_filled} exceeds order quantity "
                    f"{self.order_quantity}"
                )
                return ExecutionLifecycle(
                    client_order_id=self.client_order_id,
                    order_quantity=self.order_quantity,
                    filled_quantity=self.filled_quantity,
                    status=OrderStatus.UNKNOWN,
                    requires_reconciliation=True,
                    anomalies=tuple(anomaly_list),
                    observed_filled_quantity=new_observed,
                    delta_evidence_seen=self.delta_evidence_seen,
                )
        else:
            raise ValueError(f"unsupported evidence kind: {receipt.evidence_kind}")

        # The shared reducer owns terminal absorption, UNKNOWN authority, and
        # quantity-driven status decisions for a normal order receipt.
        #
        # For cumulative observations the evidenced total is ``new_filled`` (the
        # monotonic observed quantity), not ``self.filled_quantity``.  Feeding the
        # observed total as ``current_filled`` with a zero delta lets the shared
        # reducer judge status against the real quantity without inventing a
        # synthetic fill or double-counting the observation.
        is_cumulative = receipt.evidence_kind is ExecutionEvidenceKind.CUMULATIVE_OBSERVATION
        reducer_current_filled = new_filled if is_cumulative else self.filled_quantity
        reducer_added_fill = Decimal("0") if is_cumulative else receipt.filled_quantity
        if is_terminal_order_status(self.status):
            reduction = _reduce_order_status(
                self.status,
                receipt.order_status,
                current_filled=reducer_current_filled,
                added_fill=reducer_added_fill,
                order_quantity=self.order_quantity,
                requires_reconciliation=self.requires_reconciliation,
                anomalies=self.anomalies,
                reconciliation_authorized=reconciliation_authorized,
            )
            merged_anomalies = list(reduction.anomalies)
            for a in anomaly_list:
                if a not in merged_anomalies:
                    merged_anomalies.append(a)
            return ExecutionLifecycle(
                client_order_id=self.client_order_id,
                order_quantity=self.order_quantity,
                filled_quantity=new_filled,
                status=reduction.status,
                requires_reconciliation=reduction.requires_reconciliation,
                anomalies=tuple(merged_anomalies),
                observed_filled_quantity=new_observed,
                delta_evidence_seen=new_delta_seen,
            )

        # A correlated child receipt contributes quantity to the parent only;
        # its status cannot resolve or overwrite the parent's state.
        if str(receipt.client_order_id) != str(self.client_order_id):
            if self.status is OrderStatus.UNKNOWN or receipt.order_status is OrderStatus.UNKNOWN:
                if receipt.order_status is OrderStatus.UNKNOWN:
                    flag_anomaly("correlated child receipt has UNKNOWN status")
                else:
                    flag_anomaly("correlated child receipt cannot resolve parent UNKNOWN status")
                return ExecutionLifecycle(
                    client_order_id=self.client_order_id,
                    order_quantity=self.order_quantity,
                    filled_quantity=new_filled,
                    status=OrderStatus.UNKNOWN,
                    requires_reconciliation=True,
                    anomalies=tuple(anomaly_list),
                    observed_filled_quantity=new_observed,
                    delta_evidence_seen=new_delta_seen,
                )
            if new_filled == self.order_quantity:
                return ExecutionLifecycle(
                    client_order_id=self.client_order_id,
                    order_quantity=self.order_quantity,
                    filled_quantity=new_filled,
                    status=OrderStatus.FILLED,
                    requires_reconciliation=self.requires_reconciliation,
                    anomalies=tuple(anomaly_list),
                    observed_filled_quantity=new_observed,
                    delta_evidence_seen=new_delta_seen,
                )
            if new_filled > 0:
                return ExecutionLifecycle(
                    client_order_id=self.client_order_id,
                    order_quantity=self.order_quantity,
                    filled_quantity=new_filled,
                    status=OrderStatus.PARTIALLY_FILLED,
                    requires_reconciliation=self.requires_reconciliation,
                    anomalies=tuple(anomaly_list),
                    observed_filled_quantity=new_observed,
                    delta_evidence_seen=new_delta_seen,
                )
            return ExecutionLifecycle(
                client_order_id=self.client_order_id,
                order_quantity=self.order_quantity,
                filled_quantity=new_filled,
                status=self.status,
                requires_reconciliation=self.requires_reconciliation,
                anomalies=tuple(anomaly_list),
                observed_filled_quantity=new_observed,
                delta_evidence_seen=new_delta_seen,
            )

        reduction = _reduce_order_status(
            self.status,
            receipt.order_status,
            current_filled=reducer_current_filled,
            added_fill=reducer_added_fill,
            order_quantity=self.order_quantity,
            requires_reconciliation=self.requires_reconciliation,
            anomalies=self.anomalies,
            reconciliation_authorized=reconciliation_authorized,
        )
        merged_anomalies = list(reduction.anomalies)
        for a in anomaly_list:
            if a not in merged_anomalies:
                merged_anomalies.append(a)
        return ExecutionLifecycle(
            client_order_id=self.client_order_id,
            order_quantity=self.order_quantity,
            filled_quantity=new_filled,
            status=reduction.status,
            requires_reconciliation=reduction.requires_reconciliation,
            anomalies=tuple(merged_anomalies),
            observed_filled_quantity=new_observed,
            delta_evidence_seen=new_delta_seen,
        )
