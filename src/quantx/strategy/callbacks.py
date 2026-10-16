"""Optional observe-only strategy callbacks and deterministic failure records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from quantx.domain.enums import OrderStatus
from quantx.domain.orders import Fill
from quantx.domain.value_objects import InstrumentId

from .context import StrategyContext
from .timers import TimerInvocation


@dataclass(frozen=True, slots=True)
class OrderUpdateFact:
    """Immutable normalized order-status observation delivered after commit."""

    client_order_id: str
    instrument: InstrumentId
    status: OrderStatus
    order_quantity: Decimal
    filled_quantity: Decimal
    remaining_quantity: Decimal | None
    created_at: datetime
    evidence_time: datetime
    reason: str | None = None
    effective_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.client_order_id.strip():
            raise ValueError("client_order_id must not be empty")
        if self.order_quantity <= 0:
            raise ValueError("order_quantity must be positive")
        if self.filled_quantity < 0 or self.filled_quantity > self.order_quantity:
            raise ValueError("filled_quantity must be between zero and order_quantity")
        if self.remaining_quantity is not None and not (
            Decimal("0") <= self.remaining_quantity <= self.order_quantity
        ):
            raise ValueError("remaining_quantity must be between zero and order_quantity")
        for name, value in (
            ("created_at", self.created_at),
            ("evidence_time", self.evidence_time),
            ("effective_at", self.effective_at),
        ):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError(f"{name} must be timezone-aware")
        object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
        object.__setattr__(self, "evidence_time", self.evidence_time.astimezone(UTC))
        if self.effective_at is not None:
            object.__setattr__(self, "effective_at", self.effective_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class CallbackFault:
    """Stable callback/pre-commit fault data without a traceback or wall-clock stamp."""

    callback_name: str
    identity: str
    exception_type: str
    message: str


@dataclass(frozen=True, slots=True)
class RunHaltRecord:
    """Run-level halt latch reason, distinct from committed execution facts."""

    kind: str
    as_of: datetime
    identity: str
    reason: str

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("halt as_of must be timezone-aware")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class TemporalIntegrityFault:
    """Unexpected future-effective execution evidence detected after it is preserved."""

    source: str
    identity: str
    expected_at: datetime
    effective_at: datetime
    reason: str

    def __post_init__(self) -> None:
        for name, value in (("expected_at", self.expected_at), ("effective_at", self.effective_at)):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        object.__setattr__(self, "expected_at", self.expected_at.astimezone(UTC))
        object.__setattr__(self, "effective_at", self.effective_at.astimezone(UTC))


def callback_fault(
    callback_name: str,
    identity: str,
    error: Exception,
) -> CallbackFault:
    """Make a traceback-free, locally inspectable fault record."""
    return CallbackFault(
        callback_name=callback_name,
        identity=identity,
        exception_type=type(error).__name__,
        message=str(error),
    )


def _invoke_observer(
    target: object,
    callback_name: str,
    context: StrategyContext,
    value: object,
    identity: str,
) -> CallbackFault | None:
    callback: Any = getattr(target, callback_name, None)
    if callback is None:
        return None
    if not callable(callback):
        return CallbackFault(
            callback_name,
            identity,
            "TypeError",
            f"{callback_name} callback is not callable",
        )
    try:
        returned = callback(context, value)
    except Exception as exc:
        return callback_fault(callback_name, identity, exc)
    if returned is not None:
        return CallbackFault(
            callback_name,
            identity,
            "TypeError",
            f"{callback_name} callback must return None",
        )
    return None


def dispatch_timer_callback(
    target: object,
    context: StrategyContext,
    timer: TimerInvocation,
) -> CallbackFault | None:
    """Invoke one optional timer observer without allowing timer re-registration."""
    if context.event is not None:
        return CallbackFault(
            "on_timer",
            timer.timer_id,
            "ValueError",
            "timer callback context must not contain a market event",
        )
    if context.as_of != timer.due_at:
        return CallbackFault(
            "on_timer",
            timer.timer_id,
            "ValueError",
            "timer callback context as_of must equal timer due_at",
        )
    return _invoke_observer(target, "on_timer", context, timer, timer.timer_id)


def dispatch_post_commit_callbacks(
    target: object,
    context: StrategyContext,
    fills: tuple[Fill, ...],
    order_update: OrderUpdateFact,
) -> tuple[CallbackFault, ...]:
    """Attempt every on_fill in receipt order, then exactly one order update."""
    faults: list[CallbackFault] = []
    for fill in fills:
        fault = _invoke_observer(
            target,
            "on_fill",
            context,
            fill,
            str(fill.execution_id),
        )
        if fault is not None:
            faults.append(fault)
    fault = _invoke_observer(
        target,
        "on_order_update",
        context,
        order_update,
        order_update.client_order_id,
    )
    if fault is not None:
        faults.append(fault)
    return tuple(faults)
