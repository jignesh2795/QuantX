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
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Order
from quantx.domain.position_effect import AbsentPositionEffectResolution, PositionEvidence
from quantx.domain.product_selection import ProductSelectionResolution
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId, ProductCode

NOW = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
PACK = {"market_pack_id": "india", "rule_version": "india-products-v1"}
MAX_AGE = timedelta(minutes=5)
MARKET = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def _product_resolution(
    product: ProductCode,
    *,
    market_pack_id: str = PACK["market_pack_id"],
    rule_version: str = PACK["rule_version"],
) -> ProductSelectionResolution:
    return ProductSelectionResolution(
        market=MARKET,
        product=product,
        market_pack_id=market_pack_id,
        rule_version=rule_version,
    )


def _absent_effect_resolution(
    *,
    product: ProductCode | None = None,
    effective: PositionEffect | None = None,
    not_applicable: bool = True,
    market_pack_id: str = PACK["market_pack_id"],
    rule_version: str = PACK["rule_version"],
) -> AbsentPositionEffectResolution:
    return AbsentPositionEffectResolution(
        market=MARKET,
        product=product,
        rule_product=product,
        market_pack_id=market_pack_id,
        rule_version=rule_version,
        effective=effective,
        not_applicable=not_applicable,
    )


def _context(
    mode: ExecutionMode,
    connection_id=None,
    *,
    market_pack_id: str | None = None,
    rule_version: str | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=connection_id,
        execution_mode=mode,
        market_pack_id=market_pack_id,
        rule_version=rule_version,
    )


def test_order_is_derived_from_intent() -> None:
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        execution_context=_context(ExecutionMode.PAPER),
    )
    order = build_order_from_intent(intent)
    assert isinstance(order, Order)
    assert order.instrument == intent.instrument
    assert order.quantity == intent.quantity


def test_live_execution_requires_broker_connection() -> None:
    order = Order(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
    )
    approved = RiskResult(RiskDecision.APPROVE, "approved")
    with pytest.raises(ValueError, match="broker connection"):
        ApprovedExecutionRequest(order, _context(ExecutionMode.LIVE), approved)


def test_build_order_from_intent_preserves_product_and_position_effect() -> None:
    context = _context(ExecutionMode.PAPER, **PACK)
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        product=ProductCode("MIS"),
        position_effect=PositionEffect.OPEN,
        execution_context=context,
    )
    order = build_order_from_intent(intent)
    assert order.product == ProductCode("MIS")
    assert order.position_effect is PositionEffect.OPEN


def _order(
    *,
    side: OrderSide = OrderSide.BUY,
    quantity: str = "1",
    product: ProductCode | None = None,
    position_effect: PositionEffect | None = None,
) -> Order:
    return Order(
        instrument=InstrumentId("NSE", "TCS"),
        side=side,
        order_type=OrderType.MARKET,
        quantity=Decimal(quantity),
        product=product,
        position_effect=position_effect,
    )


def _evidence(
    quantity: str,
    *,
    matched: bool = True,
    observed_at: datetime = NOW,
    cut: datetime = NOW,
) -> PositionEvidence:
    return PositionEvidence(
        instrument=InstrumentId("NSE", "TCS"),
        quantity=Decimal(quantity),
        observed_at=observed_at,
        evidence_cut=cut,
        matched=matched,
    )


def _paper_request(
    order: Order,
    *,
    product: ProductCode | None = None,
    position_effect: PositionEffect | None = None,
    effective_position_effect: PositionEffect | None = None,
    position_evidence_cut: datetime | None = None,
    position_evidence: PositionEvidence | None = None,
    position_evidence_max_age: timedelta | None = MAX_AGE,
    position_effect_approval_instant: datetime | None = NOW,
    market_pack_id: str | None = PACK["market_pack_id"],
    rule_version: str | None = PACK["rule_version"],
    product_resolution: ProductSelectionResolution | None = None,
    position_effect_policy_resolution: AbsentPositionEffectResolution | None = None,
) -> ApprovedExecutionRequest:
    requested_effect = order.position_effect if position_effect is None else position_effect
    resolved_product = order.product if product is None else product
    if requested_effect in {PositionEffect.CLOSE, PositionEffect.AUTO}:
        max_age = position_evidence_max_age
        instant = position_effect_approval_instant
    else:
        max_age = None
        instant = None
    if resolved_product is not None and product_resolution is None:
        product_resolution = _product_resolution(resolved_product)
    if requested_effect is None and position_effect_policy_resolution is None:
        proof_effective = (
            effective_position_effect if effective_position_effect is PositionEffect.OPEN else None
        )
        position_effect_policy_resolution = _absent_effect_resolution(
            product=resolved_product,
            effective=proof_effective,
            not_applicable=proof_effective is None,
        )
    return ApprovedExecutionRequest(
        order=order,
        execution_context=_context(
            ExecutionMode.PAPER,
            market_pack_id=market_pack_id,
            rule_version=rule_version,
        ),
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        product=resolved_product,
        position_effect=requested_effect,
        effective_position_effect=effective_position_effect,
        position_evidence_cut=position_evidence_cut,
        position_evidence=position_evidence,
        position_evidence_max_age=max_age,
        position_effect_approval_instant=instant,
        product_resolution=product_resolution,
        position_effect_policy_resolution=position_effect_policy_resolution,
    )


