"""Focused tests for canonical request fingerprinting."""

from datetime import UTC, datetime, timedelta, timezone
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
from quantx.domain.position_effect import AbsentPositionEffectResolution, PositionEvidence
from quantx.domain.product_selection import ProductSelectionResolution
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId, ProductCode
from quantx.execution.idempotency.fingerprint import (
    _canonical_datetime,
    _canonical_decimal,
    fingerprint_payload,
    request_fingerprint,
)

NOW = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
MAX_AGE = timedelta(minutes=5)
MARKET = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def _product_resolution(
    product: ProductCode,
    *,
    market_pack_id: str = "india-equity",
    rule_version: str = "v1",
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
    market_pack_id: str = "india-equity",
    rule_version: str = "v1",
) -> AbsentPositionEffectResolution:
    return AbsentPositionEffectResolution(
        market=MARKET,
        product=product,
        rule_product=product,
        market_pack_id=market_pack_id,
        rule_version=rule_version,
        effective=effective,
        not_applicable=effective is None,
    )


def _evidence(quantity: str = "0", *, cut: datetime = NOW) -> PositionEvidence:
    return PositionEvidence(
        instrument=InstrumentId("NSE", "TCS"),
        quantity=Decimal(quantity),
        observed_at=NOW - timedelta(minutes=1),
        evidence_cut=cut,
        matched=True,
    )


def _request(
    *,
    quantity: Decimal = Decimal("10"),
    order_type: OrderType = OrderType.MARKET,
    limit_price: Decimal | None = None,
    stop_price: Decimal | None = None,
    side: OrderSide = OrderSide.BUY,
    product: ProductCode | None = None,
    position_effect: PositionEffect | None = None,
    effective_position_effect: PositionEffect | None = None,
    position_evidence_cut: datetime | None = None,
    position_evidence: PositionEvidence | None = None,
    position_effect_approval_instant: datetime | None = NOW,
    market_pack_id: str | None = "test-pack",
    rule_version: str | None = "test-v1",
    product_resolution: ProductSelectionResolution | None = None,
    position_effect_policy_resolution: AbsentPositionEffectResolution | None = None,
) -> ApprovedExecutionRequest:
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=None,
        execution_mode=ExecutionMode.PAPER,
        market_pack_id=market_pack_id,
        rule_version=rule_version,
    )
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=side,
        quantity=quantity,
        order_type=order_type,
        limit_price=limit_price,
        stop_price=stop_price,
        product=product,
        position_effect=position_effect,
        execution_context=context,
    )
    order = build_order_from_intent(intent)
    instant = (
        position_effect_approval_instant
        if position_effect in {PositionEffect.CLOSE, PositionEffect.AUTO}
        else None
    )
    assert market_pack_id is not None
    assert rule_version is not None
    if product is not None and product_resolution is None:
        product_resolution = _product_resolution(
            product,
            market_pack_id=market_pack_id,
            rule_version=rule_version,
        )
    if position_effect is None and position_effect_policy_resolution is None:
        proof_effective = (
            effective_position_effect if effective_position_effect is PositionEffect.OPEN else None
        )
        position_effect_policy_resolution = _absent_effect_resolution(
            product=product,
            effective=proof_effective,
            market_pack_id=market_pack_id,
            rule_version=rule_version,
        )
    return ApprovedExecutionRequest(
        order,
        context,
        RiskResult(RiskDecision.APPROVE, "approved"),
        None,
        product=product,
        position_effect=position_effect,
        effective_position_effect=effective_position_effect,
        position_evidence_cut=position_evidence_cut,
        position_evidence=position_evidence,
        position_evidence_max_age=MAX_AGE if position_evidence is not None else None,
        position_effect_approval_instant=instant,
        product_resolution=product_resolution,
        position_effect_policy_resolution=position_effect_policy_resolution,
    )


