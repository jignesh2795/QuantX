"""Adversarial regressions for execution-request proof authenticity.

A product-selection or absent-position-effect proof is a claim. These tests
attack that claim the way an attacker or a broken caller would: build a proof
that is internally consistent, names the canonical market pack, and asserts
something the versioned policy never declared. The trusted policy, not the
claim, must decide.

The attack surfaces covered here are:

* a product claim that names a product the pack never supported (``NRML``);
* an absent-effect claim that declares ``not applicable`` for a product the
  pack never covered (``MIS``);
* a missing proof, a wrong rule version, and an unavailable policy;
* a fabricated proof persisted in the pending context, with and without a
  recomputed fingerprint;
* a tampered proof or tampered execution fields that keep the old digest.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
from quantx.application.pending_recovery import PendingExecutionRecoveryRunner
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import OrderSide, OrderType, PositionEffect
from quantx.domain.execution_request import (
    ApprovedExecutionRequest,
    PendingExecutionRecoveryRequest,
    build_order_from_intent,
)
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.policy_verification import (
    MarketPackPolicyVerifier,
    ProofVerificationError,
)
from quantx.domain.position_effect import (
    AbsentPositionEffectResolution,
    PositionEffectPolicy,
    PositionEffectRule,
)
from quantx.domain.product_selection import (
    ProductSelectionPolicy,
    ProductSelectionResolution,
    ProductSelectionRule,
)
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId, ProductCode
from quantx.execution.idempotency import PendingExecutionContext
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.preconditions.models import PreconditionsResult, PreconditionsStatus
from quantx.execution.transactions.coordinator import ExecutionTransactionCoordinator
from quantx.india.market_pack import (
    INDIA_EQUITY_MARKET,
    INDIA_EQUITY_MARKET_PACK_ID,
    INDIA_EQUITY_POSITION_EFFECT_POLICY,
    INDIA_EQUITY_PRODUCT_SELECTION,
    INDIA_EQUITY_RULE_VERSION,
)
from quantx.persistence.sqlite import SqliteDatabase, SqliteUnitOfWork

CHECKED_AT = datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)
CANONICAL_VERIFIER = MarketPackPolicyVerifier(
    product_selection_policies=(INDIA_EQUITY_PRODUCT_SELECTION,),
    position_effect_policies=(INDIA_EQUITY_POSITION_EFFECT_POLICY,),
)


def _context(
    *,
    mode: ExecutionMode = ExecutionMode.PAPER,
    market: MarketContext = INDIA_EQUITY_MARKET,
    market_pack_id: str | None = INDIA_EQUITY_MARKET_PACK_ID,
    rule_version: str | None = INDIA_EQUITY_RULE_VERSION,
) -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=market,
        broker_connection_id=None if mode is ExecutionMode.PAPER else BrokerConnectionId("conn-1"),
        execution_mode=mode,
        market_pack_id=market_pack_id,
        rule_version=rule_version,
    )


_UNSET = object()


def _request(
    *,
    product: ProductCode | None = None,
    product_resolution: ProductSelectionResolution | None = None,
    position_effect: PositionEffect | None = None,
    position_effect_policy_resolution: AbsentPositionEffectResolution | None = None,
    market: MarketContext = INDIA_EQUITY_MARKET,
    market_pack_id: str | None = INDIA_EQUITY_MARKET_PACK_ID,
    rule_version: str | None = INDIA_EQUITY_RULE_VERSION,
    mode: ExecutionMode = ExecutionMode.PAPER,
    omit_absent_effect_proof: bool = False,
) -> ApprovedExecutionRequest:
    """Build a request directly, with exactly the claims a test wants.

    An absent position effect always needs a claim, so the default is a
    self-consistent claim for the request's product; a test that wants a
    different claim passes it explicitly, and a test that wants no claim at
    all asks for the omission explicitly.
    """
    context = _context(
        mode=mode,
        market=market,
        market_pack_id=market_pack_id,
        rule_version=rule_version,
    )
    if (
        position_effect is None
        and position_effect_policy_resolution is None
        and not omit_absent_effect_proof
    ):
        position_effect_policy_resolution = _forged_absent_effect_claim(
            product if product is not None else ProductCode("CNC"),
            market=market,
            market_pack_id=market_pack_id or INDIA_EQUITY_MARKET_PACK_ID,
            rule_version=rule_version or INDIA_EQUITY_RULE_VERSION,
        )
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        order_type=OrderType.MARKET,
        product=product,
        position_effect=position_effect,
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
        product=product,
        position_effect=position_effect,
        product_resolution=product_resolution,
        position_effect_policy_resolution=position_effect_policy_resolution,
    )


def _forged_product_claim(
    product: ProductCode,
    *,
    market: MarketContext = INDIA_EQUITY_MARKET,
    market_pack_id: str = INDIA_EQUITY_MARKET_PACK_ID,
    rule_version: str = INDIA_EQUITY_RULE_VERSION,
) -> ProductSelectionResolution:
    """A self-consistent product claim the canonical pack never made."""
    return ProductSelectionResolution(
        market=market,
        product=product,
        market_pack_id=market_pack_id,
        rule_version=rule_version,
    )


def _forged_absent_effect_claim(
    product: ProductCode,
    *,
    market: MarketContext = INDIA_EQUITY_MARKET,
    market_pack_id: str = INDIA_EQUITY_MARKET_PACK_ID,
    rule_version: str = INDIA_EQUITY_RULE_VERSION,
) -> AbsentPositionEffectResolution:
    """A self-consistent absent-effect claim the canonical pack never made."""
    return AbsentPositionEffectResolution(
        market=market,
        product=product,
        rule_product=product,
        market_pack_id=market_pack_id,
        rule_version=rule_version,
        effective=None,
        not_applicable=True,
    )


# The canonical seam.


def test_forged_product_claim_naming_an_unsupported_product_is_rejected() -> None:
    """``NRML`` is not a product the India NSE equity pack supports."""
    request = _request(
        product=ProductCode("NRML"),
        product_resolution=_forged_product_claim(ProductCode("NRML")),
    )

    with pytest.raises(ProofVerificationError, match="is not supported for market"):
        CANONICAL_VERIFIER.verify_request(request)


def test_forged_absent_effect_claim_for_mis_is_rejected() -> None:
    """The pack declares no absent-effect rule for ``MIS``."""
    request = _request(
        product=ProductCode("MIS"),
        product_resolution=_forged_product_claim(ProductCode("MIS")),
        position_effect_policy_resolution=_forged_absent_effect_claim(ProductCode("MIS")),
    )

    with pytest.raises(ProofVerificationError, match="no versioned position-effect rule"):
        CANONICAL_VERIFIER.verify_request(request)


@pytest.mark.parametrize("product", [ProductCode("CNC"), ProductCode("DELIVERY")])
def test_valid_delivery_absent_effect_claims_remain_valid(product: ProductCode) -> None:
    """The pack's own delivery rules still authenticate their claims."""
    rule = INDIA_EQUITY_POSITION_EFFECT_POLICY.resolve(INDIA_EQUITY_MARKET, product)
    assert rule.not_applicable is True
    assert rule.product == product

    request = _request(
        product=product,
        product_resolution=_forged_product_claim(product),
        position_effect_policy_resolution=_forged_absent_effect_claim(product),
    )

    CANONICAL_VERIFIER.verify_request(request)