def test_explicit_product_requires_market_pack_identity() -> None:
    order = _order(product=ProductCode("CNC"))
    with pytest.raises(ValueError, match="requires a market-pack id"):
        _paper_request(order, market_pack_id=None, rule_version=None)
    with pytest.raises(ValueError, match="requires a market-pack rule version"):
        _paper_request(order, market_pack_id="india-equity", rule_version=None)


def test_auto_position_effect_requires_resolved_effective_effect() -> None:
    order = _order(position_effect=PositionEffect.AUTO)
    with pytest.raises(ValueError, match="AUTO position effect requires"):
        _paper_request(
            order,
            position_effect=PositionEffect.AUTO,
            position_evidence_cut=NOW,
        )


def test_auto_position_effect_rejects_unresolved_effective_value() -> None:
    order = _order(position_effect=PositionEffect.AUTO)
    with pytest.raises(ValueError, match="resolved position effect must be OPEN or CLOSE"):
        _paper_request(
            order,
            position_effect=PositionEffect.AUTO,
            effective_position_effect=PositionEffect.AUTO,
            position_evidence_cut=NOW,
        )


def test_auto_requires_the_position_evidence_cut() -> None:
    order = _order(position_effect=PositionEffect.AUTO)
    with pytest.raises(ValueError, match="requires the position evidence cut"):
        _paper_request(
            order,
            position_effect=PositionEffect.AUTO,
            effective_position_effect=PositionEffect.OPEN,
        )


@pytest.mark.parametrize("effective", [PositionEffect.OPEN, PositionEffect.CLOSE])
def test_auto_position_effect_accepts_resolved_open_or_close(
    effective: PositionEffect,
) -> None:
    side = OrderSide.SELL if effective is PositionEffect.CLOSE else OrderSide.BUY
    order = _order(side=side, position_effect=PositionEffect.AUTO)
    evidence = _evidence("10")
    request = _paper_request(
        order,
        position_effect=PositionEffect.AUTO,
        effective_position_effect=effective,
        position_evidence_cut=NOW,
        position_evidence=evidence,
    )
    assert request.position_effect is PositionEffect.AUTO
    assert request.effective_position_effect is effective
    assert request.position_evidence_cut == NOW
    assert request.position_evidence == evidence
    assert request.position_evidence_max_age == MAX_AGE


def test_close_requires_the_position_evidence_cut() -> None:
    order = _order(side=OrderSide.SELL, position_effect=PositionEffect.CLOSE)
    with pytest.raises(ValueError, match="requires the position evidence cut"):
        _paper_request(order, position_effect=PositionEffect.CLOSE)


def test_close_cannot_resolve_to_open() -> None:
    order = _order(side=OrderSide.SELL, position_effect=PositionEffect.CLOSE)
    with pytest.raises(ValueError, match="cannot resolve to OPEN"):
        _paper_request(
            order,
            position_effect=PositionEffect.CLOSE,
            effective_position_effect=PositionEffect.OPEN,
            position_evidence_cut=NOW,
        )


def test_effective_effect_is_only_valid_for_auto_or_close() -> None:
    order = _order(position_effect=PositionEffect.OPEN)
    with pytest.raises(ValueError, match="only valid for AUTO or CLOSE"):
        _paper_request(
            order,
            position_effect=PositionEffect.OPEN,
            effective_position_effect=PositionEffect.OPEN,
            position_evidence_cut=NOW,
        )


