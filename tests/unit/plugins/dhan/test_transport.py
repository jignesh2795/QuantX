import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, tzinfo
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from quantx.plugins.dhan.mapping import dhan_correlation_id
from quantx.plugins.dhan.models import DhanCredentials, DhanOrderRequest
from quantx.plugins.dhan.transport import (
    DhanAuthenticationRejectedError,
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

    auth_failure = {
        "status": "failure",
        "remarks": {
            "error_code": "DH-901",
            "error_type": "Invalid Authentication",
            "error_message": "token is invalid or expired",
        },
        "data": "",
    }
    with pytest.raises(DhanAuthenticationRejectedError, match="DH-901"):
        _order_response(auth_failure)
    with pytest.raises(DhanAuthenticationRejectedError, match="DH-901"):
        _order_detail(auth_failure)
    with pytest.raises(DhanAuthenticationRejectedError) as cancel_error:
        _order_response(auth_failure, operation="cancel")
    assert cancel_error.value.operation == "cancel"
    assert "during cancel" in str(cancel_error.value)

    # Free text is never promoted to typed authentication evidence.
    text_only_auth_hint = {
        "status": "failure",
        "remarks": "request failed with DH-901 somewhere in the text",
        "data": "",
    }
    text_only_failure = _order_response(text_only_auth_hint)
    assert text_only_failure.order_status == "UNKNOWN"

    # DH-904 is a rate-limit outcome, not an authentication failure.
    rate_limit_failure = {
        "status": "failure",
        "remarks": {
            "error_code": "DH-904",
            "error_type": "Rate Limit Exceeded",
            "error_message": "rate limit exceeded",
        },
        "data": "",
    }
    rate_limited = _order_response(rate_limit_failure)
    assert rate_limited.order_status == "UNKNOWN"
    assert "DH-904" in rate_limited.message

    # DH-902 is an unrecognized authentication code and must stay UNKNOWN.
    unrecognized_auth_failure = {
        "status": "failure",
        "remarks": {
            "error_code": "DH-902",
            "error_type": "Authentication Error",
            "error_message": "unrecognized authentication failure",
        },
        "data": "",
    }
    unrecognized_auth = _order_response(unrecognized_auth_failure)
    assert unrecognized_auth.order_status == "UNKNOWN"
    assert "DH-902" in unrecognized_auth.message

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
        credentials=DhanCredentials(
            client_id="test-id",
            access_token="test-token",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
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


class _CountingHungFundsClient:
    """Fake SDK client counting fund-limits entries; reads block until released."""

    def __init__(self, entered: threading.Event, release: threading.Event, count: int) -> None:
        self._entered = entered
        self._release = release
        self._count = count
        self._seen = 0
        self._lock = threading.Lock()

    def get_fund_limits(self) -> object:
        with self._lock:
            self._seen += 1
            if self._seen >= self._count:
                self._entered.set()
        assert self._release.wait(timeout=30)
        return {"status": "success", "remarks": "", "data": {}}

    def get_order_by_correlationID(self, correlation_id: str) -> object:  # noqa: N802
        return {
            "status": "success",
            "remarks": "",
            "data": {
                "orderId": "reconciled-order",
                "correlationId": correlation_id,
                "orderStatus": "TRADED",
                "averageTradedPrice": 0,
                "filledQty": 0,
                "exchangeTime": "2026-01-01 10:00:00",
                "updateTime": "2026-01-01 10:00:00",
            },
        }

    def get_positions(self) -> object:
        return {"status": "success", "remarks": "", "data": []}

    def place_order(self, **kwargs: object) -> object:
        raise AssertionError("no submission is expected in this test")

    def cancel_order(self, order_id: str) -> object:
        raise AssertionError("no cancellation is expected in this test")


def test_reconcile_proceeds_while_query_lane_saturated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A saturated read lane must not starve the recovery reconcile."""
    entered = threading.Event()
    release = threading.Event()
    transport = _sdk_transport_without_sdk(
        monkeypatch, _CountingHungFundsClient(entered, release, 4)
    )
    readers: list[threading.Thread] = []
    try:
        for _ in range(4):
            reader = threading.Thread(
                target=transport.fund_limits, kwargs={"timeout": 30.0}, daemon=True
            )
            reader.start()
            readers.append(reader)
        assert entered.wait(timeout=10)
        detail = transport.reconcile("cid-1", timeout=5.0)
        assert detail.order_id == "reconciled-order"
        assert detail.order_status == "TRADED"
    finally:
        release.set()
        for reader in readers:
            reader.join(timeout=10)
        transport.close()

    assert all(not reader.is_alive() for reader in readers)


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


class _CancelEchoFakeDhanClient:
    """Fake SDK client whose reconciliation detail carries a configurable echo."""

    def __init__(self, correlation_echo: str | None) -> None:
        self._correlation_echo = correlation_echo
        self.cancel_calls: list[str] = []

    def get_order_by_correlationID(self, correlation_id: str) -> object:  # noqa: N802
        payload: dict[str, object] = {
            "orderId": "resolved-order",
            "orderStatus": "PENDING",
        }
        if self._correlation_echo is not None:
            payload["correlationId"] = self._correlation_echo
        return {"status": "success", "remarks": "", "data": payload}

    def cancel_order(self, order_id: str) -> object:
        self.cancel_calls.append(order_id)
        return {
            "status": "success",
            "remarks": "",
            "data": {"orderId": order_id, "orderStatus": "CANCELLED"},
        }

    def get_fund_limits(self) -> object:
        return {"status": "success", "remarks": "", "data": {}}

    def get_positions(self) -> object:
        return {"status": "success", "remarks": "", "data": []}

    def place_order(self, **kwargs: object) -> object:
        raise AssertionError("no submission is expected in this test")


def test_sdk_cancel_proceeds_when_correlation_echo_confirms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A confirming correlation echo binds the resolution and permits the cancel."""
    client = _CancelEchoFakeDhanClient(correlation_echo="requested-correlation")
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        response = transport.cancel("requested-correlation", timeout=5.0)
        assert response.order_status == "CANCELLED"
        assert client.cancel_calls == ["resolved-order"]
    finally:
        transport.close()


def test_sdk_cancel_refuses_mismatched_correlation_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mismatched echo means the resolved order is not bindable; never cancel it."""
    client = _CancelEchoFakeDhanClient(correlation_echo="different-correlation")
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        response = transport.cancel("requested-correlation", timeout=5.0)
        assert response.order_status == "UNKNOWN"
        assert response.order_id is None
        assert client.cancel_calls == []
    finally:
        transport.close()


def test_sdk_cancel_refuses_absent_correlation_echo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing echo evidence must not silently become a definitive cancellation."""
    client = _CancelEchoFakeDhanClient(correlation_echo=None)
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        response = transport.cancel("requested-correlation", timeout=5.0)
        assert response.order_status == "UNKNOWN"
        assert response.order_id is None
        assert client.cancel_calls == []
    finally:
        transport.close()


# Profile, extended fund/position fields, and holdings normalization.


def test_profile_snapshot_parses_the_authenticated_client_id() -> None:
    from quantx.plugins.dhan.transport import _profile_snapshot

    snapshot = _profile_snapshot(
        {
            "status": "success",
            "remarks": "",
            "data": {"dhanClientId": "  client-1  "},
        }
    )

    assert snapshot.available is True
    assert snapshot.client_id == "client-1"


def test_profile_snapshot_accepts_a_raw_profile_payload() -> None:
    from quantx.plugins.dhan.transport import _profile_snapshot

    snapshot = _profile_snapshot({"dhanClientId": "client-1"})

    assert snapshot.available is True
    assert snapshot.client_id == "client-1"


@pytest.mark.parametrize(
    "response",
    [
        {"status": "failure", "remarks": "invalid access token", "data": ""},
        {"status": "success", "remarks": "", "data": {}},
        {"status": "success", "remarks": "", "data": []},
        ["not", "a", "mapping"],
    ],
)
def test_profile_snapshot_fails_closed_without_identity(response) -> None:
    from quantx.plugins.dhan.transport import _profile_snapshot

    snapshot = _profile_snapshot(response)

    assert snapshot.available is False
    assert snapshot.client_id is None


def test_fund_limits_parse_every_required_financial_field() -> None:
    from quantx.plugins.dhan.transport import _funds_snapshot

    snapshot = _funds_snapshot(
        {
            "status": "success",
            "remarks": "",
            "data": {
                "dhanClientId": "client-1",
                "sodLimit": "10000.25",
                "availabelBalance": "5000.50",
                "collateralAmount": "100",
                "receiveableAmount": "50",
                "utilizedAmount": "1200",
                "blockedPayoutAmount": "0",
                "withdrawableBalance": "4800",
            },
        }
    )

    assert snapshot.available is True
    assert snapshot.client_id == "client-1"
    assert snapshot.sod_limit == Decimal("10000.25")
    assert snapshot.available_balance == Decimal("5000.50")
    assert snapshot.collateral_amount == Decimal("100")
    assert snapshot.receivable_amount == Decimal("50")
    assert snapshot.utilized_amount == Decimal("1200")
    assert snapshot.blocked_payout_amount == Decimal("0")
    assert snapshot.withdrawable_balance == Decimal("4800")


def test_fund_limits_preserve_missing_fields_as_unknown() -> None:
    from quantx.plugins.dhan.transport import _funds_snapshot

    snapshot = _funds_snapshot(
        {
            "status": "success",
            "remarks": "",
            "data": {"availabelBalance": "5000"},
        }
    )

    assert snapshot.available is True
    assert snapshot.available_balance == Decimal("5000")
    assert snapshot.sod_limit is None
    assert snapshot.collateral_amount is None
    assert snapshot.receivable_amount is None
    assert snapshot.blocked_payout_amount is None
    assert snapshot.withdrawable_balance is None


def test_fund_limits_invalid_decimal_is_unavailable() -> None:
    from quantx.plugins.dhan.transport import _funds_snapshot

    snapshot = _funds_snapshot(
        {
            "status": "success",
            "remarks": "",
            "data": {"availabelBalance": "5000", "sodLimit": "not-a-number"},
        }
    )

    assert snapshot.available is False
    assert snapshot.available_balance is None


def test_positions_parse_identity_product_quantity_and_pnl_fields() -> None:
    from quantx.plugins.dhan.transport import _positions_snapshot

    snapshot = _positions_snapshot(
        {
            "status": "success",
            "remarks": "",
            "data": [
                {
                    "dhanClientId": "client-1",
                    "securityId": "1333",
                    "exchangeSegment": "NSE_EQ",
                    "productType": "CNC",
                    "positionType": "LONG",
                    "buyQty": 10,
                    "sellQty": 0,
                    "netQty": 10,
                    "costPrice": "100.50",
                    "realizedProfit": "25",
                    "unrealizedProfit": "-5",
                    "multiplier": 2,
                }
            ],
        }
    )

    assert snapshot.available is True
    position = snapshot.positions[0]
    assert position.client_id == "client-1"
    assert position.product_type == "CNC"
    assert position.position_type == "LONG"
    assert position.buy_quantity == Decimal("10")
    assert position.sell_quantity == Decimal("0")
    assert position.net_quantity == Decimal("10")
    assert position.average_price == Decimal("100.50")
    assert position.realized_profit == Decimal("25")
    assert position.unrealized_profit == Decimal("-5")
    assert position.multiplier == Decimal("2")


def test_positions_contradictory_quantities_make_the_book_unavailable() -> None:
    from quantx.plugins.dhan.transport import _positions_snapshot

    snapshot = _positions_snapshot(
        {
            "status": "success",
            "remarks": "",
            "data": [
                {
                    "securityId": "1333",
                    "exchangeSegment": "NSE_EQ",
                    "buyQty": 10,
                    "sellQty": 0,
                    "netQty": 5,
                }
            ],
        }
    )

    assert snapshot.available is False
    assert snapshot.positions == ()


def test_holdings_parse_quantities_and_available_cost_basis() -> None:
    from quantx.plugins.dhan.transport import _holdings_snapshot

    snapshot = _holdings_snapshot(
        {
            "status": "success",
            "remarks": "",
            "data": [
                {
                    "exchange": "ALL",
                    "securityId": "1333",
                    "totalQty": 10,
                    "dpQty": 7,
                    "t1Qty": 3,
                    "availableQty": 8,
                    "collateralQty": 2,
                    "avgCostPrice": "100.25",
                }
            ],
        }
    )

    assert snapshot.available is True
    holding = snapshot.holdings[0]
    assert holding.security_id == "1333"
    assert holding.exchange == "ALL"
    assert holding.total_quantity == Decimal("10")
    assert holding.dp_quantity == Decimal("7")
    assert holding.t1_quantity == Decimal("3")
    assert holding.available_quantity == Decimal("8")
    assert holding.collateral_quantity == Decimal("2")
    assert holding.average_cost_price == Decimal("100.25")


@pytest.mark.parametrize(
    "data",
    [
        [{"exchange": "ALL", "securityId": "1333"}],
        [{"exchange": "ALL", "securityId": "1333", "totalQty": 10, "dpQty": 7, "t1Qty": 4}],
        [{"exchange": "ALL", "securityId": "1333", "totalQty": -1}],
        ["not", "a", "mapping"],
    ],
    ids=["missing-total", "contradictory-split", "negative-total", "malformed-entry"],
)
def test_holdings_malformed_entries_make_the_book_unavailable(data) -> None:
    from quantx.plugins.dhan.transport import _holdings_snapshot

    snapshot = _holdings_snapshot({"status": "success", "remarks": "", "data": data})

    assert snapshot.available is False
    assert snapshot.holdings == ()


def test_holdings_non_list_data_is_unavailable() -> None:
    from quantx.plugins.dhan.transport import _holdings_snapshot

    snapshot = _holdings_snapshot({"status": "success", "remarks": "", "data": {}})

    assert snapshot.available is False
    assert snapshot.holdings == ()


def test_in_memory_transport_returns_configured_profile_and_holdings() -> None:
    from quantx.plugins.dhan.models import DhanHoldingSnapshot

    transport = InMemoryDhanTransport(
        profile_client_id="client-1",
        holding_snapshots=(
            DhanHoldingSnapshot(
                "1333",
                "ALL",
                Decimal("5"),
                average_cost_price=Decimal("100"),
            ),
        ),
    )

    profile = transport.profile()
    holdings = transport.holdings()

    assert profile.available is True
    assert profile.client_id == "client-1"
    assert holdings.available is True
    assert holdings.holdings[0].security_id == "1333"


def test_in_memory_transport_profile_and_holdings_default_to_no_identity_or_rows() -> None:
    transport = InMemoryDhanTransport()

    profile = transport.profile()
    holdings = transport.holdings()

    assert profile.available is True
    assert profile.client_id is None
    assert holdings.available is True
    assert holdings.holdings == ()


class _ProfileLogin:
    def __init__(self, response: object) -> None:
        self._response = response
        self.tokens: list[str] = []

    def user_profile(self, access_token: str) -> object:
        self.tokens.append(access_token)
        return self._response


class _ProfileContext:
    def __init__(self, login: object) -> None:
        self._login = login

    def get_dhan_login(self) -> object:
        return self._login


class _RaisingProfileLogin:
    def user_profile(self, access_token: str) -> object:
        raise RuntimeError("profile endpoint failure")


class _HoldingsFakeDhanClient(_CancelEchoFakeDhanClient):
    def __init__(self, response: object) -> None:
        super().__init__(correlation_echo=None)
        self._holdings_response = response

    def get_holdings(self) -> object:
        return self._holdings_response


def _sdk_transport_with_context(
    monkeypatch: pytest.MonkeyPatch,
    client: object,
    context: object,
) -> DhanSDKTransport:
    """Build the real SDK transport with a fake SDK module and context."""
    import sys

    def _context(client_id: str, access_token: str) -> object:
        return context

    def _client(context: object) -> object:
        return client

    fake_module = types.ModuleType("dhanhq")
    fake_module.DhanContext = _context  # type: ignore[attr-defined]
    fake_module.dhanhq = _client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dhanhq", fake_module)
    return DhanSDKTransport(
        credentials=DhanCredentials(
            client_id="test-id",
            access_token="test-token",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
    )


def test_sdk_profile_reads_through_the_authenticated_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login = _ProfileLogin({"dhanClientId": "client-1"})
    transport = _sdk_transport_with_context(
        monkeypatch,
        _CancelEchoFakeDhanClient(correlation_echo=None),
        _ProfileContext(login),
    )
    try:
        profile = transport.profile(timeout=5.0)

        assert profile.available is True
        assert profile.client_id == "client-1"
        assert login.tokens == ["test-token"]
    finally:
        transport.close()


def test_sdk_profile_without_login_capability_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _sdk_transport_with_context(
        monkeypatch,
        _CancelEchoFakeDhanClient(correlation_echo=None),
        object(),
    )
    try:
        profile = transport.profile(timeout=5.0)

        assert profile.available is False
        assert profile.client_id is None
    finally:
        transport.close()


def test_sdk_profile_transport_failure_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _sdk_transport_with_context(
        monkeypatch,
        _CancelEchoFakeDhanClient(correlation_echo=None),
        _ProfileContext(_RaisingProfileLogin()),
    )
    try:
        profile = transport.profile(timeout=5.0)

        assert profile.available is False
        assert profile.client_id is None
        assert "profile endpoint failure" in profile.message
    finally:
        transport.close()


def test_sdk_holdings_reads_through_the_authenticated_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _HoldingsFakeDhanClient(
        {
            "status": "success",
            "remarks": "",
            "data": [
                {
                    "exchange": "ALL",
                    "securityId": "1333",
                    "totalQty": 5,
                    "dpQty": 5,
                    "t1Qty": 0,
                    "availableQty": 5,
                    "collateralQty": 0,
                    "avgCostPrice": "100",
                }
            ],
        }
    )
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        holdings = transport.holdings(timeout=5.0)

        assert holdings.available is True
        assert holdings.holdings[0].security_id == "1333"
        assert holdings.holdings[0].average_cost_price == Decimal("100")
    finally:
        transport.close()


def test_sdk_holdings_without_vendor_method_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _sdk_transport_without_sdk(
        monkeypatch,
        _CancelEchoFakeDhanClient(correlation_echo=None),
    )
    try:
        holdings = transport.holdings(timeout=5.0)

        assert holdings.available is False
        assert holdings.holdings == ()
    finally:
        transport.close()


def test_sdk_transport_partial_executor_initialization_shuts_down_prior_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    def _context(client_id: str, access_token: str) -> object:
        return object()

    def _client(context: object) -> object:
        return object()

    fake_module = types.ModuleType("dhanhq")
    fake_module.DhanContext = _context  # type: ignore[attr-defined]
    fake_module.dhanhq = _client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dhanhq", fake_module)

    real_executor = ThreadPoolExecutor
    created: list[object] = []
    shutdowns: list[object] = []

    class FailingExecutor:
        def __init__(self, *args: object, **kwargs: object) -> None:
            if len(created) == 1:
                raise RuntimeError("executor construction failed")
            self._executor = real_executor(*args, **kwargs)
            created.append(self)

        def shutdown(self, *args: object, **kwargs: object) -> None:
            shutdowns.append(self)
            self._executor.shutdown(*args, **kwargs)

    monkeypatch.setattr(
        "quantx.plugins.dhan.transport.ThreadPoolExecutor", FailingExecutor, raising=True
    )

    with pytest.raises(RuntimeError, match="executor construction failed"):
        DhanSDKTransport(
            credentials=DhanCredentials(
                client_id="test-id",
                access_token="test-token",
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )

    assert len(created) == 1
    assert len(shutdowns) == 1
    assert shutdowns[0] is created[0]


def _sdk_transport_partial_executor_setup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    raise_on_index: int,
    raise_exc: BaseException,
    shutdown_raises: BaseException | None = None,
) -> tuple[list[object], list[object]]:
    import sys

    def _context(client_id: str, access_token: str) -> object:
        return object()

    def _client(context: object) -> object:
        return object()

    fake_module = types.ModuleType("dhanhq")
    fake_module.DhanContext = _context  # type: ignore[attr-defined]
    fake_module.dhanhq = _client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dhanhq", fake_module)

    real_executor = ThreadPoolExecutor
    created: list[object] = []
    shutdowns: list[object] = []

    class FailingExecutor:
        def __init__(self, *args: object, **kwargs: object) -> None:
            if len(created) == raise_on_index:
                raise raise_exc
            self._executor = real_executor(*args, **kwargs)
            created.append(self)

        def shutdown(self, *args: object, **kwargs: object) -> None:
            shutdowns.append(self)
            if shutdown_raises is not None:
                raise shutdown_raises
            self._executor.shutdown(*args, **kwargs)

    monkeypatch.setattr(
        "quantx.plugins.dhan.transport.ThreadPoolExecutor", FailingExecutor, raising=True
    )
    return created, shutdowns


def test_sdk_transport_partial_executor_initialization_keyboard_interrupt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, shutdowns = _sdk_transport_partial_executor_setup(
        monkeypatch, raise_on_index=1, raise_exc=KeyboardInterrupt()
    )

    with pytest.raises(KeyboardInterrupt):
        DhanSDKTransport(
            credentials=DhanCredentials(
                client_id="test-id",
                access_token="test-token",
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )

    assert len(created) == 1
    assert len(shutdowns) == 1


def test_sdk_transport_partial_executor_initialization_system_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, shutdowns = _sdk_transport_partial_executor_setup(
        monkeypatch, raise_on_index=1, raise_exc=SystemExit(7)
    )

    with pytest.raises(SystemExit) as exc_info:
        DhanSDKTransport(
            credentials=DhanCredentials(
                client_id="test-id",
                access_token="test-token",
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )

    assert exc_info.value.code == 7
    assert len(created) == 1
    assert len(shutdowns) == 1


def test_sdk_transport_partial_executor_initialization_third_executor_interrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, shutdowns = _sdk_transport_partial_executor_setup(
        monkeypatch, raise_on_index=2, raise_exc=KeyboardInterrupt()
    )

    with pytest.raises(KeyboardInterrupt):
        DhanSDKTransport(
            credentials=DhanCredentials(
                client_id="test-id",
                access_token="test-token",
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )

    assert len(created) == 2
    assert len(shutdowns) == 2


def test_sdk_transport_partial_executor_cleanup_failure_does_not_replace_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, shutdowns = _sdk_transport_partial_executor_setup(
        monkeypatch,
        raise_on_index=1,
        raise_exc=KeyboardInterrupt(),
        shutdown_raises=RuntimeError("executor close failed"),
    )

    with pytest.raises(KeyboardInterrupt) as exc_info:
        DhanSDKTransport(
            credentials=DhanCredentials(
                client_id="test-id",
                access_token="test-token",
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )

    assert len(created) == 1
    assert len(shutdowns) == 1
    assert any("executor close failed" in note for note in getattr(exc_info.value, "__notes__", []))


def test_sdk_transport_partial_executor_cleanup_interruption_does_not_replace_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, shutdowns = _sdk_transport_partial_executor_setup(
        monkeypatch,
        raise_on_index=1,
        raise_exc=KeyboardInterrupt(),
        shutdown_raises=SystemExit(9),
    )

    with pytest.raises(KeyboardInterrupt) as exc_info:
        DhanSDKTransport(
            credentials=DhanCredentials(
                client_id="test-id",
                access_token="test-token",
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )

    assert len(created) == 1
    assert len(shutdowns) == 1
    assert any("SystemExit" in note for note in getattr(exc_info.value, "__notes__", []))


class _LedgerFakeDhanClient:
    def __init__(self, ledger_response: object) -> None:
        self._ledger_response = ledger_response

    def ledger_report(self, from_date: str, to_date: str) -> object:
        return self._ledger_response


class _TradeHistoryFakeDhanClient:
    def __init__(self, trade_history_response: object) -> None:
        self._trade_history_response = trade_history_response

    def get_trade_history(self, from_date: str, to_date: str, page_number: int = 0) -> object:
        return self._trade_history_response


def test_sdk_ledger_report_reads_official_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    ledger_response = {
        "status": "success",
        "remarks": "",
        "data": [
            {
                "dhanClientId": "client-1",
                "narration": "Test narration",
                "voucherdate": "2026-01-15",
                "exchange": "NSE",
                "voucherdesc": "Test voucher",
                "vouchernumber": "VN001",
                "debit": "100.50",
                "credit": "0",
                "runbal": "5000.00",
            }
        ],
    }
    client = _LedgerFakeDhanClient(ledger_response)
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        from_date = datetime(2026, 1, 1, tzinfo=UTC)
        to_date = datetime(2026, 1, 31, tzinfo=UTC)
        snapshot = transport.ledger_report(from_date, to_date, timeout=5.0)

        assert snapshot.available is True
        assert snapshot.from_date == from_date
        assert snapshot.to_date == to_date
        assert len(snapshot.entries) == 1
        entry = snapshot.entries[0]
        assert entry.observed_at == snapshot.observed_at
        assert entry.client_id == "client-1"
        assert entry.narration == "Test narration"
        assert entry.voucher_date == datetime(2026, 1, 15, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert entry.exchange == "NSE"
        assert entry.voucher_description == "Test voucher"
        assert entry.voucher_number == "VN001"
        assert entry.debit == Decimal("100.50")
        assert entry.credit == Decimal("0")
        assert entry.running_balance == Decimal("5000.00")
    finally:
        transport.close()


def test_sdk_ledger_report_empty_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _LedgerFakeDhanClient({"status": "success", "remarks": "", "data": []})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is True
        assert snapshot.entries == ()
    finally:
        transport.close()


def test_sdk_ledger_report_missing_mandatory_field_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _LedgerFakeDhanClient(
        {
            "status": "success",
            "remarks": "",
            "data": [
                {
                    "dhanClientId": "c1",
                    "narration": "n",
                    "voucherdate": "2026-01-15",
                    "exchange": "NSE",
                    "voucherdesc": "d",
                    "vouchernumber": "vn",
                    "debit": "1",
                    "credit": "0",
                }
            ],
        }
    )
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is False
        assert "missing running balance" in snapshot.message
    finally:
        transport.close()


def test_sdk_ledger_report_malformed_optional_not_applicable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _LedgerFakeDhanClient(
        {
            "status": "success",
            "remarks": "",
            "data": [
                {
                    "dhanClientId": "c1",
                    "narration": "n",
                    "voucherdate": "2026-01-15",
                    "exchange": "NSE",
                    "voucherdesc": "d",
                    "vouchernumber": "vn",
                    "debit": "1",
                    "credit": "0",
                    "runbal": "x",
                }
            ],
        }
    )
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is False
        assert "malformed" in snapshot.message
    finally:
        transport.close()


def test_sdk_trade_history_reads_official_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    trade_history_response = {
        "status": "success",
        "remarks": "",
        "data": [
            {
                "dhanClientId": "client-1",
                "orderId": "ORD001",
                "exchangeOrderId": "EXCH001",
                "exchangeTradeId": "TRD001",
                "transactionType": "BUY",
                "exchangeSegment": "NSE_EQ",
                "productType": "CNC",
                "securityId": "1333",
                "tradingSymbol": None,
                "customSymbol": "RELIANCE",
                "tradedQuantity": 10,
                "tradedPrice": "100.50",
                "instrument": "EQUITY",
                "exchangeTime": "2026-01-15 10:30:00",
                "stt": "10.00",
                "sebiTax": "0.50",
                "brokerageCharges": "5.00",
                "serviceTax": "0.90",
                "exchangeTransactionCharges": "0.50",
                "stampDuty": "1.00",
            }
        ],
    }
    client = _TradeHistoryFakeDhanClient(trade_history_response)
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        from_date = datetime(2026, 1, 1, tzinfo=UTC)
        to_date = datetime(2026, 1, 31, tzinfo=UTC)
        snapshot = transport.trade_history(from_date, to_date, page=0, timeout=5.0)
        assert snapshot.available is True
        assert snapshot.from_date == from_date
        assert snapshot.to_date == to_date
        assert snapshot.page == 0
        assert len(snapshot.entries) == 1
        entry = snapshot.entries[0]
        assert entry.observed_at == snapshot.observed_at
        assert entry.client_id == "client-1"
        assert entry.order_id == "ORD001"
        assert entry.exchange_order_id == "EXCH001"
        assert entry.exchange_trade_id == "TRD001"
        assert entry.transaction_side == "BUY"
        assert entry.exchange_segment == "NSE_EQ"
        assert entry.product_type == "CNC"
        assert entry.security_id == "1333"
        assert entry.trading_symbol is None
        assert entry.custom_symbol == "RELIANCE"
        assert entry.traded_quantity == 10
        assert entry.traded_price == Decimal("100.50")
        assert entry.instrument_type == "EQUITY"
        assert entry.exchange_timestamp == datetime(
            2026, 1, 15, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata")
        )
        assert entry.stt == Decimal("10.00")
        assert entry.sebi == Decimal("0.50")
        assert entry.brokerage == Decimal("5.00")
        assert entry.service_tax == Decimal("0.90")
        assert entry.exchange_txn_charges == Decimal("0.50")
        assert entry.stamp_duty == Decimal("1.00")
        assert entry.source_date_from == from_date
        assert entry.source_date_to == to_date
        assert entry.source_page == 0
    finally:
        transport.close()


def test_sdk_trade_history_empty_page_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _TradeHistoryFakeDhanClient({"status": "success", "remarks": "", "data": []})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), page=0, timeout=5.0
        )
        assert snapshot.available is True
        assert snapshot.entries == ()
    finally:
        transport.close()


def test_sdk_trade_history_duplicate_trade_id_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "status": "success",
        "remarks": "",
        "data": [
            {
                "dhanClientId": "c1",
                "orderId": "o1",
                "exchangeOrderId": "eo1",
                "exchangeTradeId": "t1",
                "transactionType": "BUY",
                "exchangeSegment": "NSE_EQ",
                "productType": "CNC",
                "securityId": "1",
                "tradingSymbol": "SYM",
                "tradedQuantity": 1,
                "tradedPrice": "10",
                "instrument": "EQUITY",
                "exchangeTime": "2026-01-15 10:30:00",
            },
            {
                "dhanClientId": "c1",
                "orderId": "o2",
                "exchangeOrderId": "eo2",
                "exchangeTradeId": "t1",
                "transactionType": "BUY",
                "exchangeSegment": "NSE_EQ",
                "productType": "CNC",
                "securityId": "1",
                "tradingSymbol": "SYM",
                "tradedQuantity": 1,
                "tradedPrice": "10",
                "instrument": "EQUITY",
                "exchangeTime": "2026-01-15 10:30:00",
            },
        ],
    }
    client = _TradeHistoryFakeDhanClient(response)
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), page=0, timeout=5.0
        )
        assert snapshot.available is False
        assert "duplicate exchange trade id" in snapshot.message
    finally:
        transport.close()


def test_sdk_trade_history_malformed_optional_charge_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "status": "success",
        "remarks": "",
        "data": [
            {
                "dhanClientId": "c1",
                "orderId": "o1",
                "exchangeOrderId": "eo1",
                "exchangeTradeId": "t1",
                "transactionType": "BUY",
                "exchangeSegment": "NSE_EQ",
                "productType": "CNC",
                "securityId": "1",
                "tradingSymbol": "SYM",
                "tradedQuantity": 1,
                "tradedPrice": "10",
                "instrument": "EQUITY",
                "exchangeTime": "2026-01-15 10:30:00",
                "stt": "bad",
            }
        ],
    }
    client = _TradeHistoryFakeDhanClient(response)
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), page=0, timeout=5.0
        )
        assert snapshot.available is False
        assert "malformed charge value" in snapshot.message
    finally:
        transport.close()


def test_sdk_trade_history_page_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    response = {
        "status": "success",
        "remarks": "",
        "data": [
            {
                "dhanClientId": "c1",
                "orderId": "o1",
                "exchangeOrderId": "eo1",
                "exchangeTradeId": "t1",
                "transactionType": "BUY",
                "exchangeSegment": "NSE_EQ",
                "productType": "CNC",
                "securityId": "1",
                "tradingSymbol": "SYM",
                "tradedQuantity": 1,
                "tradedPrice": "10",
                "instrument": "EQUITY",
                "exchangeTime": "2026-01-15 10:30:00",
            }
        ],
    }
    client = _TradeHistoryFakeDhanClient(response)
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        from_date = datetime(2026, 1, 1, tzinfo=UTC)
        to_date = datetime(2026, 1, 31, tzinfo=UTC)
        snapshot = transport.trade_history(from_date, to_date, page=2, timeout=5.0)
        assert snapshot.page == 2
        assert snapshot.entries[0].source_page == 2
        assert snapshot.entries[0].source_date_from == from_date
        assert snapshot.entries[0].source_date_to == to_date
    finally:
        transport.close()


def test_sdk_trade_history_transport_failure_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RaisingTradeHistoryClient(_CancelEchoFakeDhanClient):
        def get_trade_history(self, from_date: str, to_date: str, page_number: int = 0) -> object:
            raise RuntimeError("trade history endpoint failure")

    transport = _sdk_transport_without_sdk(monkeypatch, _RaisingTradeHistoryClient(None))
    try:
        snapshot = transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), page=0, timeout=5.0
        )
        assert snapshot.available is False
        assert "transport failure" in snapshot.message
    finally:
        transport.close()


