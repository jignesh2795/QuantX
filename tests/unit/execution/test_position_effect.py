"""QX-04: CLOSE/AUTO resolution against authoritative position evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import OrderSide, OrderType, PositionEffect
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.orders import Order
from quantx.domain.position_effect import (
    PositionEffectPolicy,
    PositionEffectPolicyError,
    PositionEffectRule,
    PositionEvidence,
    resolve_absent_position_effect,
    resolve_position_effect,
)
from quantx.domain.value_objects import InstrumentId, ProductCode

NOW = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
MAX_AGE = timedelta(minutes=5)
INSTRUMENT = InstrumentId("NSE", "TCS")
INDIA_EQUITY = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


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


def _context(
    *,
    market: MarketContext = INDIA_EQUITY,
    market_pack_id: str | None = None,
    rule_version: str | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=market,
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
        market_pack_id=market_pack_id,
        rule_version=rule_version,
    )


def _policy(
    *,
    market: MarketContext = INDIA_EQUITY,
    product: ProductCode | None = None,
    default_effect: PositionEffect | None = None,
    not_applicable: bool = False,
    market_pack_id: str = "india-equity",
    rule_version: str = "india-products-v1",
    extra_rules: tuple[PositionEffectRule, ...] = (),
) -> PositionEffectPolicy:
    rule = PositionEffectRule(
        market=market,
        product=product,
        default_effect=default_effect,
        not_applicable=not_applicable,
    )
    return PositionEffectPolicy(
        market_pack_id=market_pack_id,
        rule_version=rule_version,
        rules=(rule, *extra_rules),
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
        approval_instant=NOW,
    )

    assert resolution.requested is PositionEffect.CLOSE
    assert resolution.effective is PositionEffect.CLOSE
    assert resolution.evidence_cut == NOW
    assert resolution.approval_instant == NOW


def test_close_buy_reduces_matched_short_position() -> None:
    resolution = resolve_position_effect(
        _order(side=OrderSide.BUY, quantity="3"),
        evidence=_evidence("-3"),
        max_evidence_age=MAX_AGE,
        approval_instant=NOW,
    )

    assert resolution.effective is PositionEffect.CLOSE


def test_close_same_side_position_is_rejected() -> None:
    with pytest.raises(ValueError, match="must reduce an existing opposite position"):
        resolve_position_effect(
            _order(side=OrderSide.SELL, quantity="1"),
            evidence=_evidence("-4"),
            max_evidence_age=MAX_AGE,
            approval_instant=NOW,
        )


def test_close_flat_position_is_rejected() -> None:
    with pytest.raises(ValueError, match="existing opposite position"):
        resolve_position_effect(
            _order(side=OrderSide.SELL, quantity="1"),
            evidence=_evidence("0"),
            max_evidence_age=MAX_AGE,
            approval_instant=NOW,
        )


def test_close_cannot_cross_through_zero() -> None:
    with pytest.raises(ValueError, match="cross through zero"):
        resolve_position_effect(
            _order(side=OrderSide.SELL, quantity="6"),
            evidence=_evidence("5"),
            max_evidence_age=MAX_AGE,
            approval_instant=NOW,
        )


def test_close_requires_evidence() -> None:
    with pytest.raises(ValueError, match="requires authoritative position evidence"):
        resolve_position_effect(
            _order(), evidence=None, max_evidence_age=MAX_AGE, approval_instant=NOW
        )


def test_close_requires_the_approval_instant() -> None:
    with pytest.raises(ValueError, match="requires the approval instant"):
        resolve_position_effect(_order(), evidence=_evidence("5"), max_evidence_age=MAX_AGE)


def test_approval_instant_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="approval instant must be timezone-aware"):
        resolve_position_effect(
            _order(),
            evidence=_evidence("5"),
            max_evidence_age=MAX_AGE,
            approval_instant=datetime(2026, 1, 5, 10, 0),
        )


def test_close_rejects_unmatched_evidence() -> None:
    with pytest.raises(ValueError, match="not an authoritative reconciled observation"):
        resolve_position_effect(
            _order(),
            evidence=_evidence("5", matched=False),
            max_evidence_age=MAX_AGE,
            approval_instant=NOW,
        )


def test_close_rejects_stale_evidence() -> None:
    with pytest.raises(ValueError, match="stale"):
        resolve_position_effect(
            _order(),
            evidence=_evidence("5", observed_at=NOW - timedelta(minutes=6)),
            max_evidence_age=MAX_AGE,
            approval_instant=NOW,
        )


def test_freshness_is_measured_against_the_supplied_approval_instant() -> None:
    instant = NOW + timedelta(minutes=2)
    resolution = resolve_position_effect(
        _order(),
        evidence=_evidence("5", observed_at=NOW, cut=NOW),
        max_evidence_age=MAX_AGE,
        approval_instant=instant,
    )

    assert resolution.effective is PositionEffect.CLOSE
    assert resolution.approval_instant == instant


def test_evidence_observed_after_the_approval_instant_is_rejected() -> None:
    future = NOW + timedelta(minutes=1)
    with pytest.raises(ValueError, match="observed after the approval instant"):
        resolve_position_effect(
            _order(),
            evidence=_evidence("5", observed_at=future, cut=future),
            max_evidence_age=MAX_AGE,
            approval_instant=NOW,
        )


def test_evidence_cut_after_the_approval_instant_is_rejected() -> None:
    future = NOW + timedelta(minutes=1)
    with pytest.raises(ValueError, match="cut is after the approval instant"):
        resolve_position_effect(
            _order(),
            evidence=_evidence("5", observed_at=NOW, cut=future),
            max_evidence_age=MAX_AGE,
            approval_instant=NOW,
        )


def test_close_rejects_evidence_from_another_instrument() -> None:
    with pytest.raises(ValueError, match="does not match the order instrument"):
        resolve_position_effect(
            _order(),
            evidence=_evidence("5", instrument=InstrumentId("NSE", "INFY")),
            max_evidence_age=MAX_AGE,
            approval_instant=NOW,
        )


def test_auto_resolves_reducing_side_to_close_within_position() -> None:
    resolution = resolve_position_effect(
        _order(side=OrderSide.SELL, quantity="5", effect=PositionEffect.AUTO),
        evidence=_evidence("8"),
        max_evidence_age=MAX_AGE,
        approval_instant=NOW,
    )

    assert resolution.requested is PositionEffect.AUTO
    assert resolution.effective is PositionEffect.CLOSE
    assert resolution.evidence_cut == NOW


def test_auto_resolves_increasing_side_to_open() -> None:
    resolution = resolve_position_effect(
        _order(side=OrderSide.BUY, quantity="2", effect=PositionEffect.AUTO),
        evidence=_evidence("8"),
        max_evidence_age=MAX_AGE,
        approval_instant=NOW,
    )

    assert resolution.effective is PositionEffect.OPEN
    assert resolution.evidence_cut == NOW


def test_auto_resolves_flat_position_to_open() -> None:
    resolution = resolve_position_effect(
        _order(side=OrderSide.SELL, quantity="2", effect=PositionEffect.AUTO),
        evidence=_evidence("0"),
        max_evidence_age=MAX_AGE,
        approval_instant=NOW,
    )

    assert resolution.effective is PositionEffect.OPEN


def test_auto_rejects_oversized_reducing_order_instead_of_reversing() -> None:
    with pytest.raises(ValueError, match="cross through zero"):
        resolve_position_effect(
            _order(side=OrderSide.SELL, quantity="9", effect=PositionEffect.AUTO),
            evidence=_evidence("8"),
            max_evidence_age=MAX_AGE,
            approval_instant=NOW,
        )


def test_auto_requires_evidence() -> None:
    with pytest.raises(ValueError, match="AUTO position effect requires"):
        resolve_position_effect(
            _order(effect=PositionEffect.AUTO),
            evidence=None,
            max_evidence_age=MAX_AGE,
            approval_instant=NOW,
        )


def test_auto_requires_the_approval_instant() -> None:
    with pytest.raises(ValueError, match="requires the approval instant"):
        resolve_position_effect(
            _order(effect=PositionEffect.AUTO),
            evidence=_evidence("5"),
            max_evidence_age=MAX_AGE,
        )


def test_resolution_policy_is_required_and_validated() -> None:
    with pytest.raises(ValueError, match="max_evidence_age"):
        resolve_position_effect(
            _order(),
            evidence=_evidence("5"),
            max_evidence_age=timedelta(seconds=-1),
            approval_instant=NOW,
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


def test_evidence_match_authority_must_be_a_real_boolean() -> None:
    for invalid in ("true", 1, None):
        with pytest.raises(ValueError, match="matched must be boolean"):
            PositionEvidence(
                instrument=INSTRUMENT,
                quantity=Decimal("5"),
                observed_at=NOW,
                evidence_cut=NOW,
                matched=invalid,  # type: ignore[arg-type]
            )


def test_open_rejects_evidence_symmetrically_with_the_request_contract() -> None:
    with pytest.raises(ValueError, match="only valid for AUTO or CLOSE"):
        resolve_position_effect(
            _order(effect=PositionEffect.OPEN),
            evidence=_evidence("5"),
            max_evidence_age=MAX_AGE,
        )


def test_open_rejects_an_approval_instant_symmetrically() -> None:
    with pytest.raises(ValueError, match="only valid for AUTO or CLOSE"):
        resolve_position_effect(
            _order(effect=PositionEffect.OPEN),
            evidence=None,
            max_evidence_age=MAX_AGE,
            approval_instant=NOW,
        )


def test_absent_without_policy_fails_closed() -> None:
    with pytest.raises(PositionEffectPolicyError, match="requires a versioned market-pack"):
        resolve_absent_position_effect(_context(), product=None, policy=None)


def test_absent_not_applicable_binds_identity_and_resolves_to_no_effect() -> None:
    resolution, context = resolve_absent_position_effect(
        _context(),
        product=None,
        policy=_policy(not_applicable=True),
    )

    assert resolution.requested is None
    assert resolution.effective is None
    assert resolution.evidence_cut is None
    assert context.market_pack_id == "india-equity"
    assert context.rule_version == "india-products-v1"


def test_absent_open_default_binds_identity() -> None:
    resolution, context = resolve_absent_position_effect(
        _context(),
        product=None,
        policy=_policy(default_effect=PositionEffect.OPEN),
    )

    assert resolution.effective is PositionEffect.OPEN
    assert context.market_pack_id == "india-equity"


def test_absent_policy_without_matching_market_fails_closed() -> None:
    other_market = MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN")
    with pytest.raises(PositionEffectPolicyError, match="no versioned position-effect rule"):
        resolve_absent_position_effect(
            _context(),
            product=None,
            policy=_policy(market=other_market, not_applicable=True),
        )


def test_absent_policy_conflicting_context_identity_fails_closed() -> None:
    with pytest.raises(PositionEffectPolicyError, match="market-pack id conflicts"):
        resolve_absent_position_effect(
            _context(market_pack_id="other-pack"),
            product=None,
            policy=_policy(not_applicable=True),
        )
    with pytest.raises(PositionEffectPolicyError, match="rule version conflicts"):
        resolve_absent_position_effect(
            _context(rule_version="other-version"),
            product=None,
            policy=_policy(not_applicable=True),
        )


def test_absent_product_scoped_rule_wins_over_market_wide_rule() -> None:
    product_rule = PositionEffectRule(
        market=INDIA_EQUITY,
        product=ProductCode("NRML"),
        default_effect=PositionEffect.OPEN,
    )
    resolution, _ = resolve_absent_position_effect(
        _context(),
        product=ProductCode("NRML"),
        policy=_policy(not_applicable=True, extra_rules=(product_rule,)),
    )

    assert resolution.effective is PositionEffect.OPEN


def test_position_effect_rule_requires_exactly_one_declaration() -> None:
    with pytest.raises(ValueError, match="requires a default effect or a not-applicable"):
        PositionEffectRule(market=INDIA_EQUITY)
    with pytest.raises(ValueError, match="either a default effect or not_applicable"):
        PositionEffectRule(
            market=INDIA_EQUITY,
            default_effect=PositionEffect.OPEN,
            not_applicable=True,
        )


def test_position_effect_rule_default_may_only_be_open() -> None:
    with pytest.raises(ValueError, match="may only default to OPEN"):
        PositionEffectRule(market=INDIA_EQUITY, default_effect=PositionEffect.CLOSE)
