from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.clock import FixedClock
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId
from quantx.execution.idempotency import (
    IdempotencyDecision,
    InMemoryIdempotencyStore,
    request_fingerprint,
)
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.paper import (
    PaperExecutionEngine,
    PaperExecutionError,
    PaperSimulationProfile,
    QuoteSnapshot,
)
from quantx.persistence import ReceiptRepository


def _request(mode: ExecutionMode = ExecutionMode.PAPER) -> ApprovedExecutionRequest:
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=BrokerConnectionId("paper-1") if mode is ExecutionMode.LIVE else None,
        execution_mode=mode,
    )
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        execution_context=context,
    )
    order = build_order_from_intent(intent)
    policy = (
        PolicyResult(PolicyDecision.APPROVE, "approved") if mode is ExecutionMode.LIVE else None
    )
    return ApprovedExecutionRequest(
        order, context, RiskResult(RiskDecision.APPROVE, "approved"), policy
    )


def _snapshot(*, bid=None, ask=None, last=None) -> MarketSnapshot:
    return MarketSnapshot(
        instrument=InstrumentId("NSE", "TCS"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        bid=bid,
        ask=ask,
        last=last,
    )


def test_market_buy_uses_observed_ask_and_explicit_slippage() -> None:
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        profile=PaperSimulationProfile(slippage_bps=Decimal("10")),
    )
    receipt = engine.execute(_request(), snapshot=_snapshot(bid=Decimal("99"), ask=Decimal("100")))
    assert receipt.simulated is True
    assert receipt.fills[0].price == Decimal("100.10")


def test_simulation_latency_is_applied_to_fill_and_receipt() -> None:
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        profile=PaperSimulationProfile(latency_ms=250),
    )
    receipt = engine.execute(
        _request(),
        snapshot=_snapshot(ask=Decimal("100")),
    )

    expected = datetime(2026, 1, 1, 0, 0, 0, 250000, tzinfo=UTC)
    assert receipt.executed_at == expected
    assert receipt.fills[0].filled_at == expected


def test_repeated_client_order_is_idempotent() -> None:
    engine = PaperExecutionEngine(clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)))
    request = _request()
    snapshot = _snapshot(ask=Decimal("100"))
    first = engine.execute(request, snapshot=snapshot)
    second = engine.execute(request, snapshot=snapshot)
    assert first == second
    assert len(engine.events()) == 2


def test_reusing_client_order_id_for_changed_request_is_blocked() -> None:
    engine = PaperExecutionEngine(clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)))
    request = _request()
    engine.execute(request, snapshot=_snapshot(ask=Decimal("100")))
    changed_order = replace(request.order, quantity=Decimal("11"))
    changed_request = replace(request, order=changed_order)

    with pytest.raises(ValueError, match="different request"):
        engine.execute(changed_request, snapshot=_snapshot(ask=Decimal("100")))


def test_missing_required_price_does_not_create_a_fill() -> None:
    engine = PaperExecutionEngine(clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)))
    receipt = engine.execute(_request(), snapshot=_snapshot(bid=Decimal("99")))
    assert receipt.fills == ()
    assert receipt.order_status.value == "ACCEPTED"
    assert "does_not_create_a_fill" in receipt.assumptions[-1]


def test_snapshot_instrument_must_match_order() -> None:
    engine = PaperExecutionEngine(clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)))
    mismatched = MarketSnapshot(
        instrument=InstrumentId("NSE", "INFY"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ask=Decimal("100"),
    )
    with pytest.raises(PaperExecutionError, match="does not match"):
        engine.execute(_request(), snapshot=mismatched)


def test_paper_engine_rejects_live_mode() -> None:
    engine = PaperExecutionEngine(clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)))
    with pytest.raises(PaperExecutionError, match="PAPER, SHADOW, or REPLAY"):
        engine.execute(_request(ExecutionMode.LIVE), snapshot=_snapshot(ask=Decimal("100")))