def test_in_memory_transport_ledger_report_and_trade_history() -> None:
    transport = InMemoryDhanTransport()
    from_date = datetime(2026, 1, 1, tzinfo=UTC)
    to_date = datetime(2026, 1, 31, tzinfo=UTC)
    ledger_snapshot = transport.ledger_report(from_date, to_date)
    assert ledger_snapshot.available is True
    assert ledger_snapshot.from_date == from_date
    assert ledger_snapshot.to_date == to_date
    assert ledger_snapshot.entries == ()

    trade_snapshot = transport.trade_history(from_date, to_date, page=0)
    assert trade_snapshot.available is True
    assert trade_snapshot.from_date == from_date
    assert trade_snapshot.to_date == to_date
    assert trade_snapshot.page == 0
    assert trade_snapshot.entries == ()

    trade_snapshot_page1 = transport.trade_history(from_date, to_date, page=1)
    assert trade_snapshot_page1.page == 1


class _RecordingLedgerFakeDhanClient:
    def __init__(self, ledger_response: object) -> None:
        self._ledger_response = ledger_response
        self.called = False

    def ledger_report(self, from_date: str, to_date: str) -> object:
        self.called = True
        return self._ledger_response


class _RecordingTradeHistoryFakeDhanClient:
    def __init__(self, trade_history_response: object) -> None:
        self._trade_history_response = trade_history_response
        self.called = False

    def get_trade_history(self, from_date: str, to_date: str, page_number: int = 0) -> object:
        self.called = True
        return self._trade_history_response


