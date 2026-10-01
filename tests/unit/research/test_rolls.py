from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.value_objects import InstrumentId
from quantx.research.rolls import (
    ContractRollEvent,
    ExplicitRollSchedule,
    RollMethod,
)


def test_explicit_roll_is_only_triggered_after_event_time() -> None:
    old_id = InstrumentId("NSE", "NIFTY-FUT-2026-09")
    new_id = InstrumentId("NSE", "NIFTY-FUT-2026-10")
    event = ContractRollEvent(
        timestamp=datetime(2026, 9, 20, tzinfo=UTC),
        from_instrument=old_id,
        to_instrument=new_id,
        method=RollMethod.EXPLICIT,
        rule_id="nifty-roll",
        rule_version="1",
        old_price=Decimal("100"),
        new_price=Decimal("101"),
    )
    schedule = ExplicitRollSchedule((event,))

    before = schedule.decision_at(datetime(2026, 9, 19, tzinfo=UTC), old_id)
    after = schedule.decision_at(datetime(2026, 9, 20, tzinfo=UTC), old_id)

    assert before.should_roll is False
    assert after.should_roll is True
    assert after.next_instrument == new_id


def test_latest_roll_event_wins_for_same_active_contract() -> None:
    old_id = InstrumentId("NSE", "NIFTY-FUT-2026-09")
    first_target = InstrumentId("NSE", "NIFTY-FUT-2026-10")
    latest_target = InstrumentId("NSE", "NIFTY-FUT-2026-11")
    schedule = ExplicitRollSchedule(
        (
            ContractRollEvent(
                timestamp=datetime(2026, 9, 20, tzinfo=UTC),
                from_instrument=old_id,
                to_instrument=first_target,
                method=RollMethod.EXPLICIT,
                rule_id="nifty-roll",
                rule_version="1",
            ),
            ContractRollEvent(
                timestamp=datetime(2026, 9, 25, tzinfo=UTC),
                from_instrument=old_id,
                to_instrument=latest_target,
                method=RollMethod.EXPLICIT,
                rule_id="nifty-roll",
                rule_version="2",
            ),
        )
    )

    decision = schedule.decision_at(datetime(2026, 9, 26, tzinfo=UTC), old_id)

    assert decision.should_roll is True
    assert decision.next_instrument == latest_target
    assert decision.rule_version == "2"


def test_duplicate_roll_timestamp_is_rejected() -> None:
    old_id = InstrumentId("NSE", "NIFTY-FUT-2026-09")
    target = InstrumentId("NSE", "NIFTY-FUT-2026-10")
    timestamp = datetime(2026, 9, 20, tzinfo=UTC)

    with pytest.raises(ValueError, match="duplicate roll events"):
        ExplicitRollSchedule(
            (
                ContractRollEvent(
                    timestamp=timestamp,
                    from_instrument=old_id,
                    to_instrument=target,
                    method=RollMethod.EXPLICIT,
                    rule_id="nifty-roll",
                    rule_version="1",
                ),
                ContractRollEvent(
                    timestamp=timestamp,
                    from_instrument=old_id,
                    to_instrument=InstrumentId("NSE", "NIFTY-FUT-2026-11"),
                    method=RollMethod.EXPLICIT,
                    rule_id="nifty-roll",
                    rule_version="2",
                ),
            )
        )


def test_no_missing_data_inference_for_rolls() -> None:
    active_id = InstrumentId("NSE", "NIFTY-FUT-2026-09")
    schedule = ExplicitRollSchedule(())
    decision = schedule.decision_at(datetime(2026, 9, 20, tzinfo=UTC), active_id)

    assert decision.should_roll is False
    assert decision.next_instrument is None
    assert decision.reason == "no explicit roll event available"
