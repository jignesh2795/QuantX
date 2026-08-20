from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quantx.research.market_rules import (
    PointInTimeInstrumentRegistry,
    TradabilityStatus,
    VersionedInstrumentRule,
    resolve_tradability,
)


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 2, 1, tzinfo=timezone.utc)
T2 = datetime(2026, 3, 1, tzinfo=timezone.utc)


def rule(start, end, *, version, status=TradabilityStatus.TRADABLE):
    return VersionedInstrumentRule(
        instrument_id="NIFTY-TEST",
        effective_from=start,
        effective_to=end,
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
        multiplier=Decimal("1"),
        currency="INR",
        status=status,
        rule_version=version,
    )


def test_resolves_historical_version():
    registry = PointInTimeInstrumentRegistry(
        (
            rule(T0, T1, version="v1"),
            rule(T1, None, version="v2"),
        )
    )

    assert registry.resolve("NIFTY-TEST", T0).rule_version == "v1"
    assert registry.resolve("NIFTY-TEST", T2).rule_version == "v2"


def test_overlap_is_rejected():
    registry = PointInTimeInstrumentRegistry((rule(T0, T2, version="v1"),))
    with pytest.raises(ValueError):
        registry.add(rule(T1, None, version="v2"))


def test_missing_point_in_time_rule_is_an_error():
    registry = PointInTimeInstrumentRegistry((rule(T0, T1, version="v1"),))
    with pytest.raises(LookupError):
        registry.resolve("NIFTY-TEST", T2)


def test_tradability_is_explicit():
    registry = PointInTimeInstrumentRegistry(
        (rule(T0, None, version="v1", status=TradabilityStatus.SUSPENDED),)
    )
    result = resolve_tradability(registry, "NIFTY-TEST", T2)
    assert result.status is TradabilityStatus.SUSPENDED
    assert result.tradable is False
