"""BASIC_BAR fill-model unit coverage.

Candle MARKET orders propose a deterministic fill at the observed bar
close; every other order type or evidence combination yields no proposal
rather than an invented price.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion
from quantx.domain.market_data import Candle
from quantx.domain.orders import Order
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.models import (
    CandleFillModel,
    DataAdaptiveFillModel,
    QuoteFillModel,
    StopTrigger,
)

T0 = datetime(2026, 1, 1, 9, 15, tzinfo=UTC)
TCS = InstrumentId("NSE", "TCS")

PRECISE_CLOSE = Decimal("100.00000000000001")


def _context() -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        broker_connection_id=BrokerConnectionId("paper-1"),
        execution_mode=ExecutionMode.PAPER,
    )


def _candle() -> Candle:
    return Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("100.100000000000000001"),
        high=Decimal("101.00000000000001"),
        low=Decimal("99.09799999999999999"),
        close=PRECISE_CLOSE,
        volume=Decimal("123456789.123456789"),
    )


def _quote() -> MarketSnapshot:
    return MarketSnapshot(
        instrument=TCS,
        timestamp=T0,
        bid=Decimal("99"),
        ask=Decimal("100"),
        last=Decimal("100"),
    )


def _request(
    side: OrderSide,
    kind: OrderType = OrderType.MARKET,
    *,
    limit: Decimal | None = None,
    stop: Decimal | None = None,
) -> ApprovedExecutionRequest:
    limit_price = limit
    if limit_price is None and kind in {OrderType.LIMIT, OrderType.STOP_LIMIT}:
        limit_price = Decimal("50")
    stop_price = stop
    if stop_price is None and kind in {OrderType.STOP, OrderType.STOP_LIMIT}:
        stop_price = Decimal("200")
    order = Order(
        instrument=TCS,
        side=side,
        order_type=kind,
        quantity=Decimal("2"),
        limit_price=limit_price,
        stop_price=stop_price,
    )
    return ApprovedExecutionRequest(order, _context(), RiskResult(RiskDecision.APPROVE, "ok"))


def test_candle_market_buy_fills_at_exact_bar_close() -> None:
    proposal = CandleFillModel().propose_fill(_request(OrderSide.BUY), _candle())

    assert proposal is not None
    assert proposal.price == PRECISE_CLOSE
    assert str(proposal.price) == "100.00000000000001"
    assert not isinstance(proposal.price, float)
    assert proposal.quantity == Decimal("2")
    assert "BASIC_BAR" in proposal.reason


def test_candle_market_sell_fills_at_exact_bar_close() -> None:
    proposal = CandleFillModel().propose_fill(_request(OrderSide.SELL), _candle())

    assert proposal is not None
    assert proposal.price == PRECISE_CLOSE
    assert "BASIC_BAR" in proposal.reason


def test_candle_uncrossed_limit_and_stops_propose_no_fill() -> None:
    candle = _candle()

    assert CandleFillModel().propose_fill(_request(OrderSide.BUY, OrderType.LIMIT), candle) is None
    assert CandleFillModel().propose_fill(_request(OrderSide.BUY, OrderType.STOP), candle) is None
    assert (
        CandleFillModel().propose_fill(_request(OrderSide.SELL, OrderType.STOP_LIMIT), candle)
        is None
    )


def test_candle_model_does_not_price_quotes() -> None:
    assert CandleFillModel().propose_fill(_request(OrderSide.BUY), _quote()) is None


def test_quote_model_does_not_price_candles() -> None:
    assert QuoteFillModel().propose_fill(_request(OrderSide.BUY), _candle()) is None
    assert QuoteFillModel().propose_fill(_request(OrderSide.SELL), _candle()) is None


def test_quote_model_behavior_unchanged() -> None:
    buy = QuoteFillModel().propose_fill(_request(OrderSide.BUY), _quote())
    sell = QuoteFillModel().propose_fill(_request(OrderSide.SELL), _quote())

    assert buy is not None and buy.price == Decimal("100")
    assert sell is not None and sell.price == Decimal("99")


def test_adaptive_model_routes_by_evidence_type() -> None:
    model = DataAdaptiveFillModel()

    buy = model.propose_fill(_request(OrderSide.BUY), _candle())
    quote_buy = model.propose_fill(_request(OrderSide.BUY), _quote())
    limit = model.propose_fill(_request(OrderSide.BUY, OrderType.LIMIT), _candle())

    assert buy is not None and buy.price == PRECISE_CLOSE
    assert "BASIC_BAR" in buy.reason
    assert quote_buy is not None and quote_buy.price == Decimal("100")
    assert limit is None


def test_adaptive_model_rejects_unknown_snapshots() -> None:
    with pytest.raises(TypeError, match="unsupported market snapshot"):
        DataAdaptiveFillModel().propose_fill(_request(OrderSide.BUY), object())  # type: ignore[arg-type]


def test_candle_proposals_are_deterministic() -> None:
    model = CandleFillModel()
    candle = _candle()
    request = _request(OrderSide.BUY)

    first = model.propose_fill(request, candle)
    second = model.propose_fill(request, candle)

    assert first == second
    assert first is not None and first.price == PRECISE_CLOSE


def test_quote_proposals_carry_quote_model_identity() -> None:
    proposal = QuoteFillModel().propose_fill(_request(OrderSide.BUY), _quote())

    assert proposal is not None
    assert proposal.model_id == "QUOTE"
    assert proposal.model_version == "paper-core-v0.3"


def test_candle_proposals_carry_basic_bar_identity() -> None:
    proposal = CandleFillModel().propose_fill(_request(OrderSide.BUY), _candle())

    assert proposal is not None
    assert proposal.model_id == "BASIC_BAR"
    assert proposal.model_version == "basic-bar-v4"


def test_buy_limit_fills_when_close_at_or_below_limit() -> None:
    exact = CandleFillModel().propose_fill(
        _request(OrderSide.BUY, OrderType.LIMIT, limit=PRECISE_CLOSE), _candle()
    )
    inside = CandleFillModel().propose_fill(
        _request(OrderSide.BUY, OrderType.LIMIT, limit=Decimal("101")),
        _candle(),
    )

    assert exact is not None
    assert exact.price == PRECISE_CLOSE
    assert str(exact.price) == "100.00000000000001"
    assert "close-cross" in exact.reason
    assert inside is not None and inside.price == PRECISE_CLOSE


def test_buy_limit_does_not_fill_when_close_above_limit() -> None:
    request = _request(OrderSide.BUY, OrderType.LIMIT, limit=Decimal("50"))

    assert CandleFillModel().propose_fill(request, _candle()) is None


def test_sell_limit_fills_when_close_at_or_above_limit() -> None:
    candle = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("100"),
        close=Decimal("101.5"),
        volume=Decimal("1000"),
    )
    exact = CandleFillModel().propose_fill(
        _request(OrderSide.SELL, OrderType.LIMIT, limit=Decimal("101.5")), candle
    )
    inside = CandleFillModel().propose_fill(
        _request(OrderSide.SELL, OrderType.LIMIT, limit=Decimal("101")), candle
    )

    assert exact is not None
    assert exact.price == Decimal("101.5")
    assert "close-cross" in exact.reason
    assert inside is not None and inside.price == Decimal("101.5")


def test_sell_limit_does_not_fill_when_close_below_limit() -> None:
    request = _request(OrderSide.SELL, OrderType.LIMIT, limit=Decimal("200"))

    assert CandleFillModel().propose_fill(request, _candle()) is None


def test_intrabar_extremes_never_trigger_limit_fills() -> None:
    spiking = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("100"),
        high=Decimal("10000"),
        low=Decimal("1"),
        close=Decimal("101.5"),
        volume=Decimal("1000"),
    )
    # BUY limit=50: low=1 crosses intrabar, but close=101.5 does not.
    buy = _request(OrderSide.BUY, OrderType.LIMIT, limit=Decimal("50"))
    assert CandleFillModel().propose_fill(buy, spiking) is None
    dipping = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("100"),
        high=Decimal("10000"),
        low=Decimal("1"),
        close=Decimal("99.5"),
        volume=Decimal("1000"),
    )
    # SELL limit=200: high=10000 crosses intrabar, but close=99.5 does not.
    sell = _request(OrderSide.SELL, OrderType.LIMIT, limit=Decimal("200"))
    assert CandleFillModel().propose_fill(sell, dipping) is None


def test_high_low_variation_with_same_close_is_invariant() -> None:
    variant_candle = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("50"),
        high=Decimal("50000"),
        low=Decimal("0.01"),
        close=PRECISE_CLOSE,
        volume=Decimal("1"),
    )
    request = _request(OrderSide.BUY, OrderType.LIMIT, limit=PRECISE_CLOSE)
    base = CandleFillModel().propose_fill(request, _candle())
    variant = CandleFillModel().propose_fill(request, variant_candle)

    assert base is not None and variant is not None
    assert (base.price, base.quantity, base.reason) == (
        variant.price,
        variant.quantity,
        variant.reason,
    )


def test_untriggered_stop_proposes_no_fill() -> None:
    candle = _candle()

    # BUY stop=200 never touched (high=101.000...01); SELL stop=50 never touched.
    assert CandleFillModel().propose_fill(_request(OrderSide.BUY, OrderType.STOP), candle) is None
    sell = _request(OrderSide.SELL, OrderType.STOP, stop=Decimal("50"))
    assert CandleFillModel().propose_fill(sell, candle) is None


def test_classify_buy_stop_trigger_states() -> None:
    untouched = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("90"),
        high=Decimal("95"),
        low=Decimal("89"),
        close=Decimal("92"),
        volume=Decimal("1000"),
    )
    assert (
        CandleFillModel.classify_stop(OrderSide.BUY, Decimal("100"), untouched)
        is StopTrigger.NOT_TRIGGERED
    )
    confirmed = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("99"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=Decimal("101"),
        volume=Decimal("1000"),
    )
    assert (
        CandleFillModel.classify_stop(OrderSide.BUY, Decimal("100"), confirmed)
        is StopTrigger.TRIGGERED
    )
    reversal = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("105"),
        high=Decimal("106"),
        low=Decimal("95"),
        close=Decimal("97"),
        volume=Decimal("1000"),
    )
    assert (
        CandleFillModel.classify_stop(OrderSide.BUY, Decimal("100"), reversal)
        is StopTrigger.AMBIGUOUS
    )


def test_classify_sell_stop_trigger_states() -> None:
    untouched = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("110"),
        high=Decimal("112"),
        low=Decimal("108"),
        close=Decimal("111"),
        volume=Decimal("1000"),
    )
    assert (
        CandleFillModel.classify_stop(OrderSide.SELL, Decimal("100"), untouched)
        is StopTrigger.NOT_TRIGGERED
    )
    confirmed = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=Decimal("99"),
        volume=Decimal("1000"),
    )
    assert (
        CandleFillModel.classify_stop(OrderSide.SELL, Decimal("100"), confirmed)
        is StopTrigger.TRIGGERED
    )
    reversal = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("95"),
        high=Decimal("105"),
        low=Decimal("94"),
        close=Decimal("103"),
        volume=Decimal("1000"),
    )
    assert (
        CandleFillModel.classify_stop(OrderSide.SELL, Decimal("100"), reversal)
        is StopTrigger.AMBIGUOUS
    )


def test_triggered_buy_stop_fills_at_bar_close() -> None:
    candle = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("99"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=Decimal("101"),
        volume=Decimal("1000"),
    )
    proposal = CandleFillModel().propose_fill(
        _request(OrderSide.BUY, OrderType.STOP, stop=Decimal("100")), candle
    )

    assert proposal is not None
    assert proposal.price == Decimal("101")
    assert "stop" in proposal.reason
    assert (proposal.model_id, proposal.model_version) == ("BASIC_BAR", "basic-bar-v4")


def test_triggered_sell_stop_fills_at_bar_close() -> None:
    candle = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("101"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=Decimal("99"),
        volume=Decimal("1000"),
    )
    proposal = CandleFillModel().propose_fill(
        _request(OrderSide.SELL, OrderType.STOP, stop=Decimal("100")), candle
    )

    assert proposal is not None
    assert proposal.price == Decimal("99")


def test_ambiguous_stop_proposes_no_fill() -> None:
    reversal = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("105"),
        high=Decimal("106"),
        low=Decimal("95"),
        close=Decimal("97"),
        volume=Decimal("1000"),
    )
    assert (
        CandleFillModel().propose_fill(
            _request(OrderSide.BUY, OrderType.STOP, stop=Decimal("100")), reversal
        )
        is None
    )


def test_stop_limit_never_proposes_even_when_triggered() -> None:
    candle = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("99"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=Decimal("101"),
        volume=Decimal("1000"),
    )
    stop_limit = _request(
        OrderSide.BUY, OrderType.STOP_LIMIT, limit=Decimal("102"), stop=Decimal("100")
    )
    assert CandleFillModel().propose_fill(stop_limit, candle) is None


def test_participation_disabled_preserves_behavior() -> None:
    default = CandleFillModel().propose_fill(_request(OrderSide.BUY), _candle())
    explicit = CandleFillModel(volume_participation_rate=None).propose_fill(
        _request(OrderSide.BUY), _candle()
    )

    assert default is not None and explicit is not None
    assert (default.price, default.quantity) == (explicit.price, explicit.quantity)
    assert "participation" not in default.reason


def test_participation_configuration_is_validated() -> None:
    CandleFillModel(volume_participation_rate=Decimal("1"))
    CandleFillModel(volume_participation_rate=Decimal("0.000000000000000001"))

    with pytest.raises(ValueError, match="in \\(0, 1\\]"):
        CandleFillModel(volume_participation_rate=Decimal("0"))
    with pytest.raises(ValueError, match="in \\(0, 1\\]"):
        CandleFillModel(volume_participation_rate=Decimal("-0.5"))
    with pytest.raises(ValueError, match="in \\(0, 1\\]"):
        CandleFillModel(volume_participation_rate=Decimal("1.000000000000000001"))
    with pytest.raises(TypeError, match="must be a Decimal"):
        CandleFillModel(volume_participation_rate=0.1)  # type: ignore[arg-type]


def test_participation_caps_quantity_by_candle_volume() -> None:
    model = CandleFillModel(volume_participation_rate=Decimal("0.10"))
    proposal = model.propose_fill(_request(OrderSide.BUY), _candle())

    assert proposal is not None
    assert proposal.price == PRECISE_CLOSE
    assert proposal.quantity == Decimal("2")
    assert "volume_participation_rate=0.10" in proposal.reason
    assert "candle_volume_cap=12345678.91234567890" in proposal.reason
    assert "cap is modeled, not observed liquidity" in proposal.reason


def test_participation_cap_below_order_quantity_partial() -> None:
    candle = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("99"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=Decimal("100"),
        volume=Decimal("10"),
    )
    model = CandleFillModel(volume_participation_rate=Decimal("0.10"))
    proposal = model.propose_fill(_request(OrderSide.BUY), candle)

    assert proposal is not None
    assert proposal.quantity == Decimal("1.00")
    assert proposal.price == Decimal("100")


def test_participation_cap_exactly_matching_fills_fully() -> None:
    candle = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("99"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=Decimal("100"),
        volume=Decimal("20"),
    )
    model = CandleFillModel(volume_participation_rate=Decimal("0.10"))
    proposal = model.propose_fill(_request(OrderSide.BUY), candle)

    assert proposal is not None
    assert proposal.quantity == Decimal("2")


def test_zero_candle_volume_proposes_no_fill() -> None:
    candle = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("99"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=Decimal("100"),
        volume=Decimal("0"),
    )
    model = CandleFillModel(volume_participation_rate=Decimal("0.10"))

    assert model.propose_fill(_request(OrderSide.BUY), candle) is None


def test_participation_uses_decimal_arithmetic_only() -> None:
    rate = Decimal("0.333333333333333333")
    candle = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("99"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=Decimal("100"),
        volume=Decimal("5"),
    )
    model = CandleFillModel(volume_participation_rate=rate)
    proposal = model.propose_fill(_request(OrderSide.BUY), candle)

    assert proposal is not None
    assert isinstance(proposal.quantity, Decimal)
    assert not isinstance(proposal.quantity, float)
    assert proposal.quantity == Decimal("5") * rate
    assert str(proposal.quantity) == "1.666666666666666665"


def test_participation_does_not_apply_to_quotes() -> None:
    model = CandleFillModel(volume_participation_rate=Decimal("0.000000000000000001"))

    assert model.propose_fill(_request(OrderSide.BUY), _quote()) is None
    quote_fill = QuoteFillModel().propose_fill(_request(OrderSide.BUY), _quote())
    assert quote_fill is not None and quote_fill.quantity == Decimal("2")


def test_participation_applies_to_limit_and_stop_fills() -> None:
    model = CandleFillModel(volume_participation_rate=Decimal("0.10"))
    candle = Candle(
        instrument=TCS,
        timeframe="1m",
        timestamp=T0,
        open=Decimal("99"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=Decimal("100"),
        volume=Decimal("10"),
    )
    limit = model.propose_fill(
        _request(OrderSide.BUY, OrderType.LIMIT, limit=Decimal("100")), candle
    )
    stop = model.propose_fill(_request(OrderSide.BUY, OrderType.STOP, stop=Decimal("100")), candle)

    assert limit is not None and limit.quantity == Decimal("1.00")
    assert "close-cross" in limit.reason
    assert stop is not None and stop.quantity == Decimal("1.00")
    assert "stop" in stop.reason


def test_adaptive_proposals_preserve_per_payload_identity() -> None:
    model = DataAdaptiveFillModel()

    candle = model.propose_fill(_request(OrderSide.BUY), _candle())
    quote = model.propose_fill(_request(OrderSide.BUY), _quote())

    assert candle is not None
    assert (candle.model_id, candle.model_version) == ("BASIC_BAR", "basic-bar-v4")
    assert quote is not None
    assert (quote.model_id, quote.model_version) == ("QUOTE", "paper-core-v0.3")