def test_equivalent_quantities_share_fingerprint() -> None:
    first = request_fingerprint(_request(quantity=Decimal("10")))
    second = request_fingerprint(_request(quantity=Decimal("10.0")))
    third = request_fingerprint(_request(quantity=Decimal("10.00")))
    assert first == second == third


def test_different_quantities_have_different_fingerprints() -> None:
    assert request_fingerprint(_request(quantity=Decimal("10"))) != request_fingerprint(
        _request(quantity=Decimal("11"))
    )


def test_equivalent_limit_prices_share_fingerprint() -> None:
    first = request_fingerprint(_request(order_type=OrderType.LIMIT, limit_price=Decimal("100")))
    second = request_fingerprint(_request(order_type=OrderType.LIMIT, limit_price=Decimal("100.0")))
    assert first == second


def test_equivalent_stop_prices_share_fingerprint() -> None:
    first = request_fingerprint(_request(order_type=OrderType.STOP, stop_price=Decimal("99.5")))
    second = request_fingerprint(_request(order_type=OrderType.STOP, stop_price=Decimal("99.50")))
    assert first == second


def test_non_finite_decimals_are_deterministic() -> None:
    assert _canonical_decimal(Decimal("NaN")) == _canonical_decimal(Decimal("NaN"))
    assert _canonical_decimal(Decimal("Infinity")) == _canonical_decimal(Decimal("Infinity"))
    assert _canonical_decimal(Decimal("-Infinity")) == _canonical_decimal(Decimal("-Infinity"))


def test_fingerprint_is_stable() -> None:
    assert request_fingerprint(_request()) == request_fingerprint(_request())


def test_identity_fields_are_excluded_from_fingerprint() -> None:
    first_request = _request()
    second_request = _request()
    assert first_request.order.client_order_id != second_request.order.client_order_id
    assert request_fingerprint(first_request) == request_fingerprint(second_request)


def _product_request(product: str) -> ApprovedExecutionRequest:
    return _request(product=ProductCode(product), market_pack_id="india-equity", rule_version="v1")


def test_different_products_have_different_fingerprints() -> None:
    assert request_fingerprint(_product_request("CNC")) != request_fingerprint(
        _product_request("MIS")
    )


def test_same_product_has_stable_fingerprint() -> None:
    assert request_fingerprint(_product_request("CNC")) == request_fingerprint(
        _product_request("CNC")
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (None, PositionEffect.OPEN),
        (PositionEffect.OPEN, PositionEffect.CLOSE),
        (PositionEffect.OPEN, PositionEffect.AUTO),
    ],
)
def test_different_requested_effects_have_different_fingerprints(
    first: PositionEffect | None,
    second: PositionEffect | None,
) -> None:
    def effect_request(effect: PositionEffect | None) -> ApprovedExecutionRequest:
        if effect is PositionEffect.CLOSE:
            return _request(
                side=OrderSide.SELL,
                position_effect=effect,
                effective_position_effect=PositionEffect.CLOSE,
                position_evidence_cut=NOW,
                position_evidence=_evidence("10"),
            )
        if effect is PositionEffect.AUTO:
            return _request(
                position_effect=effect,
                effective_position_effect=PositionEffect.OPEN,
                position_evidence_cut=NOW,
                position_evidence=_evidence("0"),
            )
        return _request(position_effect=effect)

    first_request = effect_request(first)
    second_request = effect_request(second)
    assert request_fingerprint(first_request) != request_fingerprint(second_request)


def test_different_resolved_auto_effects_have_different_fingerprints() -> None:
    open_request = _request(
        position_effect=PositionEffect.AUTO,
        effective_position_effect=PositionEffect.OPEN,
        position_evidence_cut=NOW,
        position_evidence=_evidence("0"),
    )
    close_request = _request(
        side=OrderSide.SELL,
        position_effect=PositionEffect.AUTO,
        effective_position_effect=PositionEffect.CLOSE,
        position_evidence_cut=NOW,
        position_evidence=_evidence("10"),
    )
    assert request_fingerprint(open_request) != request_fingerprint(close_request)