def test_sdk_ledger_report_reads_official_object_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_response = {
        "status": "success",
        "remarks": "",
        "data": {
            "dhanClientId": "client-1",
            "narration": "FUNDS WITHDRAWAL",
            "voucherdate": "Jun 22, 2022",
            "exchange": "NSE-CAPITAL",
            "voucherdesc": "PAYBNK",
            "vouchernumber": "202200036701",
            "debit": "20000.00",
            "credit": "0.00",
            "runbal": "957.29",
        },
    }
    client = _RecordingLedgerFakeDhanClient(ledger_response)
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        from_date = datetime(2026, 1, 1, tzinfo=UTC)
        to_date = datetime(2026, 1, 31, tzinfo=UTC)
        snapshot = transport.ledger_report(from_date, to_date, timeout=5.0)

        assert snapshot.available is True
        assert snapshot.from_date == from_date
        assert snapshot.to_date == to_date
        assert len(snapshot.entries) == 1
        entry = snapshot.entries[0]
        assert entry.client_id == "client-1"
        assert entry.narration == "FUNDS WITHDRAWAL"
        assert entry.voucher_date == datetime(2022, 6, 22, tzinfo=ZoneInfo("Asia/Kolkata"))
        assert entry.exchange == "NSE-CAPITAL"
        assert entry.voucher_description == "PAYBNK"
        assert entry.voucher_number == "202200036701"
        assert entry.debit == Decimal("20000.00")
        assert entry.credit == Decimal("0.00")
        assert entry.running_balance == Decimal("957.29")
    finally:
        transport.close()


