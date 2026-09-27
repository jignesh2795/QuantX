from decimal import Decimal

from quantx.plugins.dhan.mapping import dhan_correlation_id
from quantx.plugins.dhan.models import DhanOrderRequest
from quantx.plugins.dhan.transport import DhanTransport, InMemoryDhanTransport


def _request() -> DhanOrderRequest:
    return DhanOrderRequest(
        security_id="1333",
        exchange_segment="NSE_EQ",
        transaction_type="BUY",
        quantity=2,
        order_type="MARKET",
        product_type="CNC",
        price=Decimal("0"),
        trigger_price=Decimal("0"),
        validity="DAY",
        correlation_id=dhan_correlation_id("client-order-1"),
    )


def test_in_memory_transport_is_runtime_usable_as_transport() -> None:
    transport = InMemoryDhanTransport()

    assert isinstance(transport, DhanTransport)


def test_in_memory_transport_records_submission_and_returns_response() -> None:
    transport = InMemoryDhanTransport(response_status="PENDING")
    response = transport.submit(_request())

    assert response.order_id == "dhan-test-order"
    assert response.order_status == "PENDING"
    assert len(transport.submitted) == 1
    assert transport.submitted[0].security_id == "1333"


def test_in_memory_transport_supports_cancel_and_reconcile() -> None:
    transport = InMemoryDhanTransport(
        response_status="TRADED",
        filled_quantity=Decimal("2"),
        average_traded_price=Decimal("101.25"),
    )
    correlation_id = dhan_correlation_id("client-order-1")

    cancel = transport.cancel(correlation_id)
    detail = transport.reconcile(correlation_id)

    assert cancel.order_status == "CANCELLED"
    assert transport.cancelled == (correlation_id,)
    assert detail.order_status == "TRADED"
    assert detail.filled_quantity == Decimal("2")
    assert detail.average_traded_price == Decimal("101.25")


def test_transport_helpers_unwrap_success_and_failure_envelopes() -> None:
    from quantx.plugins.dhan.transport import _order_detail, _order_response

    success = {
        "status": "success",
        "remarks": "",
        "data": {
            "orderId": "123",
            "orderStatus": "PENDING",
        },
    }
    failure = {
        "status": "failure",
        "remarks": "invalid access token",
        "data": "",
    }
    order = _order_response(success)
    failed = _order_response(failure)

    assert order.order_id == "123"
    assert order.order_status == "PENDING"
    assert failed.order_status == "UNKNOWN"
    assert "invalid access token" in failed.message

    detail = _order_detail(
        {
            "status": "success",
            "remarks": "",
            "data": {
                "orderId": "123",
                "correlationId": "abc",
                "orderStatus": "TRADED",
                "averageTradedPrice": 101.25,
                "filledQty": 2,
                "exchangeTime": "2026-01-01 10:00:00",
                "updateTime": "2026-01-01 10:00:01",
            },
        }
    )
    assert detail.order_id == "123"
    assert detail.correlation_id == "abc"
    assert detail.filled_quantity == Decimal("2")
    assert detail.average_traded_price == Decimal("101.25")


def test_transport_helpers_fail_closed_on_malformed_success_data() -> None:
    from quantx.plugins.dhan.transport import _order_response

    response = _order_response(
        {
            "status": "success",
            "remarks": "",
            "data": ["not", "a", "mapping"],
        }
    )

    assert response.order_status == "UNKNOWN"