def test_different_position_evidence_cuts_have_different_fingerprints() -> None:
    later = datetime(2026, 1, 5, 10, 1, tzinfo=UTC)
    first = _request(
        position_effect=PositionEffect.AUTO,
        effective_position_effect=PositionEffect.OPEN,
        position_evidence_cut=NOW,
        position_evidence=_evidence("0", cut=NOW),
        position_effect_approval_instant=later,
    )
    second = _request(
        position_effect=PositionEffect.AUTO,
        effective_position_effect=PositionEffect.OPEN,
        position_evidence_cut=later,
        position_evidence=_evidence("0", cut=later),
        position_effect_approval_instant=later,
    )
    assert request_fingerprint(first) != request_fingerprint(second)


def test_different_approval_instants_have_different_fingerprints() -> None:
    later = datetime(2026, 1, 5, 10, 1, tzinfo=UTC)
    first = _request(
        quantity=Decimal("5"),
        position_effect=PositionEffect.CLOSE,
        effective_position_effect=PositionEffect.CLOSE,
        position_evidence_cut=NOW,
        position_evidence=_evidence("-5", cut=NOW),
    )
    second = _request(
        quantity=Decimal("5"),
        position_effect=PositionEffect.CLOSE,
        effective_position_effect=PositionEffect.CLOSE,
        position_evidence_cut=NOW,
        position_evidence=_evidence("-5", cut=NOW),
        position_effect_approval_instant=later,
    )
    assert request_fingerprint(first) != request_fingerprint(second)


def test_rule_identity_changes_fingerprint() -> None:
    base = _request(product=ProductCode("CNC"), market_pack_id="india-equity", rule_version="v1")
    next_version = _request(
        product=ProductCode("CNC"), market_pack_id="india-equity", rule_version="v2"
    )
    other_pack = _request(product=ProductCode("CNC"), market_pack_id="india-fno", rule_version="v1")
    base_fingerprint = request_fingerprint(base)
    assert request_fingerprint(next_version) != base_fingerprint
    assert request_fingerprint(other_pack) != base_fingerprint


def test_product_selection_proof_participates_in_fingerprint() -> None:
    """The canonical fingerprint hashes the product proof payload itself.

    A persisted proof therefore cannot be altered without changing the
    request identity, which is what the pending-context decode compares.
    """
    product = ProductCode("CNC")
    request = _request(
        product=product,
        product_resolution=ProductSelectionResolution(
            market=MARKET,
            product=product,
            market_pack_id="test-pack",
            rule_version="test-v1",
        ),
    )

    payload = fingerprint_payload(request)

    assert payload["product_resolution"] == request.product_resolution.to_payload()
    assert request_fingerprint(request) == request_fingerprint(request)


def test_equivalent_position_effect_instants_share_a_fingerprint() -> None:
    utc_cut = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    ist = timezone(timedelta(hours=5, minutes=30))
    ist_cut = utc_cut.astimezone(ist)

    first = _request(
        quantity=Decimal("5"),
        position_effect=PositionEffect.CLOSE,
        effective_position_effect=PositionEffect.CLOSE,
        position_evidence_cut=utc_cut,
        position_evidence=_evidence("-5", cut=utc_cut),
    )
    second = _request(
        quantity=Decimal("5"),
        position_effect=PositionEffect.CLOSE,
        effective_position_effect=PositionEffect.CLOSE,
        position_evidence_cut=ist_cut,
        position_evidence=_evidence("-5", cut=ist_cut),
    )

    assert request_fingerprint(first) == request_fingerprint(second)


def test_canonical_datetime_normalizes_offsets_and_rejects_naive_values() -> None:
    utc_cut = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
    ist_cut = utc_cut.astimezone(timezone(timedelta(hours=5, minutes=30)))

    assert _canonical_datetime(utc_cut) == _canonical_datetime(ist_cut)
    with pytest.raises(ValueError, match="timezone-aware"):
        _canonical_datetime(datetime(2026, 1, 5, 10, 0))