def test_sdk_ledger_report_empty_object_is_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient({"status": "success", "remarks": "", "data": {}})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is True
        assert snapshot.entries == ()
    finally:
        transport.close()


def test_sdk_ledger_report_iso_date_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient(
        {
            "status": "success",
            "remarks": "",
            "data": {
                "dhanClientId": "client-1",
                "narration": "Test",
                "voucherdate": "2026-01-15",
                "exchange": "NSE",
                "voucherdesc": "Test",
                "vouchernumber": "VN001",
                "debit": "1",
                "credit": "0",
                "runbal": "2",
            },
        }
    )
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is True
        assert snapshot.entries[0].voucher_date == datetime(
            2026, 1, 15, tzinfo=ZoneInfo("Asia/Kolkata")
        )
    finally:
        transport.close()


def test_sdk_ledger_report_malformed_voucher_date_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient(
        {
            "status": "success",
            "remarks": "",
            "data": {
                "dhanClientId": "client-1",
                "narration": "Test",
                "voucherdate": "not-a-date",
                "exchange": "NSE",
                "voucherdesc": "Test",
                "vouchernumber": "VN001",
                "debit": "1",
                "credit": "0",
                "runbal": "2",
            },
        }
    )
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is False
        assert "invalid voucher date" in snapshot.message
    finally:
        transport.close()


