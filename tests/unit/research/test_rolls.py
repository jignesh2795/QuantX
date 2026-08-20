from datetime import datetime, timezone
from decimal import Decimal

from quantx.domain.value_objects import InstrumentId
from quantx.research.rolls import (
    ContractRollEvent,
    ExplicitRollSchedule,
    RollMethod,
)


def test_explicit_roll_is_only_triggered_after_event_time() -> None:
    old_id = InstrumentId("NIFTY-FUT-2026-09")
    new_id = InstrumentId("NIFTY-FUT-2026-10")
    event = ContractRollEvent(
        timestamp=datetime(2026, 9, 20, tzinfo=timezone.utc),
        from_instrument=old_id,
        to_instrument=new_id,
        method=RollMethod.EXPLICIT,
        rule_id="nifty-roll",
        rule_version="1",
        old_price=Decimal("100"),
        new_price=Decimal("101"),
    )
    schedule = ExplicitRollSchedule((event,))

    before = schedule.decision_at(datetime(2026, 9, 19, tzinfo=timezone.utc), old_id)
    after = schedule.decision_at(datetime(2026, 9, 20, tzinfo=timezone.utc), old_id)

    assert before.should_roll is False
    assert after.should_roll is True
    assert after.next_instrument == new_id


def test_no_missing_data_inference_for_rolls() -> None:
    active_id = InstrumentId("NIFTY-FUT-2026-09")
    schedule = ExplicitRollSchedule(())
    decision = schedule.decision_at(datetime(2026, 9, 20, tzinfo=timezone.utc), active_id)

    assert decision.should_roll is False
    assert decision.next_instrument is None
    assert decision.reason == "no explicit roll event available"
