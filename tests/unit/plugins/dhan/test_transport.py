import threading
import time
import types
from decimal import Decimal

import pytest

from quantx.plugins.dhan.mapping import dhan_correlation_id
from quantx.plugins.dhan.models import DhanCredentials, DhanOrderRequest
from quantx.plugins.dhan.transport import (
    DhanSDKTransport,
    DhanTimeoutError,
    DhanTransport,
    InMemoryDhanTransport,
)


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


class _HungFakeDhanClient:
    """Fake SDK client whose order submission blocks until released."""

    def __init__(self, started: threading.Event, release: threading.Event) -> None:
        self._started = started
        self._release = release
        self.place_order_calls = 0

    def place_order(self, **kwargs: object) -> object:
        self.place_order_calls += 1
        self._started.set()
        assert self._release.wait(timeout=30)
        return {
            "status": "success",
            "remarks": "",
            "data": {"orderId": "late-order", "orderStatus": "PENDING"},
        }

    def get_order_by_correlationID(self, correlation_id: str) -> object:  # noqa: N802
        return {
            "status": "success",
            "remarks": "",
            "data": {
                "orderId": "late-order",
                "correlationId": correlation_id,
                "orderStatus": "PENDING",
                "averageTradedPrice": 0,
                "filledQty": 0,
                "exchangeTime": "2026-01-01 10:00:00",
                "updateTime": "2026-01-01 10:00:00",
            },
        }

    def get_fund_limits(self) -> object:
        return {"status": "success", "remarks": "", "data": {}}

    def get_positions(self) -> object:
        return {"status": "success", "remarks": "", "data": []}

    def cancel_order(self, order_id: str) -> object:
        return {
            "status": "success",
            "remarks": "",
            "data": {"orderId": order_id, "orderStatus": "CANCELLED"},
        }


class _HungFundsFakeDhanClient(_HungFakeDhanClient):
    """Fake SDK client whose fund-limits read blocks until released."""

    def get_fund_limits(self) -> object:
        assert self._release.wait(timeout=30)
        return {"status": "success", "remarks": "", "data": {}}


def _sdk_transport_without_sdk(monkeypatch: pytest.MonkeyPatch, client: object) -> DhanSDKTransport:
    """Build the real SDK transport with a fake client and no dhanhq installed."""
    import sys

    def _context(client_id: str, access_token: str) -> object:
        return object()

    def _client(context: object) -> object:
        return client

    fake_module = types.ModuleType("dhanhq")
    fake_module.DhanContext = _context  # type: ignore[attr-defined]
    fake_module.dhanhq = _client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dhanhq", fake_module)
    return DhanSDKTransport(
        credentials=DhanCredentials(client_id="test-id", access_token="test-token")
    )


def _run_submit_in_background(
    transport: DhanSDKTransport,
    *,
    timeout: float = 0.2,
) -> tuple[threading.Thread, list[BaseException]]:
    """Run one submit on a helper thread and capture its terminal exception."""
    errors: list[BaseException] = []

    def _submit() -> None:
        try:
            transport.submit(_request(), timeout=timeout)
        except BaseException as exc:  # noqa: BLE001 - recorded for assertion
            errors.append(exc)

    worker = threading.Thread(target=_submit, daemon=True)
    worker.start()
    return worker, errors


def test_reconcile_proceeds_while_submit_hung(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hung submission must not block the recovery reconcile behind it."""
    started = threading.Event()
    release = threading.Event()
    transport = _sdk_transport_without_sdk(monkeypatch, _HungFakeDhanClient(started, release))
    worker, errors = _run_submit_in_background(transport)
    try:
        assert started.wait(timeout=10)
        detail = transport.reconcile("cid-1", timeout=5.0)
        assert detail.order_id == "late-order"
        assert detail.order_status == "PENDING"
    finally:
        release.set()
        worker.join(timeout=10)
        transport.close()

    # The hung submission resolves cleanly once released; nothing was lost.
    assert errors == []
    assert not worker.is_alive()


def test_second_submit_stays_queued_behind_hung_submit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Submissions stay serialized: a second submit never overtakes a hung one."""
    started = threading.Event()
    release = threading.Event()
    client = _HungFakeDhanClient(started, release)
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    # A long worker timeout keeps this deterministic: only the main-thread
    # second submit may expire while queued behind the hung first submit.
    worker, errors = _run_submit_in_background(transport, timeout=30.0)
    try:
        assert started.wait(timeout=10)
        with pytest.raises(DhanTimeoutError, match="submit"):
            transport.submit(_request(), timeout=0.2)
        assert client.place_order_calls == 1
    finally:
        release.set()
        worker.join(timeout=10)
        transport.close()

    # The first submission resolves cleanly once released; it never ran twice.
    assert errors == []
    assert not worker.is_alive()


def test_hung_submit_times_out_for_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    """A submission hung past its own timeout raises without hanging the caller."""
    release = threading.Event()
    transport = _sdk_transport_without_sdk(
        monkeypatch, _HungFakeDhanClient(threading.Event(), release)
    )
    try:
        with pytest.raises(DhanTimeoutError, match="submit"):
            transport.submit(_request(), timeout=0.1)
    finally:
        release.set()
        transport.close()


def test_read_calls_time_out_without_hanging_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hung fund-limits read fails closed within its timeout bound."""
    release = threading.Event()
    transport = _sdk_transport_without_sdk(
        monkeypatch, _HungFundsFakeDhanClient(threading.Event(), release)
    )
    try:
        started = time.monotonic()
        funds = transport.fund_limits(timeout=0.2)
        elapsed = time.monotonic() - started
        assert funds.available is False
        assert elapsed < 5.0
        assert transport.health(timeout=0.2) is False
    finally:
        release.set()
        transport.close()
