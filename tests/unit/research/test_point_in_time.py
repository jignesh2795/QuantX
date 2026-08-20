from datetime import datetime, time, timezone
from decimal import Decimal

from quantx.research.calendar import FixedDailySessionCalendar, SessionStatus
from quantx.research.market_rules import (
    PointInTimeInstrumentRegistry,
    TradabilityStatus,
    VersionedInstrumentRule,
)
from quantx.research.point_in_time import PointInTimeContextResolver


def make_registry(status=TradabilityStatus.TRADABLE):
    return PointInTimeInstrumentRegistry(
        (
            VersionedInstrumentRule(
                instrument_id="TEST",
                effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                effective_to=None,
                tick_size=Decimal("0.05"),
                lot_size=Decimal("1"),
                multiplier=Decimal("1"),
                currency="INR",
                status=status,
                rule_version="v1",
            ),
        )
    )


def test_market_open_and_instrument_tradable_is_executable():
    calendar = FixedDailySessionCalendar(
        timezone="UTC",
        open_time=time(9),
        close_time=time(16),
    )
    resolver = PointInTimeContextResolver(
        calendar=calendar,
        instrument_registry=make_registry(),
    )
    context = resolver.resolve("TEST", datetime(2026, 2, 1, 10, tzinfo=timezone.utc))
    assert context.session.status is SessionStatus.OPEN
    assert context.executable is True
    assert context.execution_block_reason is None


def test_closed_market_is_not_executable_even_when_instrument_is_tradable():
    calendar = FixedDailySessionCalendar(
        timezone="UTC",
        open_time=time(9),
        close_time=time(16),
    )
    resolver = PointInTimeContextResolver(
        calendar=calendar,
        instrument_registry=make_registry(),
    )
    context = resolver.resolve("TEST", datetime(2026, 2, 1, 20, tzinfo=timezone.utc))
    assert context.executable is False
    assert "market session" in context.execution_block_reason


def test_suspended_instrument_is_not_executable_during_open_session():
    calendar = FixedDailySessionCalendar(
        timezone="UTC",
        open_time=time(9),
        close_time=time(16),
    )
    resolver = PointInTimeContextResolver(
        calendar=calendar,
        instrument_registry=make_registry(TradabilityStatus.SUSPENDED),
    )
    context = resolver.resolve("TEST", datetime(2026, 2, 1, 10, tzinfo=timezone.utc))
    assert context.session.status is SessionStatus.OPEN
    assert context.executable is False
    assert "instrument status" in context.execution_block_reason
