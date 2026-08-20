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
    event = AdjustmentEvent("evt-1", "SPLIT", "2025-01-01T00:00:00Z", Decimal("0.5"), "source-1")
    value, provenance = HistoricalAdjuster().apply(
        Decimal("100"), (event,), policy=AdjustmentPolicy.ADJUSTED
    )
    assert value == Decimal("50")
    assert provenance.event_ids == ("evt-1",)
    assert provenance.source_ids == ("source-1",)


def test_adjustment_does_not_infer_missing_events() -> None:
    value, provenance = HistoricalAdjuster().apply(
        Decimal("100"), (), policy=AdjustmentPolicy.EVENT_RECONSTRUCTED
    )
    assert value == Decimal("100")
    assert provenance.event_ids == ()


def test_adjustment_event_requires_positive_factor() -> None:
    with pytest.raises(ValueError):
        AdjustmentEvent("evt-1", "SPLIT", "2025-01-01T00:00:00Z", Decimal("0"))