def test_missing_product_proof_fails_closed_at_the_request_boundary() -> None:
    """A resolved product without its proof never becomes a request."""
    with pytest.raises(ValueError, match="requires a validated product selection resolution"):
        _request(product=ProductCode("CNC"), product_resolution=None)


def test_missing_absent_effect_proof_fails_closed_at_the_request_boundary() -> None:
    """An absent effect without its proof never becomes a request."""
    with pytest.raises(ValueError, match="requires a validated market-pack policy resolution"):
        _request(
            product=ProductCode("CNC"),
            product_resolution=_forged_product_claim(ProductCode("CNC")),
            omit_absent_effect_proof=True,
        )


def test_verifier_refuses_a_request_without_a_product_proof() -> None:
    """The seam itself fails closed when a caller skips the constructor."""
    request = _request(
        product=ProductCode("CNC"),
        product_resolution=_forged_product_claim(ProductCode("CNC")),
    )
    stripped = SimpleNamespace(
        execution_context=request.execution_context,
        product=request.product,
        position_effect=request.position_effect,
        product_resolution=None,
        position_effect_policy_resolution=request.position_effect_policy_resolution,
    )

    with pytest.raises(ProofVerificationError, match="requires a validated product selection"):
        CANONICAL_VERIFIER.verify_request(stripped)


