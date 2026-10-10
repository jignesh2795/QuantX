from datetime import UTC, datetime
from decimal import Decimal

from quantx.research.venue_adapters import StaticVenueRuleProvider, VenueRuleContext


def test_resolves_rule_effective_at_timestamp():
    older = VenueRuleContext(
        venue="TEST",
        effective_from=datetime(2025, 1, 1, tzinfo=UTC),
        effective_to=datetime(2025, 6, 1, tzinfo=UTC),
        version="v1",
        minimum_order_value=Decimal("10"),
    )
    newer = VenueRuleContext(
        venue="TEST",
        effective_from=datetime(2025, 6, 1, tzinfo=UTC),
        effective_to=None,
        version="v2",
        minimum_order_value=Decimal("20"),
    )
    provider = StaticVenueRuleProvider((older, newer))

    result = provider.resolve("TEST", datetime(2025, 7, 1, tzinfo=UTC))

    assert result is newer
    assert result.version == "v2"


def test_unknown_historical_rule_returns_none():
    provider = StaticVenueRuleProvider(())
    assert provider.resolve("TEST", datetime(2025, 7, 1, tzinfo=UTC)) is None
