from datetime import datetime, timezone
from decimal import Decimal

from quantx.research.venue_adapters import StaticVenueRuleProvider, VenueRuleContext


def test_resolves_rule_effective_at_timestamp():
    older = VenueRuleContext(
        venue="TEST",
        effective_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        effective_to=datetime(2025, 6, 1, tzinfo=timezone.utc),
        rule_version="v1",
        minimum_order_value=Decimal("10"),
    )
    newer = VenueRuleContext(
        venue="TEST",
        effective_from=datetime(2025, 6, 1, tzinfo=timezone.utc),
        effective_to=None,
        rule_version="v2",
        minimum_order_value=Decimal("20"),
    )
    provider = StaticVenueRuleProvider((older, newer))

    result = provider.resolve("TEST", datetime(2025, 7, 1, tzinfo=timezone.utc))

    assert result is newer
    assert result.rule_version == "v2"


def test_unknown_historical_rule_returns_none():
    provider = StaticVenueRuleProvider(())
    assert provider.resolve("TEST", datetime(2025, 7, 1, tzinfo=timezone.utc)) is None
