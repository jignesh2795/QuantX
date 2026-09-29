from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.execution.margin_ledger import MarginLedger


def test_margin_reservation_reduces_available_margin() -> None:
    ledger = MarginLedger(Decimal("10000"))
    reservation = ledger.reserve(uuid4(), Decimal("2500"))

    assert reservation.outstanding == Decimal("2500")
    assert ledger.state.used == Decimal("2500")
    assert ledger.state.available == Decimal("7500")


def test_partial_and_full_release_restore_available_margin() -> None:
    ledger = MarginLedger(Decimal("10000"))
    reservation_id = uuid4()
    ledger.reserve(reservation_id, Decimal("2500"))

    updated = ledger.release(reservation_id, Decimal("1000"))
    assert updated.outstanding == Decimal("1500")
    assert ledger.state.used == Decimal("1500")

    updated = ledger.release(reservation_id)
    assert updated.outstanding == Decimal("0")
    assert ledger.state.used == Decimal("0")
    assert ledger.state.available == Decimal("10000")


def test_reservation_cannot_overdraw_margin() -> None:
    ledger = MarginLedger(Decimal("1000"))

    with pytest.raises(ValueError, match="exceeds available margin"):
        ledger.reserve(uuid4(), Decimal("1001"))


def test_reservation_is_idempotency_unsafe_by_design() -> None:
    ledger = MarginLedger(Decimal("1000"))
    reservation_id = uuid4()
    ledger.reserve(reservation_id, Decimal("100"))

    with pytest.raises(ValueError, match="already exists"):
        ledger.reserve(reservation_id, Decimal("100"))
