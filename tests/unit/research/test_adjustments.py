from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.research.adjustments import (
    AdjustmentEvent,
    AdjustmentPolicy,
    HistoricalAdjuster,
)


def test_raw_policy_does_not_change_value() -> None:
    value, provenance = HistoricalAdjuster().apply(
        Decimal("100"), (), policy=AdjustmentPolicy.RAW
    )
    assert value == Decimal("100")
    assert provenance.policy is AdjustmentPolicy.RAW


def test_explicit_adjustment_factor_is_applied_and_recorded() -> None:
    event = AdjustmentEvent(
        "evt-1",
        "SPLIT",
        datetime(2025, 1, 1, tzinfo=UTC),
        Decimal("0.5"),
        "source-1",
    )
    value, provenance = HistoricalAdjuster().apply(
        Decimal("100"),
        (event,),
        policy=AdjustmentPolicy.ADJUSTED,
        as_of=datetime(2025, 1, 2, tzinfo=UTC),
    )
    assert value == Decimal("50")
    assert provenance.event_ids == ("evt-1",)
    assert provenance.source_ids == ("source-1",)


def test_adjustment_does_not_infer_missing_events() -> None:
    value, provenance = HistoricalAdjuster().apply(
        Decimal("100"),
        (),
        policy=AdjustmentPolicy.EVENT_RECONSTRUCTED,
        as_of=datetime(2025, 1, 2, tzinfo=UTC),
    )
    assert value == Decimal("100")
    assert provenance.event_ids == ()


def test_adjustment_event_requires_positive_factor() -> None:
    with pytest.raises(ValueError):
        AdjustmentEvent(
            "evt-1",
            "SPLIT",
            datetime(2025, 1, 1, tzinfo=UTC),
            Decimal("0"),
        )


def test_future_adjustment_is_excluded_from_historical_value() -> None:
    event = AdjustmentEvent(
        "future",
        "SPLIT",
        datetime(2025, 2, 1, tzinfo=UTC),
        Decimal("0.5"),
    )
    value, provenance = HistoricalAdjuster().apply(
        Decimal("100"),
        (event,),
        policy=AdjustmentPolicy.ADJUSTED,
        as_of=datetime(2025, 1, 15, tzinfo=UTC),
    )
    assert value == Decimal("100")
    assert provenance.event_ids == ()


def test_adjusted_policy_requires_point_in_time_cutoff() -> None:
    event = AdjustmentEvent(
        "evt-1", "SPLIT", datetime(2025, 1, 1, tzinfo=UTC), Decimal("0.5")
    )
    with pytest.raises(ValueError, match="as_of is required"):
        HistoricalAdjuster().apply(
            Decimal("100"), (event,), policy=AdjustmentPolicy.ADJUSTED
        )


def test_adjusted_policy_requires_timezone_aware_cutoff() -> None:
    event = AdjustmentEvent(
        "evt-1", "SPLIT", datetime(2025, 1, 1, tzinfo=UTC), Decimal("0.5")
    )
    with pytest.raises(ValueError, match="as_of must be timezone-aware"):
        HistoricalAdjuster().apply(
            Decimal("100"),
            (event,),
            policy=AdjustmentPolicy.ADJUSTED,
            as_of=datetime(2025, 1, 2),
        )
