"""Execution boundary contracts independent of broker implementations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.orders import Fill, OrderStatus


class ExecutionOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    request_id: UUID
    client_order_id: UUID
    outcome: ExecutionOutcome
    order_status: OrderStatus
    fills: tuple[Fill, ...] = ()
    external_order_id: str | None = None
    message: str = ""
    executed_at: datetime | None = None
    simulated: bool = False
    model_profile: str | None = None
    model_version: str | None = None
    assumptions: tuple[str, ...] = ()


class ExecutionPort(Protocol):
    def execute(self, request: ApprovedExecutionRequest) -> ExecutionReceipt:
        """Execute an already risk-approved request."""
