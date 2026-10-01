from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.research.lifecycle import (
    ContractLifecycle,
    CorporateActionEvent,
    InstrumentLifecycle,
    LifecycleStatus,
)


def test_instrument_lifecycle_is_point_in_time() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    end = datetime(2025, 2, 1, tzinfo=UTC)
    lifecycle = InstrumentLifecycle("ABC", start, end, LifecycleStatus.ACTIVE)

    assert lifecycle.contains(datetime(2025, 1, 15, tzinfo=UTC))
    assert not lifecycle.contains(datetime(2025, 2, 1, tzinfo=UTC))


def test_contract_is_not_tradable_after_expiry() -> None:
    contract = ContractLifecycle(
        instrument_id="ABC-FUT",
        contract_rule_version="2025-01",
        listed_from=datetime(2025, 1, 1, tzinfo=UTC),
        expiry_at=datetime(2025, 1, 30, tzinfo=UTC),
    )

    assert contract.tradable_at(datetime(2025, 1, 15, tzinfo=UTC))
    assert not contract.tradable_at(datetime(2025, 1, 30, tzinfo=UTC))


def test_corporate_action_is_explicit_and_point_in_time() -> None:
    event = CorporateActionEvent(
        event_id="split-1",
        instrument_id="ABC",
        effective_at=datetime(2025, 1, 10, tzinfo=UTC),
        event_type="SPLIT",
        factor=Decimal("2"),
        adjustment_method="PRICE_AND_QUANTITY",
    )

    assert not event.applies_at(datetime(2025, 1, 9, tzinfo=UTC))
    assert event.applies_at(datetime(2025, 1, 10, tzinfo=UTC))


def test_lifecycle_requires_timezone_aware_dates() -> None:
    with pytest.raises(ValueError):
        InstrumentLifecycle("ABC", datetime(2025, 1, 1))


def test_contract_lifecycle_requires_valid_temporal_bounds() -> None:
    listed = datetime(2025, 1, 1, tzinfo=UTC)
    expiry = datetime(2025, 1, 30, tzinfo=UTC)

    with pytest.raises(ValueError, match="listed_from must be timezone-aware"):
        ContractLifecycle("ABC-FUT", "2025-01", datetime(2025, 1, 1))

    with pytest.raises(ValueError, match="expiry_at must be after listed_from"):
        ContractLifecycle("ABC-FUT", "2025-01", listed, listed)

    with pytest.raises(ValueError, match="settled_at requires expiry_at"):
        ContractLifecycle(
            "ABC-FUT",
            "2025-01",
            listed,
            settled_at=datetime(2025, 1, 31, tzinfo=UTC),
        )

    with pytest.raises(ValueError, match="settled_at must not precede expiry_at"):
        ContractLifecycle(
            "ABC-FUT",
            "2025-01",
            listed,
            expiry_at=expiry,
            settled_at=datetime(2025, 1, 29, tzinfo=UTC),
        )


def test_contract_lifecycle_requires_timezone_aware_expiry_and_settlement() -> None:
    listed = datetime(2025, 1, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="expiry_at must be timezone-aware"):
        ContractLifecycle("ABC-FUT", "2025-01", listed, datetime(2025, 1, 30))

    with pytest.raises(ValueError, match="settled_at must be timezone-aware"):
        ContractLifecycle(
            "ABC-FUT",
            "2025-01",
            listed,
            expiry_at=datetime(2025, 1, 30, tzinfo=UTC),
            settled_at=datetime(2025, 1, 31),
        )
