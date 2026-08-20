from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quantx.research.lifecycle import (
    ContractLifecycle,
    CorporateActionEvent,
    InstrumentLifecycle,
    LifecycleStatus,
)


def test_instrument_lifecycle_is_point_in_time() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    end = datetime(2025, 2, 1, tzinfo=timezone.utc)
    lifecycle = InstrumentLifecycle("ABC", start, end, LifecycleStatus.ACTIVE)

    assert lifecycle.contains(datetime(2025, 1, 15, tzinfo=timezone.utc))
    assert not lifecycle.contains(datetime(2025, 2, 1, tzinfo=timezone.utc))


def test_contract_is_not_tradable_after_expiry() -> None:
    contract = ContractLifecycle(
        instrument_id="ABC-FUT",
        contract_rule_version="2025-01",
        listed_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        expiry_at=datetime(2025, 1, 30, tzinfo=timezone.utc),
    )

    assert contract.tradable_at(datetime(2025, 1, 15, tzinfo=timezone.utc))
    assert not contract.tradable_at(datetime(2025, 1, 30, tzinfo=timezone.utc))


def test_corporate_action_is_explicit_and_point_in_time() -> None:
    event = CorporateActionEvent(
        event_id="split-1",
        instrument_id="ABC",
        effective_at=datetime(2025, 1, 10, tzinfo=timezone.utc),
        event_type="SPLIT",
        factor=Decimal("2"),
        adjustment_method="PRICE_AND_QUANTITY",
    )

    assert not event.applies_at(datetime(2025, 1, 9, tzinfo=timezone.utc))
    assert event.applies_at(datetime(2025, 1, 10, tzinfo=timezone.utc))


def test_lifecycle_requires_timezone_aware_dates() -> None:
    with pytest.raises(ValueError):
        InstrumentLifecycle("ABC", datetime(2025, 1, 1))