def test_sdk_ledger_report_empty_voucher_date_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient(
        {
            "status": "success",
            "remarks": "",
            "data": {
                "dhanClientId": "client-1",
                "narration": "Test",
                "voucherdate": "",
                "exchange": "NSE",
                "voucherdesc": "Test",
                "vouchernumber": "VN001",
                "debit": "1",
                "credit": "0",
                "runbal": "2",
            },
        }
    )
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is False
        assert "missing voucherdate" in snapshot.message
    finally:
        transport.close()


def test_sdk_ledger_report_missing_mandatory_value_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient(
        {
            "status": "success",
            "remarks": "",
            "data": {
                "dhanClientId": "client-1",
                "narration": "Test",
                "voucherdate": "2026-01-15",
                "exchange": "NSE",
                "voucherdesc": "Test",
                "vouchernumber": "VN001",
                "debit": "1",
                "credit": "0",
            },
        }
    )
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is False
        assert "missing running balance" in snapshot.message
    finally:
        transport.close()


def test_sdk_ledger_report_negative_debit_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient(
        {
            "status": "success",
            "remarks": "",
            "data": {
                "dhanClientId": "client-1",
                "narration": "Test",
                "voucherdate": "2026-01-15",
                "exchange": "NSE",
                "voucherdesc": "Test",
                "vouchernumber": "VN001",
                "debit": "-1",
                "credit": "0",
                "runbal": "2",
            },
        }
    )
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is False
        assert "debit cannot be negative" in snapshot.message
    finally:
        transport.close()


def test_sdk_ledger_report_float_precision_documented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient(
        {
            "status": "success",
            "remarks": "",
            "data": {
                "dhanClientId": "client-1",
                "narration": "Test",
                "voucherdate": "2026-01-15",
                "exchange": "NSE",
                "voucherdesc": "Test",
                "vouchernumber": "VN001",
                "debit": 0.1 + 0.2,
                "credit": 0,
                "runbal": 1.0,
            },
        }
    )
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is True
        assert snapshot.entries[0].debit == Decimal(str(0.1 + 0.2))
    finally:
        transport.close()


def test_sdk_trade_history_reads_official_shape_with_custom_symbol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trade_history_response = {
        "status": "success",
        "remarks": "",
        "data": [
            {
                "dhanClientId": "client-1",
                "orderId": "ORD001",
                "exchangeOrderId": "EXCH001",
                "exchangeTradeId": "TRD001",
                "transactionType": "BUY",
                "exchangeSegment": "NSE_EQ",
                "productType": "CNC",
                "securityId": "1333",
                "tradingSymbol": None,
                "customSymbol": "RELIANCE",
                "tradedQuantity": 10,
                "tradedPrice": 100.5,
                "instrument": "EQUITY",
                "exchangeTime": "2026-01-15 10:30:00",
                "stt": 10.0,
                "sebiTax": 0.5,
                "brokerageCharges": 5.0,
                "serviceTax": 0.9,
                "exchangeTransactionCharges": 0.5,
                "stampDuty": 1.0,
            }
        ],
    }
    client = _TradeHistoryFakeDhanClient(trade_history_response)
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        from_date = datetime(2026, 1, 1, tzinfo=UTC)
        to_date = datetime(2026, 1, 31, tzinfo=UTC)
        snapshot = transport.trade_history(from_date, to_date, page=0, timeout=5.0)
        assert snapshot.available is True
        assert snapshot.entries[0].trading_symbol is None
        assert snapshot.entries[0].custom_symbol == "RELIANCE"
        assert snapshot.entries[0].traded_price == Decimal(str(100.5))
        assert snapshot.entries[0].stt == Decimal(str(10.0))
    finally:
        transport.close()


