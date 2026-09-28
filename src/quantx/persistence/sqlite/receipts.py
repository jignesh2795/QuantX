"""SQLite-backed authoritative receipt repository."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from quantx.domain.enums import OrderSide, OrderStatus
from quantx.domain.orders import Fill
from quantx.domain.value_objects import AccountId, BrokerConnectionId, InstrumentId
from quantx.execution.idempotency.fingerprint import _canonical_decimal
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt

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


def receipt_to_payload(receipt: ExecutionReceipt) -> str:
    """Serialize a receipt deterministically using only stdlib JSON."""
    payload = {
        "account_id": receipt.account_id.value if receipt.account_id is not None else None,
        "assumptions": list(receipt.assumptions),
        "broker_order_id": receipt.broker_order_id,
        "client_order_id": _client_order_id_to_str(receipt.client_order_id),
        "connection_id": receipt.connection_id.value if receipt.connection_id is not None else None,
        "correlation_id": receipt.correlation_id,
        "executed_at": receipt.executed_at.isoformat(),
        "fee": _canonical_decimal(receipt.fee),
        "fills": [_fill_to_dict(fill) for fill in receipt.fills],
        "message": receipt.message,
        "model_profile": receipt.model_profile,
        "model_version": receipt.model_version,
        "order_id": str(receipt.order_id) if receipt.order_id is not None else None,
        "order_status": receipt.order_status.value,
        "outcome": receipt.outcome.value,
        "raw_reference": receipt.raw_reference,
        "receipt_id": str(receipt.receipt_id),
        "request_id": str(receipt.request_id),
        "simulated": receipt.simulated,
        "source": receipt.source,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def receipt_from_payload(payload: str) -> ExecutionReceipt:
    """Reconstruct a receipt through the canonical constructors for validation."""
    data = json.loads(payload)
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
        broker_order_id=data["broker_order_id"],
        raw_reference=data["raw_reference"],
        correlation_id=data["correlation_id"],
        receipt_id=UUID(data["receipt_id"]),
        order_id=UUID(data["order_id"]) if data["order_id"] is not None else None,
        account_id=AccountId(data["account_id"]) if data["account_id"] is not None else None,
        connection_id=BrokerConnectionId(data["connection_id"])
        if data["connection_id"] is not None
        else None,
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
