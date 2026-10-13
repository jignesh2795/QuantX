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

Continuation child receipts satisfy the invariant through the documented
parent/child correlation contract: a receipt whose ``client_order_id``
does not match the request but whose ``correlation_id`` matches the
accepted parent correlation is treated as a valid child receipt. All
remaining identity fields are still validated.

Paper/replay receipts are not subject to the LIVE-only provenance checks
(``account_id``, ``connection_id``, ``order_quantity``) because those
fields are legitimately absent from simulated receipts.
"""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.execution_request import ApprovedExecutionRequest

from .models import ExecutionReceipt


@dataclass(frozen=True, slots=True)
class ReceiptIdentityViolation:
    """Non-empty reason string describing the first identity violation found."""

    reason: str


def validate_live_receipt_identity(
    request: ApprovedExecutionRequest,
    receipt: ExecutionReceipt,
    *,
    accepted_correlation: str | None = None,
) -> ReceiptIdentityViolation | None:
    """Validate that a LIVE broker receipt is bound to the approved request.

    Returns ``None`` when the receipt passes all checks, or a
    ``ReceiptIdentityViolation`` with a diagnostic reason on the first
    failure. The caller must treat any violation as an unresolved outcome
    (UNKNOWN), keep the idempotency reservation pending, and not persist
    the foreign receipt as authoritative evidence.

    Parameters
    ----------
    request:
        The approved execution request whose identity the receipt must match.
    receipt:
        The broker-returned receipt to validate.
    accepted_correlation:
        The accepted parent correlation string for a continuation child receipt.
        When provided, a receipt whose ``client_order_id`` does not match the
        request's ``order.client_order_id`` is accepted if its
        ``correlation_id`` equals this value. All remaining identity checks
        still apply. Pass ``None`` for a normal (non-continuation) execution.
    """
    client_order_id = request.order.client_order_id
    order_quantity = request.order.quantity
    expected_account = request.execution_context.account_id
    expected_connection = request.execution_context.broker_connection_id

    # --- Client order identity -------------------------------------------------
    # A receipt must identify the requested order. A continuation child receipt
    # is the only documented exception: its ``client_order_id`` differs from the
    # parent but its ``correlation_id`` must equal the accepted parent correlation.
    if receipt.client_order_id != client_order_id:
        if accepted_correlation is None or receipt.correlation_id != accepted_correlation:
            return ReceiptIdentityViolation(
                reason=(
                    f"receipt client_order_id {receipt.client_order_id!r} does not match "
                    f"request client_order_id {client_order_id!r}"
                )
            )

    # --- Canonical order identity (optional field) ----------------------------
    # When present, order_id must match. For a normal (non-continuation) receipt
    # the expected order_id is the request's client_order_id; for a continuation
    # child it is the child's own client_order_id.
    if receipt.order_id is not None and receipt.order_id != receipt.client_order_id:
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


__all__ = [
    "ReceiptIdentityViolation",
    "validate_live_receipt_identity",
]