def test_verifier_refuses_a_request_without_an_absent_effect_proof() -> None:
    request = _request(
        product=ProductCode("CNC"),
        product_resolution=_forged_product_claim(ProductCode("CNC")),
    )
    stripped = SimpleNamespace(
        execution_context=request.execution_context,
        product=request.product,
        position_effect=request.position_effect,
        product_resolution=request.product_resolution,
        position_effect_policy_resolution=None,
    )

    with pytest.raises(ProofVerificationError, match="requires a validated market-pack policy"):
        CANONICAL_VERIFIER.verify_request(stripped)


def test_wrong_rule_version_fails_closed() -> None:
    """A claim naming a rule version no trusted policy carries is refused."""
    request = _request(
        product=ProductCode("CNC"),
        product_resolution=_forged_product_claim(
            ProductCode("CNC"),
            rule_version="india-products-v2",
        ),
        market_pack_id="india-equity",
        rule_version="india-products-v2",
    )

    with pytest.raises(ProofVerificationError, match="no trusted product selection policy"):
        CANONICAL_VERIFIER.verify_request(request)


def test_unavailable_policy_fails_closed() -> None:
    """No trusted policy means no claim can be authenticated."""
    request = _request(
        product=ProductCode("CNC"),
        product_resolution=_forged_product_claim(ProductCode("CNC")),
    )

    with pytest.raises(ProofVerificationError, match="no trusted product selection policy"):
        MarketPackPolicyVerifier().verify_request(request)


def test_verifier_rejects_a_product_proof_for_a_different_request_product() -> None:
    """A proof for one supported product cannot authenticate another product."""
    request = SimpleNamespace(
        execution_context=_context(),
        product=ProductCode("CNC"),
        position_effect=PositionEffect.OPEN,
        effective_position_effect=None,
        product_resolution=_forged_product_claim(ProductCode("MIS")),
        position_effect_policy_resolution=None,
    )

    with pytest.raises(
        ProofVerificationError,
        match="product selection resolution product does not match the resolved product",
    ):
        CANONICAL_VERIFIER.verify_request(request)


def test_verifier_rejects_a_product_proof_for_a_different_market() -> None:
    """A proof for another market cannot authenticate the request context."""
    other_market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN")
    product_policy = ProductSelectionPolicy(
        market_pack_id=INDIA_EQUITY_MARKET_PACK_ID,
        rule_version=INDIA_EQUITY_RULE_VERSION,
        rules=(
            ProductSelectionRule(
                market=INDIA_EQUITY_MARKET,
                supported_products=frozenset({ProductCode("CNC")}),
            ),
            ProductSelectionRule(
                market=other_market,
                supported_products=frozenset({ProductCode("CNC")}),
            ),
        ),
    )
    request = SimpleNamespace(
        execution_context=_context(),
        product=ProductCode("CNC"),
        position_effect=PositionEffect.OPEN,
        effective_position_effect=None,
        product_resolution=ProductSelectionResolution(
            market=other_market,
            product=ProductCode("CNC"),
            market_pack_id=INDIA_EQUITY_MARKET_PACK_ID,
            rule_version=INDIA_EQUITY_RULE_VERSION,
        ),
        position_effect_policy_resolution=None,
    )

    with pytest.raises(
        ProofVerificationError,
        match="product selection resolution market does not match the execution context",
    ):
        MarketPackPolicyVerifier(product_selection_policies=(product_policy,)).verify_request(
            request
        )


def test_verifier_rejects_a_proof_attached_to_an_absent_product() -> None:
    """An absent product cannot carry a product-selection claim."""
    request = SimpleNamespace(
        execution_context=_context(),
        product=None,
        position_effect=PositionEffect.OPEN,
        effective_position_effect=None,
        product_resolution=_forged_product_claim(ProductCode("CNC")),
        position_effect_policy_resolution=None,
    )

    with pytest.raises(
        ProofVerificationError,
        match="an absent product cannot carry a product selection resolution",
    ):
        CANONICAL_VERIFIER.verify_request(request)


