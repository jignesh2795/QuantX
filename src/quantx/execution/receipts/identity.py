"""Request-bound receipt identity validation for authoritative LIVE execution.

A broker response must not be accepted as authoritative execution evidence
unless it is demonstrably bound to the approved request. This module
provides the single, reusable validation boundary that enforces the
identity invariant before any receipt is persisted or used to complete
an idempotency reservation.

The validator is deliberately narrow: it only rejects fields that are
present and wrong, or required-for-LIVE and absent. It does not
reinterpret the receipt in any way; a failed validation always returns
the diagnostic reason without inventing an alternative outcome.

Correlation contract (per operation, derived from the request itself):

- A normal LIVE request carries ``correlation_id == str(order.client_order_id)``;
  the receipt must carry that exact correlation.
- A continuation child request carries
  ``correlation_id == parent_client_order_id``; the receipt must carry that
  exact parent correlation. This matches the documented parent/child claim
  contract enforced by ``ExecutionContinuationService``.
- The receipt's ``client_order_id`` must always equal the request's
  ``order.client_order_id``. A differing client-order id is never accepted
  merely because some correlation value matches; the continuation child
  receipt legitimately satisfies both rules because the child request's own
  order id is the receipt identity and the parent correlation is the child
  request's ``correlation_id``.

Required provenance on the authoritative LIVE boundary:

- ``correlation_id``: present and equal to the request correlation.
- ``order_id``: present and equal to the receipt ``client_order_id``
  (canonical order identity, stamped by every authoritative constructor).
- ``account_id``: present and equal to the request account.
- ``connection_id``: present and equal to the request broker connection.
- ``order_quantity``: present and equal to the requested quantity.
- ``source``: non-empty; an anonymous receipt cannot be attributed to the
  adapter that produced it.

Fields without a request-side expected value (``broker_order_id``,
``simulated``, model/assumption descriptors) are deliberately not enforced
here: the deterministic reference broker legitimately stamps
``simulated=True``, and the orchestrator already gates which adapter may
submit by connection/account identity before the broker call.

Paper/replay receipts are not subject to this validator at all; it is
invoked only on the authoritative LIVE submission boundary.

A failed validation always means: unresolved UNKNOWN outcome, the foreign
receipt is not persisted, the pending idempotency reservation stays
PENDING, and reconciliation remains responsible for the outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from quantx.domain.enums import OrderStatus
from quantx.domain.execution_request import ApprovedExecutionRequest

from .models import ExecutionOutcome, ExecutionReceipt


@dataclass(frozen=True, slots=True)
class ReceiptIdentityViolation:
    """Non-empty reason string describing the first identity violation found."""

    reason: str


def validate_receipt_runtime_shape(receipt: object) -> ReceiptIdentityViolation | None:
    """Validate a broker response's runtime shape before any attribute trust.

    The broker adapter is an untrusted plugin boundary: its response is
    typed as ``ExecutionReceipt``, but at runtime it can be any object, and
    the receipt dataclass accepts arbitrary runtime values for its enum and
    identity fields. A response outside the canonical contract must never
    reach request-identity validation, canonical persistence, idempotency
    completion or accounting — and, because it arrives after the external
    submit may have started, it must not raise out of the public execution
    call either.

    The returned reason is static: no broker-supplied value is echoed here,
    because it is recorded as sanitized, non-authoritative quarantine
    evidence rather than an authoritative rejection.
    """
    if not isinstance(receipt, ExecutionReceipt):
        return ReceiptIdentityViolation(reason="broker response is not an ExecutionReceipt")
    if not isinstance(receipt.outcome, ExecutionOutcome):
        return ReceiptIdentityViolation(
            reason="receipt outcome is not a canonical ExecutionOutcome"
        )
    if not isinstance(receipt.order_status, OrderStatus):
        return ReceiptIdentityViolation(
            reason="receipt order status is not a canonical OrderStatus"
        )
    # An enum-typed instance is not enough: a hostile response can carry an
    # uninitialized or value-shadowing member whose ``value`` lookup raises
    # or is not a string. Canonical persistence reads ``.value``, so such a
    # response must be rejected here, before identity validation and any
    # canonical write, instead of failing after the broker call.
    try:
        outcome_value = receipt.outcome.value
        order_status_value = receipt.order_status.value
    except Exception:
        return ReceiptIdentityViolation(reason="receipt enum members could not be read safely")
    if not isinstance(outcome_value, str) or not isinstance(order_status_value, str):
        return ReceiptIdentityViolation(
            reason="receipt enum members are not canonical string values"
        )
    if not isinstance(receipt.receipt_id, UUID):
        return ReceiptIdentityViolation(reason="receipt id is not a UUID")
    if not isinstance(receipt.source, str):
        return ReceiptIdentityViolation(reason="receipt source is not a string")
    if not isinstance(receipt.fills, tuple):
        return ReceiptIdentityViolation(reason="receipt fills are not a tuple")
    return None


def validate_live_receipt_identity(
    request: ApprovedExecutionRequest,
    receipt: ExecutionReceipt,
) -> ReceiptIdentityViolation | None:
    """Validate that a LIVE broker receipt is bound to the approved request.

    Returns ``None`` when the receipt passes all checks, or a
    ``ReceiptIdentityViolation`` with a diagnostic reason on the first
    failure. The caller must treat any violation as an unresolved outcome
    (UNKNOWN), keep the idempotency reservation pending, and not persist
    the foreign receipt as authoritative evidence.
    """
    client_order_id = request.order.client_order_id
    order_quantity = request.order.quantity
    expected_account = request.execution_context.account_id
    expected_connection = request.execution_context.broker_connection_id
    expected_correlation = request.correlation_id

    # --- Client order identity -------------------------------------------------
    # The receipt must identify the requested order. There is no accepted
    # exception: a continuation child request carries its own client_order_id,
    # so a matching receipt satisfies this rule directly.
    if receipt.client_order_id != client_order_id:
        return ReceiptIdentityViolation(
            reason=(
                f"receipt client_order_id {receipt.client_order_id!r} does not match "
                f"request client_order_id {client_order_id!r}"
            )
        )

    # --- Correlation identity (required for authoritative LIVE) ----------------
    # Normal requests expect str(order.client_order_id); continuation child
    # requests expect the parent client_order_id. Absent or foreign
    # correlation is rejected in both cases.
    if receipt.correlation_id is None:
        return ReceiptIdentityViolation(
            reason=(
                "receipt correlation_id is absent; "
                "authoritative LIVE receipt must carry the request correlation"
            )
        )
    if receipt.correlation_id != expected_correlation:
        return ReceiptIdentityViolation(
            reason=(
                f"receipt correlation_id {receipt.correlation_id!r} does not match "
                f"request correlation {expected_correlation!r}"
            )
        )

    # --- Canonical order identity (required for authoritative LIVE) ------------
    # Every authoritative constructor (from_order, broker adapters) stamps the
    # canonical order identity; a receipt without it did not come from a
    # known authoritative construction path.
    if receipt.order_id is None:
        return ReceiptIdentityViolation(
            reason=(
                "receipt order_id is absent; "
                "authoritative LIVE receipt must carry the canonical order identity"
            )
        )
    if receipt.order_id != receipt.client_order_id:
        return ReceiptIdentityViolation(
            reason=(
                f"receipt order_id {receipt.order_id!r} does not match "
                f"receipt client_order_id {receipt.client_order_id!r}"
            )
        )

    # --- Account identity (required for authoritative LIVE) -------------------
    if receipt.account_id is None:
        return ReceiptIdentityViolation(
            reason=(
                "receipt account_id is absent; authoritative LIVE receipt must identify the account"
            )
        )
    if receipt.account_id != expected_account:
        return ReceiptIdentityViolation(
            reason=(
                f"receipt account_id {receipt.account_id!r} does not match "
                f"request account_id {expected_account!r}"
            )
        )

    # --- Connection identity (required for authoritative LIVE) ----------------
    if receipt.connection_id is None:
        return ReceiptIdentityViolation(
            reason=(
                "receipt connection_id is absent; "
                "authoritative LIVE receipt must identify the broker connection"
            )
        )
    if receipt.connection_id != expected_connection:
        return ReceiptIdentityViolation(
            reason=(
                f"receipt connection_id {receipt.connection_id!r} does not match "
                f"request connection_id {expected_connection!r}"
            )
        )

    # --- Order quantity (required for authoritative LIVE) ---------------------
    # Authoritative receipt quantity metadata must be present and match
    # the requested order quantity.
    if receipt.order_quantity is None:
        return ReceiptIdentityViolation(
            reason=(
                "receipt order_quantity is absent; "
                "authoritative LIVE receipt must carry the requested order quantity"
            )
        )
    if receipt.order_quantity != order_quantity:
        return ReceiptIdentityViolation(
            reason=(
                f"receipt order_quantity {receipt.order_quantity!r} does not match "
                f"request quantity {order_quantity!r}"
            )
        )

    # --- Source provenance (required for authoritative LIVE) ------------------
    if not receipt.source.strip():
        return ReceiptIdentityViolation(
            reason=(
                "receipt source is absent; "
                "authoritative LIVE receipt must identify its producing adapter"
            )
        )

    # --- Fill identity --------------------------------------------------------
    # Every fill must belong to the expected order and match its instrument
    # and side. These are structural constraints that the receipt model already
    # enforces for receipts constructed via ``from_order``, but a receipt built
    # directly (e.g. by a foreign/stub broker) may bypass that constructor.
    expected_instrument = request.order.instrument
    expected_side = request.order.side
    for fill in receipt.fills:
        if fill.instrument != expected_instrument:
            return ReceiptIdentityViolation(
                reason=(
                    f"fill instrument {fill.instrument!r} does not match "
                    f"request instrument {expected_instrument!r}"
                )
            )
        if fill.side is not expected_side:
            return ReceiptIdentityViolation(
                reason=(f"fill side {fill.side!r} does not match request side {expected_side!r}")
            )

    # --- Fill arithmetic -------------------------------------------------------
    # Aggregate fill quantity must not exceed the requested quantity and must be
    # consistent with the reported receipt outcome. The receipt model validates
    # this for ``from_order`` receipts; re-check here for directly constructed
    # receipts.
    total_filled = receipt.filled_quantity
    if total_filled > order_quantity:
        return ReceiptIdentityViolation(
            reason=(
                f"aggregate fill quantity {total_filled!r} exceeds "
                f"request quantity {order_quantity!r}"
            )
        )

    return None


def validate_cached_receipt_identity(
    request: ApprovedExecutionRequest,
    *,
    receipt_id: UUID,
    receipt: object,
) -> ReceiptIdentityViolation | None:
    """Validate a receipt replayed from a completed idempotency reservation.

    A duplicate submission does not submit again: it returns the receipt already
    stored against the reservation, which then becomes the authoritative
    execution evidence for the request. That receipt must therefore be proven to
    belong to this request before it is returned or presented.

    This boundary is deliberately separate from
    :func:`validate_live_receipt_identity`. A receipt read back from storage may
    carry its ``client_order_id`` as the canonical string rendering of the same
    UUID (``ExecutionReceipt.client_order_id`` is ``UUID | str``). Exactly the
    canonical rendering is accepted as identity, and nothing else is parsed or
    normalised: a differently cased, braced, prefixed or padded string is a
    violation, never a coercion target.

    Reasons are static so a cached identity failure can be reported with a fixed
    reason while the diagnostic is kept as sanitized reconciliation evidence.
    """
    if type(receipt_id) is not UUID:
        return ReceiptIdentityViolation(reason="reservation receipt id is not an exact UUID")
    if not isinstance(receipt, ExecutionReceipt):
        return ReceiptIdentityViolation(reason="cached receipt is not an ExecutionReceipt")
    if type(receipt.receipt_id) is not UUID:
        return ReceiptIdentityViolation(reason="cached receipt id is not an exact UUID")
    if receipt.receipt_id != receipt_id:
        return ReceiptIdentityViolation(
            reason="cached receipt id does not match the reservation receipt id"
        )

    expected_client_order_id = request.order.client_order_id
    stored_client_order_id = receipt.client_order_id
    if type(stored_client_order_id) is UUID:
        if stored_client_order_id != expected_client_order_id:
            return ReceiptIdentityViolation(
                reason="cached receipt client_order_id does not match the request"
            )
    elif type(stored_client_order_id) is str:
        if stored_client_order_id != str(expected_client_order_id):
            return ReceiptIdentityViolation(
                reason="cached receipt client_order_id is not the canonical request identity"
            )
    else:
        return ReceiptIdentityViolation(
            reason="cached receipt client_order_id is not a UUID or canonical string"
        )

    if type(receipt.correlation_id) is not str or receipt.correlation_id != request.correlation_id:
        return ReceiptIdentityViolation(
            reason="cached receipt correlation_id does not match the request"
        )
    if type(receipt.order_id) is not UUID or receipt.order_id != expected_client_order_id:
        return ReceiptIdentityViolation(
            reason="cached receipt order_id does not match the request order identity"
        )

    expected_account = request.execution_context.account_id
    if receipt.account_id != expected_account:
        return ReceiptIdentityViolation(
            reason="cached receipt account_id does not match the request"
        )
    expected_connection = request.execution_context.broker_connection_id
    if receipt.connection_id != expected_connection:
        return ReceiptIdentityViolation(
            reason="cached receipt connection_id does not match the request"
        )
    if receipt.order_quantity != request.order.quantity:
        return ReceiptIdentityViolation(
            reason="cached receipt order_quantity does not match the request quantity"
        )
    if not isinstance(receipt.source, str) or not receipt.source.strip():
        return ReceiptIdentityViolation(reason="cached receipt source is absent")

    if not isinstance(receipt.outcome, ExecutionOutcome):
        return ReceiptIdentityViolation(reason="cached receipt outcome is not canonical")
    if receipt.outcome is ExecutionOutcome.UNKNOWN:
        return ReceiptIdentityViolation(
            reason="cached receipt outcome is UNKNOWN and cannot be authoritative"
        )

    return None


__all__ = [
    "ReceiptIdentityViolation",
    "validate_cached_receipt_identity",
    "validate_live_receipt_identity",
    "validate_receipt_runtime_shape",
]
