"""QX-04: CLOSE/AUTO resolution against authoritative position evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantx.domain.enums import OrderSide, OrderType, PositionEffect
from quantx.domain.orders import Order
from quantx.domain.value_objects import InstrumentId
from quantx.execution.position_effect import PositionEvidence, resolve_position_effect

NOW = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
MAX_AGE = timedelta(minutes=5)
INSTRUMENT = InstrumentId("NSE", "TCS")


def _order(
    side: OrderSide = OrderSide.SELL,
    quantity: str = "5",
    effect: PositionEffect | None = PositionEffect.CLOSE,
) -> Order:
    return Order(
        instrument=InstrumentId("NSE", "TCS"),
        side=side,
        order_type=OrderType.MARKET,
        quantity=Decimal(quantity),
        position_effect=effect,
    )


def _evidence(
    quantity: str,
    *,
    matched: bool = True,
    observed_at: datetime = NOW,
    cut: datetime = NOW,
    instrument: InstrumentId = INSTRUMENT,
) -> PositionEvidence:
    return PositionEvidence(
        instrument=instrument,
        quantity=Decimal(quantity),
        observed_at=observed_at,
        evidence_cut=cut,
        matched=matched,
    )


def test_open_and_absent_need_no_position_evidence() -> None:
    opened = resolve_position_effect(
        _order(effect=PositionEffect.OPEN), evidence=None, max_evidence_age=MAX_AGE
    )
    absent = resolve_position_effect(_order(effect=None), evidence=None, max_evidence_age=MAX_AGE)

    assert opened.effective is PositionEffect.OPEN
    assert opened.evidence_cut is None
    assert absent.effective is None
    assert absent.evidence_cut is None


def test_close_sell_reduces_matched_long_position() -> None:
    resolution = resolve_position_effect(
        _order(side=OrderSide.SELL, quantity="5"),
        evidence=_evidence("8"),
        max_evidence_age=MAX_AGE,
    )

    assert resolution.requested is PositionEffect.CLOSE
    assert resolution.effective is PositionEffect.CLOSE
    assert resolution.evidence_cut == NOW


def test_close_buy_reduces_matched_short_position() -> None:
    resolution = resolve_position_effect(
        _order(side=OrderSide.BUY, quantity="3"),
        evidence=_evidence("-3"),
        max_evidence_age=MAX_AGE,
    )

    assert resolution.effective is PositionEffect.CLOSE


def test_close_same_side_position_is_rejected() -> None:
    with pytest.raises(ValueError, match="must reduce an existing opposite position"):
        resolve_position_effect(
            _order(side=OrderSide.SELL, quantity="1"),
            evidence=_evidence("-4"),
            max_evidence_age=MAX_AGE,
        )


def test_close_flat_position_is_rejected() -> None:
    with pytest.raises(ValueError, match="existing opposite position"):
        resolve_position_effect(
            _order(side=OrderSide.SELL, quantity="1"),
            evidence=_evidence("0"),
            max_evidence_age=MAX_AGE,
        )


def test_close_cannot_cross_through_zero() -> None:
    with pytest.raises(ValueError, match="cross through zero"):
        resolve_position_effect(
            _order(side=OrderSide.SELL, quantity="6"),
            evidence=_evidence("5"),
            max_evidence_age=MAX_AGE,
        )


def test_close_requires_evidence() -> None:
    with pytest.raises(ValueError, match="requires authoritative position evidence"):
        resolve_position_effect(_order(), evidence=None, max_evidence_age=MAX_AGE)


def test_close_rejects_unmatched_evidence() -> None:
    with pytest.raises(ValueError, match="not an authoritative reconciled observation"):
        resolve_position_effect(
            _order(),
            evidence=_evidence("5", matched=False),
            max_evidence_age=MAX_AGE,
        )


def test_close_rejects_stale_evidence() -> None:
    with pytest.raises(ValueError, match="stale"):
        resolve_position_effect(
            _order(),
            evidence=_evidence("5", observed_at=NOW - timedelta(minutes=6)),
            max_evidence_age=MAX_AGE,
        )


def test_close_rejects_evidence_from_another_instrument() -> None:
    with pytest.raises(ValueError, match="does not match the order instrument"):
        resolve_position_effect(
            _order(),
            evidence=_evidence("5", instrument=InstrumentId("NSE", "INFY")),
            max_evidence_age=MAX_AGE,
        )


def test_auto_resolves_reducing_side_to_close_within_position() -> None:
    resolution = resolve_position_effect(
        _order(side=OrderSide.SELL, quantity="5", effect=PositionEffect.AUTO),
        evidence=_evidence("8"),
        max_evidence_age=MAX_AGE,
    )

    assert resolution.requested is PositionEffect.AUTO
    assert resolution.effective is PositionEffect.CLOSE
    assert resolution.evidence_cut == NOW


def test_auto_resolves_increasing_side_to_open() -> None:
    resolution = resolve_position_effect(
        _order(side=OrderSide.BUY, quantity="2", effect=PositionEffect.AUTO),
        evidence=_evidence("8"),
        max_evidence_age=MAX_AGE,
    )

    assert resolution.effective is PositionEffect.OPEN
    assert resolution.evidence_cut == NOW


def test_auto_resolves_flat_position_to_open() -> None:
    resolution = resolve_position_effect(
        _order(side=OrderSide.SELL, quantity="2", effect=PositionEffect.AUTO),
        evidence=_evidence("0"),
        max_evidence_age=MAX_AGE,
    )

    assert resolution.effective is PositionEffect.OPEN


def test_auto_rejects_oversized_reducing_order_instead_of_reversing() -> None:
    with pytest.raises(ValueError, match="cross through zero"):
        resolve_position_effect(
            _order(side=OrderSide.SELL, quantity="9", effect=PositionEffect.AUTO),
            evidence=_evidence("8"),
            max_evidence_age=MAX_AGE,
        )


def test_auto_requires_evidence() -> None:
    with pytest.raises(ValueError, match="AUTO position effect requires"):
        resolve_position_effect(
            _order(effect=PositionEffect.AUTO), evidence=None, max_evidence_age=MAX_AGE
        )


def test_resolution_policy_is_required_and_validated() -> None:
    with pytest.raises(ValueError, match="max_evidence_age"):
        resolve_position_effect(
            _order(), evidence=_evidence("5"), max_evidence_age=timedelta(seconds=-1)
        )


def test_evidence_rejects_non_decimal_and_naive_values() -> None:
    with pytest.raises(ValueError, match="finite Decimal"):
        PositionEvidence(
            instrument=InstrumentId("NSE", "TCS"),
            quantity=5.0,  # type: ignore[arg-type]
            observed_at=NOW,
            evidence_cut=NOW,
            matched=True,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        PositionEvidence(
            instrument=InstrumentId("NSE", "TCS"),
            quantity=Decimal("5"),
            observed_at=datetime(2026, 1, 5, 10, 0),
            evidence_cut=NOW,
            matched=True,
        )


def test_evidence_cannot_be_observed_after_the_cut() -> None:
    with pytest.raises(ValueError, match="observed after the evidence cut"):
        PositionEvidence(
            instrument=InstrumentId("NSE", "TCS"),
            quantity=Decimal("5"),
            observed_at=NOW + timedelta(seconds=1),
            evidence_cut=NOW,
            matched=True,
        )
