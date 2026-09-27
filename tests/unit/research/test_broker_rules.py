from datetime import UTC, datetime
from decimal import Decimal

from quantx.research.broker_rules import (
    RuleStatus,
    StaticVenueRuleProvider,
    VenueRuleSnapshot,
    evaluate_order_constraints,
)


def test_resolves_point_in_time_rule() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 7, 1, tzinfo=UTC)
    provider = StaticVenueRuleProvider(
        (
            VenueRuleSnapshot("TEST", "v1", t0, t1, minimum_order_value=Decimal("100")),
            VenueRuleSnapshot("TEST", "v2", t1, minimum_order_value=Decimal("250")),
        )
    )
    assert provider.resolve("TEST", datetime(2026, 6, 1, tzinfo=UTC)).version == "v1"
    assert provider.resolve("TEST", datetime(2026, 8, 1, tzinfo=UTC)).version == "v2"


def test_unknown_rule_does_not_get_invented() -> None:
    provider = StaticVenueRuleProvider(())
    assert provider.resolve("TEST", datetime(2026, 8, 1, tzinfo=UTC)) is None


def test_explicit_constraints_are_evaluated() -> None:
    rule = VenueRuleSnapshot(
        "TEST",
        "v1",
        datetime(2026, 1, 1, tzinfo=UTC),
        minimum_order_value=Decimal("100"),
        minimum_quantity=Decimal("2"),
    )
    status, issues = evaluate_order_constraints(
        rule, order_value=Decimal("90"), quantity=Decimal("1")
    )
    assert status is RuleStatus.INVALID
    assert len(issues) == 2


def test_overlapping_rules_are_rejected() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 6, 1, tzinfo=UTC)
    t2 = datetime(2026, 7, 1, tzinfo=UTC)

    import pytest

    with pytest.raises(ValueError, match="^overlapping venue rules for TEST$"):
        StaticVenueRuleProvider(
            (
                VenueRuleSnapshot("TEST", "v1", t0, t2),
                VenueRuleSnapshot("TEST", "v2", t1),
            )
        )