def test_verifier_rejects_an_absent_effect_proof_for_a_different_market() -> None:
    """An absent-effect proof for another market cannot authenticate the context."""
    other_market = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "BSE", "IN")
    effect_policy = PositionEffectPolicy(
        market_pack_id=INDIA_EQUITY_MARKET_PACK_ID,
        rule_version=INDIA_EQUITY_RULE_VERSION,
        rules=(
            PositionEffectRule(
                market=INDIA_EQUITY_MARKET,
                product=ProductCode("CNC"),
                not_applicable=True,
            ),
            PositionEffectRule(
                market=other_market,
                product=ProductCode("CNC"),
                not_applicable=True,
            ),
        ),
    )
    request = SimpleNamespace(
        execution_context=_context(),
        product=ProductCode("CNC"),
        position_effect=None,
        effective_position_effect=None,
        product_resolution=_forged_product_claim(ProductCode("CNC")),
        position_effect_policy_resolution=AbsentPositionEffectResolution(
            market=other_market,
            product=ProductCode("CNC"),
            rule_product=ProductCode("CNC"),
            market_pack_id=INDIA_EQUITY_MARKET_PACK_ID,
            rule_version=INDIA_EQUITY_RULE_VERSION,
            effective=None,
            not_applicable=True,
        ),
    )

    with pytest.raises(
        ProofVerificationError,
        match="position-effect policy resolution market does not match the execution context",
    ):
        MarketPackPolicyVerifier(
            product_selection_policies=(INDIA_EQUITY_PRODUCT_SELECTION,),
            position_effect_policies=(effect_policy,),
        ).verify_request(request)


def test_verifier_rejects_an_absent_effect_proof_for_a_different_effective_effect() -> None:
    """An authentic proof cannot authenticate a different recorded effect."""
    request = SimpleNamespace(
        execution_context=_context(),
        product=ProductCode("CNC"),
        position_effect=None,
        effective_position_effect=PositionEffect.OPEN,
        product_resolution=_forged_product_claim(ProductCode("CNC")),
        position_effect_policy_resolution=_forged_absent_effect_claim(ProductCode("CNC")),
    )

    with pytest.raises(
        ProofVerificationError,
        match="position-effect policy resolution does not match the resolved effective effect",
    ):
        CANONICAL_VERIFIER.verify_request(request)


def test_verifier_rejects_an_absent_effect_proof_on_an_explicit_effect() -> None:
    """An explicit effect cannot carry an absent-effect claim."""
    request = SimpleNamespace(
        execution_context=_context(),
        product=ProductCode("CNC"),
        position_effect=PositionEffect.OPEN,
        effective_position_effect=None,
        product_resolution=_forged_product_claim(ProductCode("CNC")),
        position_effect_policy_resolution=_forged_absent_effect_claim(ProductCode("CNC")),
    )

    with pytest.raises(
        ProofVerificationError,
        match="a position-effect policy resolution is only valid for an absent position effect",
    ):
        CANONICAL_VERIFIER.verify_request(request)


def test_a_policy_for_another_market_pack_is_not_trusted() -> None:
    """A claim naming a foreign pack identity never matches a trusted policy."""
    request = _request(
        product=ProductCode("CNC"),
        product_resolution=_forged_product_claim(
            ProductCode("CNC"),
            market_pack_id="other-pack",
            rule_version="other-v1",
        ),
        market_pack_id="other-pack",
        rule_version="other-v1",
    )

    with pytest.raises(ProofVerificationError, match="no trusted product selection policy"):
        CANONICAL_VERIFIER.verify_request(request)


def test_another_market_pack_policy_remains_modular() -> None:
    """A plugin-supplied pack authenticates its own claims and only its own."""
    other_market = MarketContext(MarketRegion.NORTH_AMERICA, MarketFamily.EQUITY, "NYSE", "US")
    other_selection = ProductSelectionPolicy(
        market_pack_id="other-pack",
        rule_version="other-v1",
        rules=(
            ProductSelectionRule(
                market=other_market,
                default_product=ProductCode("CASH"),
                supported_products=frozenset({ProductCode("CASH")}),
            ),
        ),
    )
    other_effects = PositionEffectPolicy(
        market_pack_id="other-pack",
        rule_version="other-v1",
        rules=(PositionEffectRule(market=other_market, not_applicable=True),),
    )
    verifier = MarketPackPolicyVerifier(
        product_selection_policies=(other_selection,),
        position_effect_policies=(other_effects,),
    )
    request = _request(
        product=ProductCode("CASH"),
        product_resolution=_forged_product_claim(
            ProductCode("CASH"),
            market=other_market,
            market_pack_id="other-pack",
            rule_version="other-v1",
        ),
        position_effect_policy_resolution=AbsentPositionEffectResolution(
            market=other_market,
            product=ProductCode("CASH"),
            rule_product=None,
            market_pack_id="other-pack",
            rule_version="other-v1",
            effective=None,
            not_applicable=True,
        ),
        market=other_market,
        market_pack_id="other-pack",
        rule_version="other-v1",
    )

    verifier.verify_request(request)

    with pytest.raises(ProofVerificationError, match="no trusted product selection policy"):
        CANONICAL_VERIFIER.verify_request(request)