def test_invalid_date_range_does_not_invoke_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingLedgerFakeDhanClient({"status": "success", "remarks": "", "data": {}})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        with pytest.raises(ValueError):
            transport.ledger_report(
                datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), timeout=5.0
            )
        assert not client.called
    finally:
        transport.close()


def test_invalid_page_does_not_invoke_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingTradeHistoryFakeDhanClient({"status": "success", "remarks": "", "data": []})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        with pytest.raises(ValueError):
            transport.trade_history(
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 31, tzinfo=UTC),
                page=-1,
                timeout=5.0,
            )
        assert not client.called
        with pytest.raises(ValueError):
            transport.trade_history(
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 31, tzinfo=UTC),
                page=True,
                timeout=5.0,
            )  # type: ignore[arg-type]
        assert not client.called
    finally:
        transport.close()


def test_naive_date_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _RecordingLedgerFakeDhanClient({"status": "success", "remarks": "", "data": {}})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        with pytest.raises(ValueError):
            transport.ledger_report(
                datetime(2026, 1, 1), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
            )
        assert not client.called
    finally:
        transport.close()


def test_valid_page_passed_to_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[int] = []

    class _RecordingClient(_CancelEchoFakeDhanClient):
        def __init__(self) -> None:
            super().__init__(None)

        def get_trade_history(self, from_date: str, to_date: str, page_number: int = 0) -> object:
            captured.append(page_number)
            return {"status": "success", "remarks": "", "data": []}

    transport = _sdk_transport_without_sdk(monkeypatch, _RecordingClient())
    try:
        transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), page=3, timeout=5.0
        )
        assert captured == [3]
    finally:
        transport.close()


class _CustomTz(tzinfo):
    def utcoffset(self, dt):
        return None

    def tzname(self, dt):
        return "Custom"

    def dst(self, dt):
        return None


def test_sdk_ledger_report_missing_data_key_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient({"status": "success", "remarks": ""})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is False
        assert "missing or invalid" in snapshot.message
    finally:
        transport.close()


def test_sdk_ledger_report_data_none_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient({"status": "success", "remarks": "", "data": None})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is False
        assert "missing or invalid" in snapshot.message
    finally:
        transport.close()


def test_sdk_ledger_report_data_empty_string_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient({"status": "success", "remarks": "", "data": ""})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is False
        assert "missing or invalid" in snapshot.message
    finally:
        transport.close()


def test_sdk_ledger_report_data_scalar_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient({"status": "success", "remarks": "", "data": 42})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is False
        assert "missing or invalid" in snapshot.message
    finally:
        transport.close()


def test_sdk_trade_history_missing_data_key_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _TradeHistoryFakeDhanClient({"status": "success", "remarks": ""})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), page=0, timeout=5.0
        )
        assert snapshot.available is False
        assert "missing or invalid" in snapshot.message
    finally:
        transport.close()


def test_sdk_trade_history_data_none_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _TradeHistoryFakeDhanClient({"status": "success", "remarks": "", "data": None})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), page=0, timeout=5.0
        )
        assert snapshot.available is False
        assert "missing or invalid" in snapshot.message
    finally:
        transport.close()


def test_sdk_trade_history_data_empty_string_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _TradeHistoryFakeDhanClient({"status": "success", "remarks": "", "data": ""})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), page=0, timeout=5.0
        )
        assert snapshot.available is False
        assert "missing or invalid" in snapshot.message
    finally:
        transport.close()


def test_sdk_trade_history_data_scalar_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _TradeHistoryFakeDhanClient({"status": "success", "remarks": "", "data": 42})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), page=0, timeout=5.0
        )
        assert snapshot.available is False
        assert "missing or invalid" in snapshot.message
    finally:
        transport.close()


def test_sdk_ledger_report_custom_tzinfo_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient({"status": "success", "remarks": "", "data": {}})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        with pytest.raises(ValueError):
            transport.ledger_report(
                datetime(2026, 1, 1, tzinfo=_CustomTz()),
                datetime(2026, 1, 31, tzinfo=UTC),
                timeout=5.0,
            )
        assert not client.called
    finally:
        transport.close()


def test_sdk_trade_history_custom_tzinfo_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingTradeHistoryFakeDhanClient({"status": "success", "remarks": "", "data": []})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        with pytest.raises(ValueError):
            transport.trade_history(
                datetime(2026, 1, 1, tzinfo=_CustomTz()),
                datetime(2026, 1, 31, tzinfo=UTC),
                page=0,
                timeout=5.0,
            )
        assert not client.called
    finally:
        transport.close()


def test_in_memory_transport_rejects_invalid_values() -> None:
    transport = InMemoryDhanTransport()
    from_date = datetime(2026, 1, 1, tzinfo=UTC)
    to_date = datetime(2026, 1, 31, tzinfo=UTC)
    with pytest.raises(ValueError):
        transport.ledger_report(datetime(2026, 1, 1), to_date)
    with pytest.raises(ValueError):
        transport.ledger_report(from_date, datetime(2026, 1, 31))
    with pytest.raises(ValueError):
        transport.ledger_report(to_date, from_date)
    with pytest.raises(ValueError):
        transport.trade_history(from_date, to_date, page=-1)
    with pytest.raises(ValueError):
        transport.trade_history(from_date, to_date, page=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        transport.trade_history(datetime(2026, 1, 1), to_date, page=0)


def test_sdk_ledger_report_non_finite_decimal_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient(
        {
            "status": "success",
            "remarks": "",
            "data": {
                "dhanClientId": "c1",
                "narration": "n",
                "voucherdate": "2026-01-15",
                "exchange": "NSE",
                "voucherdesc": "d",
                "vouchernumber": "vn",
                "debit": float("inf"),
                "credit": "0",
                "runbal": "2",
            },
        }
    )
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is False
        assert "non-finite" in snapshot.message
    finally:
        transport.close()


def test_sdk_ledger_report_negative_credit_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingLedgerFakeDhanClient(
        {
            "status": "success",
            "remarks": "",
            "data": {
                "dhanClientId": "c1",
                "narration": "n",
                "voucherdate": "2026-01-15",
                "exchange": "NSE",
                "voucherdesc": "d",
                "vouchernumber": "vn",
                "debit": "1",
                "credit": "-1",
                "runbal": "2",
            },
        }
    )
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), timeout=5.0
        )
        assert snapshot.available is False
        assert "credit cannot be negative" in snapshot.message
    finally:
        transport.close()


def test_sdk_trade_history_non_finite_price_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "status": "success",
        "remarks": "",
        "data": [
            {
                "dhanClientId": "c1",
                "orderId": "o1",
                "exchangeOrderId": "eo1",
                "exchangeTradeId": "t1",
                "transactionType": "BUY",
                "exchangeSegment": "NSE_EQ",
                "productType": "CNC",
                "securityId": "1",
                "tradingSymbol": "SYM",
                "tradedQuantity": 1,
                "tradedPrice": float("nan"),
                "instrument": "EQUITY",
                "exchangeTime": "2026-01-15 10:30:00",
            }
        ],
    }
    client = _TradeHistoryFakeDhanClient(response)
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), page=0, timeout=5.0
        )
        assert snapshot.available is False
        assert "non-finite" in snapshot.message or "invalid" in snapshot.message
    finally:
        transport.close()


def test_sdk_trade_history_non_finite_optional_charge_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "status": "success",
        "remarks": "",
        "data": [
            {
                "dhanClientId": "c1",
                "orderId": "o1",
                "exchangeOrderId": "eo1",
                "exchangeTradeId": "t1",
                "transactionType": "BUY",
                "exchangeSegment": "NSE_EQ",
                "productType": "CNC",
                "securityId": "1",
                "tradingSymbol": "SYM",
                "tradedQuantity": 1,
                "tradedPrice": "10",
                "instrument": "EQUITY",
                "exchangeTime": "2026-01-15 10:30:00",
                "stt": float("inf"),
            }
        ],
    }
    client = _TradeHistoryFakeDhanClient(response)
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), page=0, timeout=5.0
        )
        assert snapshot.available is False
        assert "non-finite" in snapshot.message or "malformed" in snapshot.message
    finally:
        transport.close()


