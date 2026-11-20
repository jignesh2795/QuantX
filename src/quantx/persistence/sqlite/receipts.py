"""SQLite-backed authoritative receipt repository."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from quantx.domain.enums import OrderSide, OrderStatus
from quantx.domain.orders import Fill
from quantx.domain.value_objects import AccountId, BrokerConnectionId, InstrumentId
from quantx.execution.charges import ChargeBreakdown, ChargeComponent
from quantx.execution.idempotency.fingerprint import _canonical_decimal
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt
from quantx.execution.receipts.models import ExecutionEvidenceKind

from .database import SqliteDatabase


def _fill_to_dict(fill: Fill) -> dict[str, object]:
    return {
        "client_order_id": str(fill.client_order_id),
        "execution_id": str(fill.execution_id),
        "filled_at": fill.filled_at.isoformat(),
        "instrument": {"symbol": fill.instrument.symbol, "venue": fill.instrument.venue},
        "price": _canonical_decimal(fill.price),
        "quantity": _canonical_decimal(fill.quantity),
        "side": fill.side.value,
    }


def _client_order_id_to_str(client_order_id: UUID | str) -> str:
    return str(client_order_id)


def _client_order_id_from_str(value: str) -> UUID | str:
    try:
        return UUID(value)
    except ValueError:
        return value


def _charge_to_dict(charges: ChargeBreakdown) -> dict[str, object]:
    return {
        "components": [
            {"amount": _canonical_decimal(component.amount), "name": component.name}
            for component in charges.components
        ],
        "currency": charges.currency,
        "model_id": charges.model_id,
        "model_version": charges.model_version,
        "provenance": list(charges.provenance),
        "rounded_total": (
            _canonical_decimal(charges.rounded_total)
            if charges.rounded_total is not None
            else None
        ),
    }


def _charge_from_dict(data: dict[str, object]) -> ChargeBreakdown:
    raw_components = data["components"]
    if not isinstance(raw_components, list):
        raise ValueError("charge components payload must be a list")
    components: list[ChargeComponent] = []
    for item in raw_components:
        if not isinstance(item, dict):
            raise ValueError("charge components payload contains an invalid item")
        name = item.get("name")
        amount = item.get("amount")
        if not isinstance(name, str) or not isinstance(amount, str):
            raise ValueError("charge component payload requires string name and decimal amount")
        components.append(ChargeComponent(name=name, amount=Decimal(amount)))
    raw_currency = data["currency"]
    raw_rounded_total = data.get("rounded_total")
    raw_provenance = data["provenance"]
    if raw_currency is not None and not isinstance(raw_currency, str):
        raise ValueError("charge currency payload must be a string or None")
    if not isinstance(raw_provenance, list) or any(
        not isinstance(item, str) for item in raw_provenance
    ):
        raise ValueError("charge provenance payload must be a list of strings")
    if raw_rounded_total is not None and not isinstance(raw_rounded_total, str):
        raise ValueError("rounded charge total payload must be a decimal string or None")
    model_id = data["model_id"]
    model_version = data["model_version"]
    if not isinstance(model_id, str) or not isinstance(model_version, str):
        raise ValueError("charge model identity payload must contain strings")
    return ChargeBreakdown(
        currency=raw_currency,
        components=tuple(components),
        model_id=model_id,
        model_version=model_version,
        provenance=tuple(raw_provenance),
        rounded_total=(
            Decimal(raw_rounded_total) if raw_rounded_total is not None else None
        ),
    )


def receipt_to_payload(receipt: ExecutionReceipt) -> str:
    """Serialize a receipt deterministically using only stdlib JSON."""
    payload = {
        "account_id": receipt.account_id.value if receipt.account_id is not None else None,
        "assumptions": list(receipt.assumptions),
        "broker_order_id": receipt.broker_order_id,
        "client_order_id": _client_order_id_to_str(receipt.client_order_id),
        "connection_id": receipt.connection_id.value if receipt.connection_id is not None else None,
        "correlation_id": receipt.correlation_id,
        "evidence_kind": receipt.evidence_kind.value,
        "executed_at": receipt.executed_at.isoformat(),
        "fee": _canonical_decimal(receipt.fee),
        "fills": [_fill_to_dict(fill) for fill in receipt.fills],
        "message": receipt.message,
        "model_profile": receipt.model_profile,
        "model_version": receipt.model_version,
        "observed_average_price": (
            _canonical_decimal(receipt.observed_average_price)
            if receipt.observed_average_price is not None
            else None
        ),
        "observed_filled_quantity": (
            _canonical_decimal(receipt.observed_filled_quantity)
            if receipt.observed_filled_quantity is not None
            else None
        ),
        "order_id": str(receipt.order_id) if receipt.order_id is not None else None,
        "order_quantity": (
            _canonical_decimal(receipt.order_quantity)
            if receipt.order_quantity is not None
            else None
        ),
        "order_status": receipt.order_status.value,
        "outcome": receipt.outcome.value,
        "raw_reference": receipt.raw_reference,
        "receipt_id": str(receipt.receipt_id),
        "request_id": str(receipt.request_id),
        "simulated": receipt.simulated,
        "source": receipt.source,
    }
    if receipt.per_fill_charges:
        payload["per_fill_charges"] = [
            _charge_to_dict(item) for item in receipt.per_fill_charges
        ]
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def receipt_from_payload(payload: str) -> ExecutionReceipt:
    """Reconstruct a receipt through the canonical constructors for validation.

    Payloads written before the evidence-kind contract carry no
    ``evidence_kind`` and no ``observed_*`` observation fields.  Those rows are
    additive execution-delta receipts, so they default to
    ``ExecutionEvidenceKind.EXECUTION_DELTAS`` with no observation metadata.
    Reading them must not fabricate cumulative-observation evidence.
    """
    data = json.loads(payload)
    evidence_kind = ExecutionEvidenceKind(
        data.get("evidence_kind", ExecutionEvidenceKind.EXECUTION_DELTAS.value)
    )
    raw_observed_quantity = data.get("observed_filled_quantity")
    raw_observed_average_price = data.get("observed_average_price")
    fills = tuple(
        Fill(
            client_order_id=UUID(item["client_order_id"]),
            instrument=InstrumentId(
                venue=item["instrument"]["venue"], symbol=item["instrument"]["symbol"]
            ),
            side=OrderSide(item["side"]),
            quantity=Decimal(item["quantity"]),
            price=Decimal(item["price"]),
            filled_at=datetime.fromisoformat(item["filled_at"]),
            execution_id=UUID(item["execution_id"]),
        )
        for item in data["fills"]
    )
    raw_charges = data.get("charges")
    raw_per_fill_charges = data.get("per_fill_charges", [])
    if raw_charges is not None and not isinstance(raw_charges, dict):
        raise ValueError("receipt charges payload must be an object or None")
    if not isinstance(raw_per_fill_charges, list) or any(
        not isinstance(item, dict) for item in raw_per_fill_charges
    ):
        raise ValueError("receipt per-fill charges payload must be a list of objects")
    return ExecutionReceipt(
        request_id=UUID(data["request_id"]),
        client_order_id=_client_order_id_from_str(data["client_order_id"]),
        outcome=ExecutionOutcome(data["outcome"]),
        order_status=OrderStatus(data["order_status"]),
        executed_at=datetime.fromisoformat(data["executed_at"]),
        fills=fills,
        message=data["message"],
        simulated=data["simulated"],
        source=data["source"],
        model_profile=data["model_profile"],
        model_version=data["model_version"],
        assumptions=tuple(data["assumptions"]),
        fee=Decimal(data["fee"]),
        charges=_charge_from_dict(raw_charges) if raw_charges is not None else None,
        per_fill_charges=tuple(
            _charge_from_dict(item) for item in raw_per_fill_charges
        ),
        broker_order_id=data["broker_order_id"],
        raw_reference=data["raw_reference"],
        correlation_id=data["correlation_id"],
        receipt_id=UUID(data["receipt_id"]),
        order_id=UUID(data["order_id"]) if data["order_id"] is not None else None,
        order_quantity=(
            Decimal(data["order_quantity"]) if data["order_quantity"] is not None else None
        ),
        account_id=AccountId(data["account_id"]) if data["account_id"] is not None else None,
        connection_id=BrokerConnectionId(data["connection_id"])
        if data["connection_id"] is not None
        else None,
        evidence_kind=evidence_kind,
        observed_filled_quantity=(
            Decimal(raw_observed_quantity) if raw_observed_quantity is not None else None
        ),
        observed_average_price=(
            Decimal(raw_observed_average_price) if raw_observed_average_price is not None else None
        ),
    )


class SqliteReceiptRepository:
    """Authoritative persistent receipt boundary; rows are immutable."""

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def save(self, receipt: ExecutionReceipt) -> None:
        payload = receipt_to_payload(receipt)
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM receipts WHERE receipt_id = ?",
                (str(receipt.receipt_id),),
            ).fetchone()
            if row is not None:
                if row[0] != payload:
                    raise ValueError("cannot overwrite an existing receipt")
                return
            connection.execute(
                "INSERT INTO receipts (receipt_id, client_order_id, payload, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    str(receipt.receipt_id),
                    _client_order_id_to_str(receipt.client_order_id),
                    payload,
                    receipt.executed_at.isoformat(),
                ),
            )

    def get(self, receipt_id: UUID) -> ExecutionReceipt | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM receipts WHERE receipt_id = ?",
                (str(receipt_id),),
            ).fetchone()
        if row is None:
            return None
        return receipt_from_payload(row[0])

    def get_by_client_order(self, client_order_id: UUID) -> ExecutionReceipt | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM receipts WHERE client_order_id = ? ORDER BY rowid LIMIT 1",
                (str(client_order_id),),
            ).fetchone()
        if row is None:
            return None
        return receipt_from_payload(row[0])

    def list_by_correlation_id(self, correlation_id: UUID | str) -> tuple[ExecutionReceipt, ...]:
        """Return immutable receipts correlated to one parent lifecycle.

        Correlation is stored inside the canonical immutable payload. The
        query remains authoritative without introducing a second lifecycle
        state store.
        """
        with self._database.transaction() as connection:
            rows = connection.execute(
                "SELECT payload FROM receipts "
                "WHERE json_extract(payload, '$.correlation_id') = ? "
                "ORDER BY rowid",
                (str(correlation_id),),
            ).fetchall()
        return tuple(receipt_from_payload(row[0]) for row in rows)
