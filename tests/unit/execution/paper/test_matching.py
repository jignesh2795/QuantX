"""Boundary contract tests for the deterministic paper order matcher.

``PaperMatcher`` decides whether an order may execute against one observed
``MarketSnapshot``. These tests pin the exact comparison boundaries for every
supported order type so a change in a price comparison cannot silently alter
execution semantics.

A trigger is not a fill: a triggered stop-limit whose limit price is not
reachable still reports ``executable is False``.
"""

from decimal import Decimal

import pytest

from quantx.execution.paper.fills import MarketSnapshot
from quantx.execution.paper.matching import PaperMatcher
from quantx.execution.paper.order_types import PaperOrderSpec, PaperOrderType

TICK = Decimal("0.05")


def _matcher() -> PaperMatcher:
    return PaperMatcher()


def _snapshot(
    bid: str = "99.00",
    ask: str = "100.00",
    last: str = "99.50",
) -> MarketSnapshot:
    return MarketSnapshot(Decimal(bid), Decimal(ask), Decimal(last))


def _market(side: str) -> PaperOrderSpec:
    return PaperOrderSpec(side, PaperOrderType.MARKET, Decimal("2"))


def _limit(side: str, limit: str) -> PaperOrderSpec:
    return PaperOrderSpec(side, PaperOrderType.LIMIT, Decimal("2"), limit_price=Decimal(limit))


def _stop(side: str, stop: str) -> PaperOrderSpec:
    return PaperOrderSpec(side, PaperOrderType.STOP, Decimal("2"), stop_price=Decimal(stop))


def _stop_limit(side: str, limit: str, stop: str) -> PaperOrderSpec:
    return PaperOrderSpec(
        side,
        PaperOrderType.STOP_LIMIT,
        Decimal("2"),
        limit_price=Decimal(limit),
        stop_price=Decimal(stop),
    )


# Market orders execute unconditionally against the touching side.


def test_market_buy_is_executable_at_the_ask() -> None:
    decision = _matcher().evaluate(_market("BUY"), _snapshot())

    assert decision.executable is True
    assert decision.reference_price == Decimal("100.00")
    assert decision.reason == "marketable"


def test_market_sell_is_executable_at_the_bid() -> None:
    decision = _matcher().evaluate(_market("SELL"), _snapshot())

    assert decision.executable is True
    assert decision.reference_price == Decimal("99.00")
    assert decision.reason == "marketable"


# Limit orders: buy crosses when limit >= ask, sell crosses when limit <= bid.


@pytest.mark.parametrize(
    ("limit", "executable"),
    (
        ("100.05", True),  # one tick above the ask
        ("100.00", True),  # exactly at the ask
        ("99.95", False),  # one tick below the ask
    ),
)
def test_limit_buy_boundary_is_inclusive_at_the_ask(limit: str, executable: bool) -> None:
    decision = _matcher().evaluate(_limit("BUY", limit), _snapshot())

    assert decision.executable is executable
    if executable:
        assert decision.reference_price == Decimal("100.00")
        assert decision.reason == "buy limit crosses ask"
    else:
        assert decision.reference_price is None
        assert decision.reason == "limit not marketable"


@pytest.mark.parametrize(
    ("limit", "executable"),
    (
        ("98.95", True),  # one tick below the bid
        ("99.00", True),  # exactly at the bid
        ("99.05", False),  # one tick above the bid
    ),
)
def test_limit_sell_boundary_is_inclusive_at_the_bid(limit: str, executable: bool) -> None:
    decision = _matcher().evaluate(_limit("SELL", limit), _snapshot())

    assert decision.executable is executable
    if executable:
        assert decision.reference_price == Decimal("99.00")
        assert decision.reason == "sell limit crosses bid"
    else:
        assert decision.reference_price is None
        assert decision.reason == "limit not marketable"


# Stops: buy triggers when last >= stop, sell triggers when last <= stop.


@pytest.mark.parametrize(
    ("last", "triggered"),
    (
        ("99.55", True),  # one tick above the stop
        ("99.50", True),  # exactly at the stop
        ("99.45", False),  # one tick below the stop
    ),
)
def test_stop_buy_trigger_boundary_is_inclusive_at_the_stop(last: str, triggered: bool) -> None:
    decision = _matcher().evaluate(_stop("BUY", "99.50"), _snapshot(last=last))

    assert decision.executable is triggered
    if triggered:
        assert decision.reference_price == Decimal("100.00")
        assert decision.reason == "stop triggered"
    else:
        assert decision.reference_price is None
        assert decision.reason == "stop not triggered"