# The execution boundaries.


class _CountingGate:
    def __init__(self) -> None:
        self.allow_calls = 0
        self.permit_calls = 0
        self.admit_calls = 0

    def allow(self) -> bool:
        self.allow_calls += 1
        return True

    def state(self) -> object:
        return object()

    def is_durable(self) -> bool:
        return True

    def submission_permit(self):  # pragma: no cover - never reached
        raise AssertionError("the gate must not be entered for an unverifiable request")

    def admit_submission(self) -> bool:  # pragma: no cover - never reached
        raise AssertionError("the gate must not be entered for an unverifiable request")


class _CountingIdempotencyStore:
    def __init__(self) -> None:
        self.reserve_calls = 0
        self.check_calls = 0

    def reserve_or_get(self, client_order_id, request_fingerprint):
        self.reserve_calls += 1
        raise AssertionError("an unverifiable request must not reserve an idempotency slot")

    def check(self, client_order_id, request_fingerprint):
        self.check_calls += 1
        raise AssertionError("an unverifiable request must not inspect a reservation")


def test_orchestrator_blocks_a_forged_product_claim_before_any_side_effect() -> None:
    gate = _CountingGate()
    request = _request(
        product=ProductCode("NRML"),
        product_resolution=_forged_product_claim(ProductCode("NRML")),
    )

    result = ExecutionOrchestrator(
        trading_gate=gate,
        policy_verifier=CANONICAL_VERIFIER,
    ).execute(request)

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert "request policy verification failed" in result.reason
    assert gate.allow_calls == 0


def test_coordinator_blocks_a_forged_absent_effect_claim_before_reservation() -> None:
    store = _CountingIdempotencyStore()
    request = _request(
        product=ProductCode("MIS"),
        product_resolution=_forged_product_claim(ProductCode("MIS")),
        position_effect_policy_resolution=_forged_absent_effect_claim(ProductCode("MIS")),
    )

    result = ExecutionTransactionCoordinator(
        idempotency=store,
        preconditions=lambda _: PreconditionsResult(PreconditionsStatus.READY),
        submit=lambda _: None,
        policy_verifier=CANONICAL_VERIFIER,
    ).execute(request)

    assert result.status is PreconditionsStatus.BLOCKED
    assert result.reasons == ("request policy verification failed",)
    assert store.reserve_calls == 0
    assert store.check_calls == 0


# The persisted recovery path.


def _pending_payload(request: ApprovedExecutionRequest) -> dict:
    fingerprint = request_fingerprint(request)
    context = PendingExecutionContext.from_request(request, fingerprint)
    return json.loads(context.to_json())


def test_pending_decode_rejects_a_tampered_proof_that_keeps_the_old_fingerprint() -> None:
    """A changed proof with the old digest must not be recovered."""
    request = _request(
        product=ProductCode("CNC"),
        product_resolution=_forged_product_claim(ProductCode("CNC")),
        mode=ExecutionMode.LIVE,
    )
    payload = _pending_payload(request)
    # A consistent forgery: the claim, the request product, and the order
    # product all name the same unsupported product, and only the digest is
    # left stale.
    payload["product_resolution"]["product"] = "NRML"
    payload["position_effect_policy_resolution"]["product"] = "NRML"
    payload["position_effect_policy_resolution"]["rule_product"] = "NRML"
    payload["product"] = "NRML"
    payload["order"]["product"] = "NRML"

    with pytest.raises(ValueError, match="fingerprint does not match its execution semantics"):
        PendingExecutionContext.from_json(json.dumps(payload))


