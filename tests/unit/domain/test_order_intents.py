from decimal import Decimal

import pytest

from quantx.domain.enums import OrderSide, OrderType, TimeInForce
from quantx.domain.execution_request import build_order_from_intent
from quantx.domain.order_intents import TradeIntent
from quantx.domain.value_objects import InstrumentId


def _intent(**overrides: object) -> TradeIntent:
    values: dict[str, object] = {
        "instrument": InstrumentId("GLOBAL", "BTCUSDT"),
        "side": OrderSide.BUY,
        "quantity": Decimal("0.1"),
        "order_type": OrderType.MARKET,
    }
    values.update(overrides)
    return TradeIntent(**values)  # type: ignore[arg-type]


def test_trade_intent_preserves_legacy_day_time_in_force_default() -> None:
    assert _intent().time_in_force is TimeInForce.DAY


def test_trade_intent_accepts_absent_time_in_force_and_order_builder_preserves_it() -> None:
    intent = _intent(time_in_force=None)
    assert intent.time_in_force is None
    assert build_order_from_intent(intent).time_in_force is None


def test_trade_intent_rejects_non_enum_time_in_force() -> None:
    with pytest.raises(ValueError, match="TimeInForce or None"):
        _intent(time_in_force="GTC")