class _StaleObservationStore:
    """Expose a stale direct observation while keeping acquisition atomic.

    Direct check() calls always miss, as if a concurrent completion landed
    between observation and acquisition. reserve_or_get() delegates to the
    real atomic operation, so only a single-acquisition engine observes the
    completed receipt.
    """

    def __init__(self, real: InMemoryIdempotencyStore) -> None:
        self._real = real

    def check(self, client_order_id, request_fingerprint):
        return IdempotencyDecision(
            client_order_id=client_order_id,
            request_fingerprint=request_fingerprint,
        )

    def reserve_or_get(self, client_order_id, request_fingerprint):
        return self._real.reserve_or_get(client_order_id, request_fingerprint)

    def complete(self, client_order_id, request_fingerprint, receipt_id):
        return self._real.complete(client_order_id, request_fingerprint, receipt_id)

    def resolve_pending(self, client_order_id, request_fingerprint, receipt_id):
        return self._real.resolve_pending(client_order_id, request_fingerprint, receipt_id)


def test_stale_observation_returns_cached_receipt_not_pending() -> None:
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        idempotency_store=_StaleObservationStore(InMemoryIdempotencyStore()),
    )
    request = _request()
    snapshot = _snapshot(ask=Decimal("100"))
    first = engine.execute(request, snapshot=snapshot)
    second = engine.execute(request, snapshot=snapshot)
    assert second == first


class _FakeReceiptRepository(ReceiptRepository):
    def __init__(self) -> None:
        self._receipts = {}

    def save(self, receipt) -> None:
        self._receipts[receipt.receipt_id] = receipt

    def get(self, receipt_id):
        return self._receipts.get(receipt_id)

    def get_by_client_order(self, client_order_id):
        for receipt in self._receipts.values():
            if receipt.client_order_id == client_order_id:
                return receipt
        return None


def test_repository_backed_duplicate_returns_authoritative_receipt() -> None:
    repository = _FakeReceiptRepository()
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        receipt_repository=repository,
    )
    request = _request()
    snapshot = _snapshot(ask=Decimal("100"))
    first = engine.execute(request, snapshot=snapshot)
    assert repository.get(first.receipt_id) == first
    second = engine.execute(request, snapshot=snapshot)
    assert second == first


def test_fresh_execution_saves_receipt_to_repository() -> None:
    repository = _FakeReceiptRepository()
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        receipt_repository=repository,
    )
    receipt = engine.execute(_request(), snapshot=_snapshot(ask=Decimal("100")))
    assert repository.get(receipt.receipt_id) == receipt
    assert repository.get_by_client_order(receipt.client_order_id) == receipt


def test_cache_conflict_cannot_override_repository_receipt() -> None:
    repository = _FakeReceiptRepository()
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        receipt_repository=repository,
    )
    request = _request()
    snapshot = _snapshot(ask=Decimal("100"))
    first = engine.execute(request, snapshot=snapshot)
    engine._receipts[request.order.client_order_id] = replace(
        first, receipt_id=uuid4(), message="stale cache entry"
    )
    second = engine.execute(request, snapshot=snapshot)
    assert second == first


def test_missing_repository_receipt_fails_closed_without_resubmit() -> None:
    store = InMemoryIdempotencyStore()
    repository = _FakeReceiptRepository()
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        idempotency_store=store,
        receipt_repository=repository,
    )
    request = _request()
    snapshot = _snapshot(ask=Decimal("100"))
    fingerprint = request_fingerprint(request)
    store.reserve_or_get(request.order.client_order_id, fingerprint)
    store.complete(request.order.client_order_id, fingerprint, uuid4())
    with pytest.raises(PaperExecutionError, match="authoritative repository"):
        engine.execute(request, snapshot=snapshot)
    assert engine.events() == ()
    with pytest.raises(PaperExecutionError, match="authoritative repository"):
        engine.execute(request, snapshot=snapshot)
    assert engine.events() == ()


# Compatibility smoke test for the transitional alias.
def test_quote_snapshot_alias_matches_market_snapshot() -> None:
    quote = QuoteSnapshot(
        instrument=InstrumentId("NSE", "TCS"),
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        ask=Decimal("100"),
    )
    assert isinstance(quote, MarketSnapshot)


def test_slippage_config_requires_decimal() -> None:
    PaperSimulationProfile(slippage_bps=Decimal("10"))
    PaperSimulationProfile(slippage_bps=Decimal("0"))

    with pytest.raises(TypeError, match="slippage_bps must be a Decimal"):
        PaperSimulationProfile(slippage_bps=0.1)  # type: ignore[arg-type]


def test_slippage_config_rejects_negative() -> None:
    with pytest.raises(ValueError, match="bps values cannot be negative"):
        PaperSimulationProfile(slippage_bps=Decimal("-1"))


