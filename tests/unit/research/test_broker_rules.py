from datetime import UTC, datetime
from decimal import Decimal

import pytest

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


@pytest.mark.parametrize(
    ("venue", "version"),
    [("", "v1"), ("TEST", "")],
)
def test_rule_identity_must_not_be_empty(venue: str, version: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        VenueRuleSnapshot(venue, version, datetime(2026, 1, 1, tzinfo=UTC))


@pytest.mark.parametrize(
    ("field", "value"),
    [("minimum_order_value", Decimal("0")), ("minimum_quantity", Decimal("-1"))],
)
def test_rule_minimums_must_be_positive(field: str, value: Decimal) -> None:
    kwargs = {field: value}
    with pytest.raises(ValueError, match="must be positive"):
        VenueRuleSnapshot(
            "TEST",
            "v1",
            datetime(2026, 1, 1, tzinfo=UTC),
            **kwargs,
        )


@pytest.mark.parametrize(
    ("order_value", "quantity", "message"),
    [
        (Decimal("0"), Decimal("1"), "order value must be positive"),
        (Decimal("100"), Decimal("0"), "quantity must be positive"),
        (Decimal("-1"), Decimal("-1"), "order value must be positive"),
    ],
)
def test_non_positive_orders_are_invalid(
    order_value: Decimal,
    quantity: Decimal,
    message: str,
) -> None:
    rule = VenueRuleSnapshot("TEST", "v1", datetime(2026, 1, 1, tzinfo=UTC))
    status, issues = evaluate_order_constraints(
        rule,
        order_value=order_value,
        quantity=quantity,
    )
    assert status is RuleStatus.INVALID
    assert message in issues


def test_overlapping_rules_are_rejected() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 6, 1, tzinfo=UTC)
    t2 = datetime(2026, 7, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="^overlapping venue rules for TEST$"):
        StaticVenueRuleProvider(
            (
                VenueRuleSnapshot("TEST", "v1", t0, t2),
                VenueRuleSnapshot("TEST", "v2", t1),
            )
        )
