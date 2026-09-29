from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.enums import OrderStatus
from quantx.execution.receipts.lifecycle import ExecutionLifecycle


def test_partial_lifecycle_exposes_safe_continuation_quantity() -> None:
    lifecycle = ExecutionLifecycle(
        uuid4(),
        Decimal("10"),
        filled_quantity=Decimal("4"),
        status=OrderStatus.PARTIALLY_FILLED,
    )

    assert lifecycle.can_continue
    assert lifecycle.continuation_quantity() == Decimal("6")
    assert lifecycle.continuation_quantity(Decimal("2")) == Decimal("2")


def test_continuation_cannot_exceed_evidenced_remainder() -> None:
    lifecycle = ExecutionLifecycle(
        uuid4(),
        Decimal("10"),
        filled_quantity=Decimal("4"),
        status=OrderStatus.PARTIALLY_FILLED,
    )

    with pytest.raises(ValueError, match="exceeds remaining"):
        lifecycle.continuation_quantity(Decimal("7"))


def test_completed_lifecycle_cannot_continue() -> None:
    lifecycle = ExecutionLifecycle(
        uuid4(),
        Decimal("10"),
        filled_quantity=Decimal("10"),
        status=OrderStatus.FILLED,
    )

    assert not lifecycle.can_continue
    with pytest.raises(ValueError, match="no remaining"):
        lifecycle.continuation_quantity()