@pytest.mark.parametrize(
    ("last", "triggered"),
    (
        ("99.45", True),  # one tick below the stop
        ("99.50", True),  # exactly at the stop
        ("99.55", False),  # one tick above the stop
    ),
)
def test_stop_sell_trigger_boundary_is_inclusive_at_the_stop(last: str, triggered: bool) -> None:
    decision = _matcher().evaluate(_stop("SELL", "99.50"), _snapshot(last=last))

    assert decision.executable is triggered
    if triggered:
        assert decision.reference_price == Decimal("99.00")
        assert decision.reason == "stop triggered"
    else:
        assert decision.reference_price is None
        assert decision.reason == "stop not triggered"


# Stop-limit: activation and execution are separate conditions.


def test_stop_limit_buy_executes_when_triggered_and_limit_reachable() -> None:
    decision = _matcher().evaluate(_stop_limit("BUY", "100.00", "99.50"), _snapshot())

    assert decision.executable is True
    assert decision.reference_price == Decimal("100.00")
    assert decision.reason == "stop-limit triggered and executable"


def test_stop_limit_sell_executes_when_triggered_and_limit_reachable() -> None:
    decision = _matcher().evaluate(_stop_limit("SELL", "99.00", "99.50"), _snapshot())

    assert decision.executable is True
    assert decision.reference_price == Decimal("99.00")
    assert decision.reason == "stop-limit triggered and executable"


def test_stop_limit_buy_triggered_but_limit_not_reachable_does_not_execute() -> None:
    """A triggered buy stop-limit must not fill when the ask exceeds the limit."""
    decision = _matcher().evaluate(_stop_limit("BUY", "99.95", "99.50"), _snapshot())

    assert decision.executable is False
    assert decision.reference_price is None
    assert decision.reason == "stop-limit triggered but limit not executable"


def test_stop_limit_sell_triggered_but_limit_not_reachable_does_not_execute() -> None:
    """A triggered sell stop-limit must not fill when the bid is below the limit."""
    decision = _matcher().evaluate(_stop_limit("SELL", "99.05", "99.50"), _snapshot())

    assert decision.executable is False
    assert decision.reference_price is None
    assert decision.reason == "stop-limit triggered but limit not executable"


def test_stop_limit_untriggered_reports_not_triggered_even_when_limit_reachable() -> None:
    """An untriggered stop-limit stays unfilled regardless of a permissive limit."""
    decision = _matcher().evaluate(
        _stop_limit("BUY", "100.05", "99.50"),
        _snapshot(last="99.45"),
    )

    assert decision.executable is False
    assert decision.reference_price is None
    assert decision.reason == "stop not triggered"


def test_stop_limit_sell_untriggered_reports_not_triggered() -> None:
    decision = _matcher().evaluate(
        _stop_limit("SELL", "98.95", "99.50"),
        _snapshot(last="99.55"),
    )

    assert decision.executable is False
    assert decision.reference_price is None
    assert decision.reason == "stop not triggered"


# Fail-closed construction constraints.


@pytest.mark.parametrize("side", ("BUY", "buy", "Sell"))
def test_side_is_case_insensitive_for_matching(side: str) -> None:
    decision = _matcher().evaluate(_market(side), _snapshot())

    assert decision.executable is True


def test_invalid_side_is_rejected_at_order_construction() -> None:
    with pytest.raises(ValueError, match="side must be BUY or SELL"):
        PaperOrderSpec("LONG", PaperOrderType.MARKET, Decimal("2"))


@pytest.mark.parametrize("quantity", ("0", "-1"))
def test_non_positive_quantity_is_rejected_at_order_construction(quantity: str) -> None:
    with pytest.raises(ValueError, match="quantity must be positive"):
        PaperOrderSpec("BUY", PaperOrderType.MARKET, Decimal(quantity))


def test_limit_without_limit_price_is_rejected_at_order_construction() -> None:
    with pytest.raises(ValueError, match="limit_price is required"):
        PaperOrderSpec("BUY", PaperOrderType.LIMIT, Decimal("2"))


def test_stop_without_stop_price_is_rejected_at_order_construction() -> None:
    with pytest.raises(ValueError, match="stop_price is required"):
        PaperOrderSpec("BUY", PaperOrderType.STOP, Decimal("2"))


def test_stop_limit_without_stop_price_is_rejected_at_order_construction() -> None:
    with pytest.raises(ValueError, match="stop_price is required"):
        PaperOrderSpec(
            "BUY", PaperOrderType.STOP_LIMIT, Decimal("2"), limit_price=Decimal("100.00")
        )


def test_crossed_market_snapshot_is_rejected() -> None:
    with pytest.raises(ValueError, match="bid cannot exceed ask"):
        MarketSnapshot(Decimal("101.00"), Decimal("100.00"), Decimal("100.00"))


def test_non_positive_market_price_is_rejected() -> None:
    with pytest.raises(ValueError, match="market prices must be positive"):
        MarketSnapshot(Decimal("99.00"), Decimal("0"), Decimal("99.50"))
