from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.value_objects import InstrumentId
from quantx.execution.margin_ledger import MarginLedger


def test_set_required_amount_for_instrument_reconciles_multiple_reservations() -> None:
    ledger = MarginLedger(Decimal("3000"))
    instrument = InstrumentId("NSE", "TCS")
    first = uuid4()
    second = uuid4()

    ledger.reserve(first, Decimal("700"), instrument=instrument)
    ledger.reserve(second, Decimal("500"), instrument=instrument)

    updated = ledger.set_required_amount_for_instrument(instrument, Decimal("600"))

    assert ledger.state.used == Decimal("600")
    assert sum(item.outstanding for item in updated) == Decimal("600")


def test_set_required_amount_for_instrument_rejects_missing_reservation() -> None:
    ledger = MarginLedger(Decimal("3000"))

    with pytest.raises(KeyError, match="no margin reservation"):
        ledger.set_required_amount_for_instrument(
            InstrumentId("NSE", "TCS"),
            Decimal("100"),
        )
