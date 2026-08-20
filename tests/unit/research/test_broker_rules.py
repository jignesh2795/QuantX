from datetime import datetime, timezone
from decimal import Decimal

from quantx.research.broker_rules import (
    RuleStatus,
    StaticVenueRuleProvider,
    VenueRuleSnapshot,
    evaluate_order_constraints,
)


def test_resolves_point_in_time_rule() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    t1 = datetime(2026, 7, 1, tzinfo=timezone.utc)
    provider = StaticVenueRuleProvider(
        (
            VenueRuleSnapshot("TEST", "v1", t0, t1, minimum_order_value=Decimal("100")),
            VenueRuleSnapshot("TEST", "v2", t1, minimum_order_value=Decimal("250")),
        )
    )
    assert provider.resolve("TEST", datetime(2026, 6, 1, tzinfo=timezone.utc)).version == "v1"
    assert provider.resolve("TEST", datetime(2026, 8, 1, tzinfo=timezone.utc)).version == "v2"


def test_unknown_rule_does_not_get_invented() -> None:
    provider = StaticVenueRuleProvider(())
    assert provider.resolve("TEST", datetime(2026, 8, 1, tzinfo=timezone.utc)) is None


def test_explicit_constraints_are_evaluated() -> None:
    rule = VenueRuleSnapshot("TEST", "v1", datetime(2026, 1, 1, tzinfo=timezone.utc), minimum_order_value=Decimal("100"), minimum_quantity=Decimal("2"))
    status, issues = evaluate_order_constraints(rule, order_value=Decimal("90"), quantity=Decimal("1"))
    assert status is RuleStatus.INVALID
    assert len(issues) == 2