def test_position_evidence_cut_must_be_timezone_aware() -> None:
    order = _order(side=OrderSide.SELL, position_effect=PositionEffect.CLOSE)
    naive = datetime(2026, 1, 5, 10, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        _paper_request(
            order,
            position_effect=PositionEffect.CLOSE,
            position_evidence_cut=naive,
            position_evidence=PositionEvidence(
                instrument=InstrumentId("NSE", "TCS"),
                quantity=Decimal("10"),
                observed_at=naive,
                evidence_cut=naive,
                matched=True,
            ),
        )


def test_position_effect_requires_authoritative_evidence() -> None:
    order = _order(side=OrderSide.SELL, position_effect=PositionEffect.CLOSE)
    with pytest.raises(ValueError, match="authoritative position evidence"):
        _paper_request(
            order,
            position_effect=PositionEffect.CLOSE,
            position_evidence_cut=NOW,
        )


def test_position_effect_requires_freshness_policy() -> None:
    order = _order(side=OrderSide.SELL, position_effect=PositionEffect.CLOSE)
    with pytest.raises(ValueError, match="freshness policy"):
        _paper_request(
            order,
            position_effect=PositionEffect.CLOSE,
            position_evidence_cut=NOW,
            position_evidence=_evidence("10"),
            position_evidence_max_age=None,
        )


def test_forged_effective_effect_cannot_disagree_with_resolution() -> None:
    order = _order(side=OrderSide.BUY, position_effect=PositionEffect.AUTO)
    with pytest.raises(ValueError, match="does not match the resolved"):
        _paper_request(
            order,
            position_effect=PositionEffect.AUTO,
            effective_position_effect=PositionEffect.CLOSE,
            position_evidence_cut=NOW,
            position_evidence=_evidence("10"),
        )


def test_forged_evidence_cut_cannot_disagree_with_resolution() -> None:
    order = _order(side=OrderSide.SELL, position_effect=PositionEffect.CLOSE)
    cut = datetime(2026, 1, 5, 10, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="evidence cut does not match"):
        _paper_request(
            order,
            position_effect=PositionEffect.CLOSE,
            effective_position_effect=PositionEffect.CLOSE,
            position_evidence_cut=cut,
            position_evidence=_evidence("10", cut=NOW),
        )


def test_close_cannot_exceed_observed_position() -> None:
    order = _order(side=OrderSide.SELL, quantity="2", position_effect=PositionEffect.CLOSE)
    with pytest.raises(ValueError, match="must not cross through zero"):
        _paper_request(
            order,
            position_effect=PositionEffect.CLOSE,
            effective_position_effect=PositionEffect.CLOSE,
            position_evidence_cut=NOW,
            position_evidence=_evidence("1"),
        )


def test_stale_evidence_is_rejected() -> None:
    order = _order(side=OrderSide.SELL, position_effect=PositionEffect.CLOSE)
    with pytest.raises(ValueError, match="stale"):
        _paper_request(
            order,
            position_effect=PositionEffect.CLOSE,
            effective_position_effect=PositionEffect.CLOSE,
            position_evidence_cut=NOW,
            position_evidence=_evidence("10", observed_at=NOW - timedelta(minutes=10)),
        )


def test_explicit_position_effect_and_product_are_preserved() -> None:
    order = _order(
        side=OrderSide.SELL,
        product=ProductCode("CNC"),
        position_effect=PositionEffect.CLOSE,
    )
    evidence = _evidence("10")
    request = _paper_request(
        order,
        position_effect=PositionEffect.CLOSE,
        effective_position_effect=PositionEffect.CLOSE,
        position_evidence_cut=NOW,
        position_evidence=evidence,
    )
    assert request.product == ProductCode("CNC")
    assert request.position_effect is PositionEffect.CLOSE
    assert request.position_evidence_cut == NOW
    assert request.position_evidence == evidence


def test_request_position_effect_must_match_the_order_contract() -> None:
    order = _order()
    with pytest.raises(ValueError, match="requires the order to carry"):
        _paper_request(order, position_effect=PositionEffect.OPEN)


def test_open_order_cannot_smuggle_position_evidence_through_the_request() -> None:
    order = _order(position_effect=PositionEffect.OPEN)
    with pytest.raises(ValueError, match="only valid for AUTO or CLOSE"):
        _paper_request(
            order,
            position_effect=PositionEffect.OPEN,
            position_evidence=_evidence("5"),
            position_evidence_cut=NOW,
        )


def test_request_product_requires_the_order_to_carry_it() -> None:
    order = _order()
    with pytest.raises(ValueError, match="requires the order to carry the same product"):
        _paper_request(order, product=ProductCode("CNC"))


def test_resolved_product_must_match_the_order_product() -> None:
    order = _order(product=ProductCode("CNC"))
    with pytest.raises(ValueError, match="does not match the order product"):
        _paper_request(order, product=ProductCode("MIS"))


def test_close_requires_the_approval_instant() -> None:
    order = _order(side=OrderSide.SELL, position_effect=PositionEffect.CLOSE)
    with pytest.raises(ValueError, match="requires the approval instant"):
        _paper_request(
            order,
            position_effect=PositionEffect.CLOSE,
            effective_position_effect=PositionEffect.CLOSE,
            position_evidence_cut=NOW,
            position_evidence=_evidence("10"),
            position_effect_approval_instant=None,
        )


def test_approval_instant_must_be_timezone_aware() -> None:
    order = _order(side=OrderSide.SELL, position_effect=PositionEffect.CLOSE)
    naive = datetime(2026, 1, 5, 10, 0)
    with pytest.raises(ValueError, match="approval instant must be timezone-aware"):
        _paper_request(
            order,
            position_effect=PositionEffect.CLOSE,
            effective_position_effect=PositionEffect.CLOSE,
            position_evidence_cut=NOW,
            position_evidence=_evidence("10"),
            position_effect_approval_instant=naive,
        )


def test_evidence_observed_after_the_approval_instant_is_rejected() -> None:
    order = _order(side=OrderSide.SELL, position_effect=PositionEffect.CLOSE)
    future = NOW + timedelta(minutes=1)
    with pytest.raises(ValueError, match="observed after the approval instant"):
        _paper_request(
            order,
            position_effect=PositionEffect.CLOSE,
            effective_position_effect=PositionEffect.CLOSE,
            position_evidence_cut=future,
            position_evidence=_evidence("10", observed_at=future, cut=future),
            position_effect_approval_instant=NOW,
        )


def test_open_request_cannot_carry_an_approval_instant() -> None:
    order = _order(position_effect=PositionEffect.OPEN)
    with pytest.raises(ValueError, match="only valid for AUTO or CLOSE"):
        ApprovedExecutionRequest(
            order=order,
            execution_context=_context(ExecutionMode.PAPER, **PACK),
            risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
            product=order.product,
            position_effect=PositionEffect.OPEN,
            position_effect_approval_instant=NOW,
        )


def test_absent_position_effect_resolved_to_open_requires_pack_identity() -> None:
    order = _order()
    with pytest.raises(ValueError, match="market-pack id does not match"):
        _paper_request(
            order,
            effective_position_effect=PositionEffect.OPEN,
            market_pack_id=None,
            rule_version=None,
        )


def test_absent_position_effect_may_resolve_to_open_with_pack_identity() -> None:
    order = _order()
    request = _paper_request(order, effective_position_effect=PositionEffect.OPEN)
    assert request.position_effect is None
    assert request.effective_position_effect is PositionEffect.OPEN


def test_absent_position_effect_cannot_resolve_to_close() -> None:
    order = _order()
    with pytest.raises(ValueError, match="does not match the resolved effective effect"):
        _paper_request(order, effective_position_effect=PositionEffect.CLOSE)


def test_absent_position_effect_requires_a_validated_policy_resolution() -> None:
    order = _order()
    with pytest.raises(
        ValueError, match="absent position effect requires a validated market-pack policy"
    ):
        ApprovedExecutionRequest(
            order=order,
            execution_context=_context(ExecutionMode.PAPER, **PACK),
            risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        )


def test_resolved_product_requires_a_validated_selection_resolution() -> None:
    order = _order(product=ProductCode("CNC"))
    with pytest.raises(ValueError, match="requires a validated product selection resolution"):
        ApprovedExecutionRequest(
            order=order,
            execution_context=_context(ExecutionMode.PAPER, **PACK),
            risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
            product=ProductCode("CNC"),
            position_effect=PositionEffect.OPEN,
        )


def test_absent_effect_policy_resolution_must_match_the_request_product() -> None:
    order = _order()
    with pytest.raises(ValueError, match="product does not match the resolved product"):
        _paper_request(
            order,
            position_effect_policy_resolution=_absent_effect_resolution(product=ProductCode("CNC")),
        )


def test_product_selection_resolution_must_match_the_resolved_product() -> None:
    order = _order(product=ProductCode("CNC"))
    with pytest.raises(ValueError, match="does not match the resolved product"):
        _paper_request(
            order,
            product_resolution=_product_resolution(ProductCode("MIS")),
        )


def test_product_selection_resolution_must_match_the_context_identity() -> None:
    order = _order(product=ProductCode("CNC"))
    with pytest.raises(ValueError, match="market-pack id does not match"):
        _paper_request(
            order,
            product_resolution=_product_resolution(ProductCode("CNC"), market_pack_id="other-pack"),
        )


def test_absent_effect_policy_resolution_is_only_valid_for_an_absent_effect() -> None:
    order = _order(position_effect=PositionEffect.OPEN)
    with pytest.raises(ValueError, match="only valid for an absent position effect"):
        ApprovedExecutionRequest(
            order=order,
            execution_context=_context(ExecutionMode.PAPER, **PACK),
            risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
            position_effect=PositionEffect.OPEN,
            position_effect_policy_resolution=_absent_effect_resolution(),
        )