def test_market_sell_slippage_divides_reference_price() -> None:
    intent = TradeIntent(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.SELL,
        quantity=Decimal("10"),
        order_type=OrderType.MARKET,
        execution_context=_request().execution_context,
    )
    order = build_order_from_intent(intent)
    request = ApprovedExecutionRequest(
        order,
        _request().execution_context,
        RiskResult(RiskDecision.APPROVE, "approved"),
    )
    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        profile=PaperSimulationProfile(slippage_bps=Decimal("10")),
    )
    receipt = engine.execute(request, snapshot=_snapshot(bid=Decimal("100"), ask=Decimal("101")))

    assert receipt.fills[0].price == Decimal("100") / Decimal("1.001")
    assert str(receipt.fills[0].price) == "99.90009990009990009990009990"


def test_slipped_fill_records_reference_price_deterministically() -> None:
    first_engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        profile=PaperSimulationProfile(slippage_bps=Decimal("10")),
    )
    second_engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        profile=PaperSimulationProfile(slippage_bps=Decimal("10")),
    )
    snapshot = _snapshot(bid=Decimal("99"), ask=Decimal("100"))
    first = first_engine.execute(_request(), snapshot=snapshot)
    second = second_engine.execute(_request(), snapshot=snapshot)

    for receipt in (first, second):
        assert "slippage_bps=10" in receipt.assumptions
        assert "reference_price=100" in receipt.assumptions
        assert "realized_price=100.100" in receipt.assumptions
        assert "realized_quantity=10" in receipt.assumptions
        assert "remaining_quantity=0" in receipt.assumptions
        assert "execution_model_id=QUOTE" in receipt.assumptions
        assert "execution_model_version=paper-core-v0.3" in receipt.assumptions
        assert "slippage_model_id=paper.fixed_bps_slippage" in receipt.assumptions
        assert "slippage_model_version=1" in receipt.assumptions
        assert "configured_simulation_profile" in receipt.assumptions
        assert receipt.fills[0].price == Decimal("100.10")
    assert first.message == second.message
    assert first.assumptions == second.assumptions
    assert first.fills[0].price == second.fills[0].price


def test_configured_charge_model_is_recorded_with_deterministic_provenance() -> None:
    from quantx.execution.charges import PercentageBpsChargeModel

    engine = PaperExecutionEngine(
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        profile=PaperSimulationProfile(
            charge_model=PercentageBpsChargeModel(
                Decimal("10"),
                component_name="simulated_brokerage",
                model_id="test.paper.charges",
                model_version="7",
                provenance=("test_configuration",),
            )
        ),
    )

    receipt = engine.execute(
        _request(),
        snapshot=_snapshot(ask=Decimal("100")),
    )

    assert receipt.fee == Decimal("1")
    assert receipt.charges is not None
    assert receipt.charges.total == Decimal("1")
    assert receipt.charges.currency is None
    assert receipt.charges.components[0].name == "simulated_brokerage"
    assert receipt.charges.components[0].amount == Decimal("1")
    assert receipt.charges.model_id == "test.paper.charges"
    assert receipt.charges.model_version == "7"
    assert receipt.charges.provenance == ("test_configuration",)
    assert "charge_model_id=test.paper.charges" in receipt.assumptions
    assert "charge_model_version=7" in receipt.assumptions
    assert "test_configuration" in receipt.assumptions
    assert "charge_total=1" in receipt.assumptions


def test_fee_bps_is_kept_decimal_only_and_rejects_float() -> None:
    with pytest.raises(TypeError, match="fee_bps must be a Decimal"):
        PaperSimulationProfile(fee_bps=0.1)  # type: ignore[arg-type]


def test_charge_model_and_fee_bps_cannot_be_ambiguous() -> None:
    from quantx.execution.charges import PercentageBpsChargeModel

    with pytest.raises(ValueError, match="cannot be combined"):
        PaperSimulationProfile(
            fee_bps=Decimal("10"),
            charge_model=PercentageBpsChargeModel(Decimal("5")),
        )


def test_zero_slippage_records_reference_and_realized_price() -> None:
    engine = PaperExecutionEngine(clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)))
    receipt = engine.execute(_request(), snapshot=_snapshot(bid=Decimal("99"), ask=Decimal("100")))

    assert receipt.fills[0].price == Decimal("100")
    assert "reference_price=100" in receipt.assumptions
    assert "realized_price=100" in receipt.assumptions
    assert "realized_quantity=10" in receipt.assumptions
    assert "remaining_quantity=0" in receipt.assumptions

