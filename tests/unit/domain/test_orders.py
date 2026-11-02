from dataclasses import replace
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from quantx.domain.enums import OrderSide, OrderType
from quantx.domain.instruments import InstrumentId
from quantx.domain.orders import Order


class _UUIDSubclass(UUID):
    pass


def _order(**kwargs) -> Order:
    return Order(
        instrument=InstrumentId("NSE", "TCS"),
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        **kwargs,
    )


def test_order_accepts_exact_uuid_client_order_id() -> None:
    client_order_id = uuid4()

    order = _order(client_order_id=client_order_id)

    assert order.client_order_id == client_order_id
    assert type(order.client_order_id) is UUID


def test_order_defaults_client_order_id_to_exact_uuid() -> None:
    order = _order()

    assert type(order.client_order_id) is UUID


@pytest.mark.parametrize(
    "client_order_id",
    [
        pytest.param(str(uuid4()), id="canonical-str"),
        pytest.param(str(uuid4()).upper(), id="uppercase-str"),
        pytest.param(_UUIDSubclass(str(uuid4())), id="uuid-subclass"),
        pytest.param(7, id="int"),
        pytest.param(None, id="none"),
        pytest.param(1.5, id="float"),
    ],
)
def test_order_rejects_non_exact_uuid_client_order_id(client_order_id) -> None:
    with pytest.raises(ValueError, match="client_order_id must be exact UUID"):
        _order(client_order_id=client_order_id)


def test_order_rejects_replacement_with_non_exact_uuid_client_order_id() -> None:
    order = _order()

    with pytest.raises(ValueError, match="client_order_id must be exact UUID"):
        replace(order, client_order_id="opaque-client")