def test_sdk_trade_history_negative_optional_charge_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "status": "success",
        "remarks": "",
        "data": [
            {
                "dhanClientId": "c1",
                "orderId": "o1",
                "exchangeOrderId": "eo1",
                "exchangeTradeId": "t1",
                "transactionType": "BUY",
                "exchangeSegment": "NSE_EQ",
                "productType": "CNC",
                "securityId": "1",
                "tradingSymbol": "SYM",
                "tradedQuantity": 1,
                "tradedPrice": "10",
                "instrument": "EQUITY",
                "exchangeTime": "2026-01-15 10:30:00",
                "stt": "-1",
            }
        ],
    }
    client = _TradeHistoryFakeDhanClient(response)
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 31, tzinfo=UTC), page=0, timeout=5.0
        )
        assert snapshot.available is False
        assert "cannot be negative" in snapshot.message or "malformed" in snapshot.message
    finally:
        transport.close()


def test_sdk_trade_history_page_none_rejected_before_sdk_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingTradeHistoryFakeDhanClient({"status": "success", "remarks": "", "data": []})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        with pytest.raises(ValueError):
            transport.trade_history(
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 31, tzinfo=UTC),
                page=None,  # type: ignore[arg-type]
                timeout=5.0,
            )
        assert not client.called
    finally:
        transport.close()


def test_in_memory_trade_history_page_none_rejected() -> None:
    transport = InMemoryDhanTransport()
    with pytest.raises(ValueError):
        transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 31, tzinfo=UTC),
            page=None,  # type: ignore[arg-type]
        )


def test_sdk_trade_history_float_page_rejected_before_sdk_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingTradeHistoryFakeDhanClient({"status": "success", "remarks": "", "data": []})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        with pytest.raises(ValueError):
            transport.trade_history(
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 31, tzinfo=UTC),
                page=1.5,  # type: ignore[arg-type]
                timeout=5.0,
            )
        assert not client.called
    finally:
        transport.close()


def test_in_memory_trade_history_float_page_rejected() -> None:
    transport = InMemoryDhanTransport()
    with pytest.raises(ValueError):
        transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 31, tzinfo=UTC),
            page=1.5,  # type: ignore[arg-type]
        )


def test_sdk_trade_history_string_page_rejected_before_sdk_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingTradeHistoryFakeDhanClient({"status": "success", "remarks": "", "data": []})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        with pytest.raises(ValueError):
            transport.trade_history(
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 31, tzinfo=UTC),
                page="1",  # type: ignore[arg-type]
                timeout=5.0,
            )
        assert not client.called
    finally:
        transport.close()


def test_in_memory_trade_history_string_page_rejected() -> None:
    transport = InMemoryDhanTransport()
    with pytest.raises(ValueError):
        transport.trade_history(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 31, tzinfo=UTC),
            page="1",  # type: ignore[arg-type]
        )


def test_sdk_trade_history_reversed_date_range_rejected_before_sdk_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _RecordingTradeHistoryFakeDhanClient({"status": "success", "remarks": "", "data": []})
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        with pytest.raises(ValueError):
            transport.trade_history(
                datetime(2026, 2, 1, tzinfo=UTC),
                datetime(2026, 1, 1, tzinfo=UTC),
                page=0,
                timeout=5.0,
            )
        assert not client.called
    finally:
        transport.close()


def test_dhan_ledger_entry_docstring_contains_precision_note() -> None:
    from quantx.plugins.dhan.models import DhanLedgerEntry

    assert "Decimal(str(value))" in (DhanLedgerEntry.__doc__ or "")
    assert "cannot reconstruct" in (DhanLedgerEntry.__doc__ or "")


def test_dhan_trade_history_entry_docstring_contains_precision_note() -> None:
    from quantx.plugins.dhan.models import DhanTradeHistoryEntry

    assert "Decimal(str(value))" in (DhanTradeHistoryEntry.__doc__ or "")
    assert "cannot reconstruct" in (DhanTradeHistoryEntry.__doc__ or "")


# Direct SDK transport coverage for market data and read-only observations.


def _sdk_transport_with_fake_market_feed(
    monkeypatch: pytest.MonkeyPatch,
    response: object,
    *,
    failure: Exception | None = None,
) -> tuple[DhanSDKTransport, list[object]]:
    """Install a deterministic fake MarketFeed module without importing the SDK."""
    import sys

    transport = _sdk_transport_without_sdk(
        monkeypatch, _CancelEchoFakeDhanClient(correlation_echo=None)
    )
    parent = sys.modules["dhanhq"]
    parent.__path__ = []  # type: ignore[attr-defined]
    calls: list[object] = []
    fake_module = types.ModuleType("dhanhq._market_feed")

    class _FakeMarketFeed:
        def __init__(self, context: object) -> None:
            self.context = context

        def quote_data(self, instruments: object) -> object:
            calls.append(instruments)
            if failure is not None:
                raise failure
            return response

    fake_module.MarketFeed = _FakeMarketFeed  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dhanhq._market_feed", fake_module)
    return transport, calls


def _sdk_transport_with_fake_historical_data(
    monkeypatch: pytest.MonkeyPatch,
    response: object,
    *,
    daily_failure: Exception | None = None,
    intraday_failure: Exception | None = None,
    daily_started: threading.Event | None = None,
    daily_release: threading.Event | None = None,
) -> tuple[DhanSDKTransport, list[tuple[str, tuple[object, ...], dict[str, object]]]]:
    """Install a deterministic fake HistoricalData implementation."""
    import sys

    transport = _sdk_transport_without_sdk(
        monkeypatch, _CancelEchoFakeDhanClient(correlation_echo=None)
    )
    parent = sys.modules["dhanhq"]
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    class _FakeHistoricalData:
        def __init__(self, context: object) -> None:
            self.context = context

        def historical_daily_data(self, *args: object) -> object:
            calls.append(("daily", args, {}))
            if daily_started is not None:
                daily_started.set()
                if daily_release is None or not daily_release.wait(timeout=5.0):
                    raise AssertionError("fake daily historical call was not released")
            if daily_failure is not None:
                raise daily_failure
            return response

        def intraday_minute_data(self, *args: object, **kwargs: object) -> object:
            calls.append(("intraday", args, kwargs))
            if intraday_failure is not None:
                raise intraday_failure
            return response

    parent.HistoricalData = _FakeHistoricalData  # type: ignore[attr-defined]
    return transport, calls


def _candle_response(*, start_time: object = 1767239100) -> dict[str, object]:
    return {
        "status": "success",
        "remarks": "",
        "data": {
            "open": ["100.25"],
            "high": ["102.50"],
            "low": ["99.75"],
            "close": ["101.50"],
            "volume": [1200],
            "start_Time": [start_time],
        },
    }


def test_sdk_quote_snapshot_uses_market_feed_and_normalizes_requested_packet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "status": "success",
        "remarks": "",
        "data": {
            "NSE_EQ": {
                "1333": {
                    "last_price": "101.25",
                    "depth": {
                        "buy": [{"price": "101.00", "quantity": "12"}],
                        "sell": [{"price": "101.50", "quantity": "15"}],
                    },
                }
            }
        },
    }
    transport, calls = _sdk_transport_with_fake_market_feed(monkeypatch, response)
    try:
        snapshot = transport.quote_snapshot("1333", "NSE_EQ", timeout=5.0)

        assert snapshot is not None
        assert snapshot.security_id == "1333"
        assert snapshot.exchange_segment == "NSE_EQ"
        assert snapshot.last_price == Decimal("101.25")
        assert snapshot.bid_price == Decimal("101.00")
        assert snapshot.bid_size == Decimal("12")
        assert snapshot.ask_price == Decimal("101.50")
        assert snapshot.ask_size == Decimal("15")
        assert calls == [{"NSE_EQ": ["1333"]}]
    finally:
        transport.close()


def test_sdk_quote_snapshot_returns_unavailable_for_malformed_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, calls = _sdk_transport_with_fake_market_feed(monkeypatch, ["not", "a", "mapping"])
    try:
        assert transport.quote_snapshot("1333", "NSE_EQ", timeout=5.0) is None
        assert calls == [{"NSE_EQ": ["1333"]}]
    finally:
        transport.close()