def test_pending_decode_rejects_tampered_execution_fields_with_the_old_fingerprint() -> None:
    """A changed quantity with the old digest must not be recovered."""
    request = _request(
        product=ProductCode("CNC"),
        product_resolution=_forged_product_claim(ProductCode("CNC")),
        mode=ExecutionMode.LIVE,
    )
    payload = _pending_payload(request)
    payload["order"]["quantity"] = "3"

    with pytest.raises(ValueError, match="fingerprint does not match its execution semantics"):
        PendingExecutionContext.from_json(json.dumps(payload))


def test_pending_decode_rejects_a_missing_proof() -> None:
    request = _request(
        product=ProductCode("CNC"),
        product_resolution=_forged_product_claim(ProductCode("CNC")),
        mode=ExecutionMode.LIVE,
    )
    payload = _pending_payload(request)
    payload.pop("product_resolution")

    with pytest.raises(ValueError):
        PendingExecutionContext.from_json(json.dumps(payload))


def _reserve(unit_of_work, request: ApprovedExecutionRequest) -> str:
    fingerprint = request_fingerprint(request)
    unit_of_work.idempotency.reserve_or_get(
        request.order.client_order_id,
        fingerprint,
        PendingExecutionContext.from_request(request, fingerprint),
    )
    return fingerprint


def _recovery_runner(unit_of_work, verifier: MarketPackPolicyVerifier):
    return PendingExecutionRecoveryRunner(
        unit_of_work=unit_of_work,
        provider_resolver=lambda request: (_ for _ in ()).throw(
            AssertionError("an unverifiable pending context must not reach a broker provider")
        ),
        policy_verifier=verifier,
    )


def test_recovery_refuses_a_self_consistent_fabricated_proof(tmp_path) -> None:
    """A fabricated pending proof is refused even when it is fully consistent.

    The fabricator recomputed the digest, so the decode cannot detect the
    tampering. The trusted policy still refuses the claim, and the record
    fails safely instead of being recovered.
    """
    request = _request(
        product=ProductCode("NRML"),
        product_resolution=_forged_product_claim(ProductCode("NRML")),
        position_effect_policy_resolution=_forged_absent_effect_claim(ProductCode("NRML")),
        mode=ExecutionMode.LIVE,
    )
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        unit_of_work = SqliteUnitOfWork(database)
        _reserve(unit_of_work, request)

        results = _recovery_runner(unit_of_work, CANONICAL_VERIFIER).run(checked_at=CHECKED_AT)

    assert len(results.results) == 1
    assert results.results[0].definitive is False
    assert results.results[0].error is not None
    assert "pending recovery failed safely" in results.results[0].error


def test_recovery_refuses_a_self_consistent_fabricated_absent_effect_claim(tmp_path) -> None:
    """A fabricated absent-effect claim is refused even with a fresh digest.

    ``MIS`` is a supported product, so the product claim is authentic; the
    claim that the pack declares the effect not applicable for it is not.
    """
    request = _request(
        product=ProductCode("MIS"),
        product_resolution=_forged_product_claim(ProductCode("MIS")),
        position_effect_policy_resolution=_forged_absent_effect_claim(ProductCode("MIS")),
        mode=ExecutionMode.LIVE,
    )
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        unit_of_work = SqliteUnitOfWork(database)
        _reserve(unit_of_work, request)

        results = _recovery_runner(unit_of_work, CANONICAL_VERIFIER).run(checked_at=CHECKED_AT)

    assert len(results.results) == 1
    assert results.results[0].definitive is False
    assert results.results[0].error is not None
    assert "pending recovery failed safely" in results.results[0].error


def test_recovery_accepts_an_authentic_pending_context(tmp_path) -> None:
    """The unchanged, authentic path still recovers."""
    request = _request(
        product=ProductCode("CNC"),
        product_resolution=_forged_product_claim(ProductCode("CNC")),
        position_effect_policy_resolution=_forged_absent_effect_claim(ProductCode("CNC")),
        mode=ExecutionMode.LIVE,
    )
    with SqliteDatabase(tmp_path / "quantx.db") as database:
        unit_of_work = SqliteUnitOfWork(database)
        _reserve(unit_of_work, request)

        records = unit_of_work.idempotency.list_pending_recovery_records()

    assert len(records) == 1
    assert records[0].error is None
    assert records[0].context is not None
    recovery_request = records[0].context.to_recovery_request()
    assert isinstance(recovery_request, PendingExecutionRecoveryRequest)
    CANONICAL_VERIFIER.verify_request(recovery_request)
