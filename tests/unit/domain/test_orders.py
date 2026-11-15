from uuid import UUID, uuid4

import pytest

from quantx.domain.enums import TimeInForce
from quantx.domain.orders import Order


def _minimal_order(**kwargs: object) -> Order:
    from decimal import Decimal

    from quantx.domain.enums import OrderSide, OrderType
    from quantx.domain.value_objects import InstrumentId

    defaults: dict[str, object] = {
        "instrument": InstrumentId("NSE", "TCS"),
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": Decimal("1"),
    }
    defaults.update(kwargs)
    return Order(**defaults)  # type: ignore[arg-type]


def test_default_client_order_id_is_uuid() -> None:
    order = _minimal_order()
    assert type(order.client_order_id) is UUID


def test_explicit_uuid_accepted() -> None:
    value = uuid4()
    order = _minimal_order(client_order_id=value)
    assert order.client_order_id == value
    assert type(order.client_order_id) is UUID


def test_uuid_string_rejected() -> None:
    with pytest.raises(ValueError, match="client_order_id must be a UUID"):
        _minimal_order(client_order_id=str(uuid4()))


def test_none_rejected() -> None:
    with pytest.raises(ValueError, match="client_order_id must be a UUID"):
        _minimal_order(client_order_id=None)


def test_int_rejected() -> None:
    with pytest.raises(ValueError, match="client_order_id must be a UUID"):
        _minimal_order(client_order_id=7)


def test_uuid_subclass_rejected() -> None:
    class SubUUID(UUID):
        pass

    with pytest.raises(ValueError, match="client_order_id must be a UUID"):
        _minimal_order(client_order_id=SubUUID(str(uuid4())))


def test_no_coercion() -> None:
    value = str(uuid4())
    with pytest.raises(ValueError):
        _minimal_order(client_order_id=value)



def test_order_preserves_legacy_day_time_in_force_default() -> None:
    assert _minimal_order().time_in_force is TimeInForce.DAY


def test_order_accepts_explicit_absent_time_in_force() -> None:
    assert _minimal_order(time_in_force=None).time_in_force is None


def test_order_rejects_non_enum_time_in_force() -> None:
    with pytest.raises(ValueError, match="TimeInForce or None"):
        _minimal_order(time_in_force="GTC")