def test_sdk_quote_snapshot_returns_unavailable_for_vendor_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, calls = _sdk_transport_with_fake_market_feed(
        monkeypatch,
        {},
        failure=RuntimeError("synthetic quote transport failure"),
    )
    try:
        assert transport.quote_snapshot("1333", "NSE_EQ", timeout=5.0) is None
        assert calls == [{"NSE_EQ": ["1333"]}]
    finally:
        transport.close()


def test_sdk_quote_snapshot_does_not_invent_malformed_numeric_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = {
        "status": "success",
        "remarks": "",
        "data": {"NSE_EQ": {"1333": {"last_price": "not-a-price"}}},
    }
    transport, _ = _sdk_transport_with_fake_market_feed(monkeypatch, response)
    try:
        with pytest.raises(ValueError, match="invalid Dhan decimal field"):
            transport.quote_snapshot("1333", "NSE_EQ", timeout=5.0)
    finally:
        transport.close()


def test_sdk_candles_uses_daily_historical_data_branch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, calls = _sdk_transport_with_fake_historical_data(monkeypatch, _candle_response())
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)
    try:
        candles = transport.candles(
            "1333",
            "NSE_EQ",
            timeframe="1d",
            start=start,
            end=end,
            timeout=5.0,
        )

        assert len(candles) == 1
        assert candles[0].timeframe == "1d"
        assert candles[0].open == Decimal("100.25")
        assert candles[0].high == Decimal("102.50")
        assert candles[0].low == Decimal("99.75")
        assert candles[0].close == Decimal("101.50")
        assert candles[0].volume == Decimal("1200")
        assert calls == [
            (
                "daily",
                ("1333", "NSE_EQ", "EQUITY", "2026-01-01", "2026-01-02"),
                {},
            )
        ]
    finally:
        transport.close()


def test_sdk_candles_uses_intraday_interval_for_historical_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, calls = _sdk_transport_with_fake_historical_data(monkeypatch, _candle_response())
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 1, 2, tzinfo=UTC)
    try:
        candles = transport.candles(
            "1333",
            "NSE_EQ",
            timeframe="5m",
            start=start,
            end=end,
            timeout=5.0,
        )

        assert len(candles) == 1
        assert candles[0].timeframe == "5m"
        assert calls == [
            (
                "intraday",
                ("1333", "NSE_EQ", "EQUITY", "2026-01-01", "2026-01-02"),
                {"interval": 5},
            )
        ]
    finally:
        transport.close()


def test_sdk_candles_rejects_malformed_historical_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = {
        "status": "success",
        "remarks": "",
        "data": {
            "open": ["100"],
            "high": ["101"],
            "low": ["99"],
            "close": ["100"],
            "volume": [],
            "start_Time": [1767239100],
        },
    }
    transport, _ = _sdk_transport_with_fake_historical_data(monkeypatch, malformed)
    try:
        with pytest.raises(ValueError, match="lengths do not match"):
            transport.candles(
                "1333",
                "NSE_EQ",
                timeframe="1d",
                start=datetime(2026, 1, 1, tzinfo=UTC),
                end=datetime(2026, 1, 2, tzinfo=UTC),
                timeout=5.0,
            )
    finally:
        transport.close()


def test_sdk_candles_preserves_timeout_as_uncertain_transport_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    transport, _ = _sdk_transport_with_fake_historical_data(
        monkeypatch,
        _candle_response(),
        daily_started=started,
        daily_release=release,
    )
    try:
        with pytest.raises(DhanTimeoutError, match="candles"):
            transport.candles(
                "1333",
                "NSE_EQ",
                timeframe="1d",
                start=datetime(2026, 1, 1, tzinfo=UTC),
                end=datetime(2026, 1, 2, tzinfo=UTC),
                timeout=0.5,
            )
        assert started.is_set()
    finally:
        release.set()
        transport.close()


class _ReadOnlySDKFakeDhanClient:
    def __init__(
        self,
        *,
        positions_response: object | None = None,
        positions_failure: Exception | None = None,
        ledger_failure: Exception | None = None,
    ) -> None:
        self.positions_response = positions_response or {
            "status": "success",
            "remarks": "",
            "data": [
                {
                    "securityId": "1333",
                    "exchangeSegment": "NSE_EQ",
                    "netQty": "2",
                    "costPrice": "100.25",
                }
            ],
        }
        self.positions_failure = positions_failure
        self.ledger_failure = ledger_failure

    def get_fund_limits(self) -> object:
        return {"status": "success", "remarks": "", "data": {}}

    def get_positions(self) -> object:
        if self.positions_failure is not None:
            raise self.positions_failure
        return self.positions_response

    def ledger_report(self, from_date: str, to_date: str) -> object:
        if self.ledger_failure is not None:
            raise self.ledger_failure
        return {"status": "success", "remarks": "", "data": []}

    def place_order(self, **kwargs: object) -> object:
        raise AssertionError("read-only transport test must not submit an order")

    def cancel_order(self, order_id: str) -> object:
        raise AssertionError("read-only transport test must not cancel an order")


def test_sdk_health_success_path_uses_fund_limits_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _ReadOnlySDKFakeDhanClient()
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        assert transport.health(timeout=5.0) is True
    finally:
        transport.close()


def test_sdk_positions_reads_and_normalizes_vendor_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _ReadOnlySDKFakeDhanClient()
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        positions = transport.positions(timeout=5.0)

        assert positions.available is True
        assert len(positions.positions) == 1
        assert positions.positions[0].security_id == "1333"
        assert positions.positions[0].exchange_segment == "NSE_EQ"
        assert positions.positions[0].net_quantity == Decimal("2")
        assert positions.positions[0].average_price == Decimal("100.25")
    finally:
        transport.close()


def test_sdk_positions_transport_failure_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _ReadOnlySDKFakeDhanClient(
        positions_failure=RuntimeError("synthetic positions transport failure")
    )
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        positions = transport.positions(timeout=5.0)

        assert positions.available is False
        assert positions.positions == ()
        assert "transport failure" in positions.message
    finally:
        transport.close()


def test_sdk_ledger_report_transport_failure_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _ReadOnlySDKFakeDhanClient(
        ledger_failure=RuntimeError("synthetic ledger transport failure")
    )
    transport = _sdk_transport_without_sdk(monkeypatch, client)
    try:
        snapshot = transport.ledger_report(
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 31, tzinfo=UTC),
            timeout=5.0,
        )

        assert snapshot.available is False
        assert snapshot.entries == ()
        assert "transport failure" in snapshot.message
    finally:
        transport.close()


def test_quote_snapshot_helper_rejects_missing_identity_and_malformed_depth() -> None:
    from quantx.plugins.dhan.transport import _depth_level, _quote_snapshot

    envelope = {"status": "success", "remarks": "", "data": {"NSE_EQ": {}}}
    empty_data = {"status": "success", "remarks": "", "data": {}}
    assert _quote_snapshot(envelope, "1333", "NSE_EQ") is None
    assert _quote_snapshot(empty_data, "1333", "NSE_EQ") is None
    assert _depth_level({}, "buy") == (None, None)
    assert _depth_level({"depth": {"buy": []}}, "buy") == (None, None)
    with pytest.raises(ValueError, match="depth level is malformed"):
        _depth_level({"depth": {"buy": ["malformed"]}}, "buy")


def test_candle_snapshot_helper_rejects_failure_mismatched_and_invalid_entries() -> None:
    from quantx.plugins.dhan.transport import _candle_snapshots

    with pytest.raises(ValueError, match="reported failure"):
        _candle_snapshots(
            {"status": "failure", "remarks": "vendor rejected request", "data": ""},
            timeframe="1m",
        )

    mismatched = _candle_response()
    mismatched["data"]["volume"] = []  # type: ignore[index]
    with pytest.raises(ValueError, match="lengths do not match"):
        _candle_snapshots(mismatched, timeframe="1m")

    invalid_decimal = _candle_response()
    invalid_decimal["data"]["close"] = ["not-a-price"]  # type: ignore[index]
    with pytest.raises(ValueError, match="candle entry is malformed"):
        _candle_snapshots(invalid_decimal, timeframe="1m")
