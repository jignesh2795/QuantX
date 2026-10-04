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
    response = transport.submit(_request(), timeout=5.0)

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

    cancel = transport.cancel(correlation_id, timeout=5.0)
    detail = transport.reconcile(correlation_id, timeout=5.0)

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


def test_fund_limits_success_parses_documented_spelling() -> None:
    from quantx.plugins.dhan.transport import _funds_snapshot

    snapshot = _funds_snapshot(
        {
            "status": "success",
            "remarks": "",
            "data": {"availabelBalance": 5000.0, "utilizedAmount": "1200.50"},
        }
    )

    assert snapshot.available is True
    assert snapshot.available_balance == Decimal("5000")
    assert snapshot.utilized_amount == Decimal("1200.50")


def test_fund_limits_tolerates_alternate_balance_spelling() -> None:
    from quantx.plugins.dhan.transport import _funds_snapshot

    snapshot = _funds_snapshot(
        {
            "status": "success",
            "remarks": "",
            "data": {"availableBalance": "250", "utilizedAmount": 0},
        }
    )

    assert snapshot.available is True
    assert snapshot.available_balance == Decimal("250")


def test_fund_limits_failure_remains_unavailable() -> None:
    from quantx.plugins.dhan.transport import _funds_snapshot

    snapshot = _funds_snapshot({"status": "failure", "remarks": "invalid access token", "data": ""})

    assert snapshot.available is False
    assert snapshot.available_balance is None
    assert snapshot.utilized_amount is None


def test_fund_limits_success_without_usable_fields_is_unavailable() -> None:
    from quantx.plugins.dhan.transport import _funds_snapshot

    snapshot = _funds_snapshot({"status": "success", "remarks": "", "data": {}})

    assert snapshot.available is False
    assert snapshot.available_balance is None


def test_positions_success_parses_multiple_positions() -> None:
    from quantx.plugins.dhan.transport import _positions_snapshot

    snapshot = _positions_snapshot(
        {
            "status": "success",
            "remarks": "",
            "data": [
                {
                    "securityId": "1333",
                    "exchangeSegment": "NSE_EQ",
                    "netQty": 10,
                    "costPrice": "100.50",
                },
                {
                    "securityId": "11915",
                    "exchangeSegment": "NSE_FNO",
                    "netQty": -5,
                    "costPrice": 200,
                },
            ],
        }
    )

    assert snapshot.available is True
    assert len(snapshot.positions) == 2
    assert snapshot.positions[0].security_id == "1333"
    assert snapshot.positions[0].net_quantity == Decimal("10")
    assert snapshot.positions[0].average_price == Decimal("100.50")
    assert snapshot.positions[1].net_quantity == Decimal("-5")


def test_malformed_position_data_becomes_unavailable() -> None:
    from quantx.plugins.dhan.transport import _positions_snapshot

    snapshot = _positions_snapshot(
        {
            "status": "success",
            "remarks": "",
            "data": [{"securityId": "1333", "exchangeSegment": "NSE_EQ"}],
        }
    )

    assert snapshot.available is False
    assert snapshot.positions == ()


def test_in_memory_transport_returns_configured_fund_and_position_observations() -> None:
    from quantx.plugins.dhan.models import DhanPositionSnapshot

    transport = InMemoryDhanTransport(
        funds_available_balance=Decimal("5000"),
        funds_utilized_amount=Decimal("1200"),
        position_snapshots=(DhanPositionSnapshot("1333", "NSE_EQ", Decimal("10"), Decimal("100")),),
    )

    funds = transport.fund_limits()
    positions = transport.positions()

    assert funds.available is True
    assert funds.available_balance == Decimal("5000")
    assert funds.utilized_amount == Decimal("1200")
    assert positions.available is True
    assert len(positions.positions) == 1
    assert positions.positions[0].security_id == "1333"
