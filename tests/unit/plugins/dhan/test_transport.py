import threading
import time
import types
from datetime import UTC, datetime
from decimal import Decimal

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


class _HealthFakeDhanClient:
    def get_fund_limits(self) -> object:
        return {"status": "success", "remarks": "", "data": {}}

    def get_positions(self) -> object:
        return {"status": "success", "remarks": "", "data": []}

    def place_order(self, **kwargs: object) -> object:
        raise AssertionError("no submission is expected")

    def cancel_order(self, order_id: str) -> object:
        raise AssertionError("no cancellation is expected")

    def get_order_by_correlationID(self, correlation_id: str) -> object:  # noqa: N802
        raise AssertionError("no reconciliation is expected")


def test_sdk_health_reports_success_status(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _sdk_transport_without_sdk(monkeypatch, _HealthFakeDhanClient())
    try:
        assert transport.health(timeout=5.0) is True
    finally:
        transport.close()


class _RaisingPositionsClient(_CancelEchoFakeDhanClient):
    def get_positions(self) -> object:
        raise RuntimeError("positions endpoint failure")


def test_sdk_positions_transport_failure_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _sdk_transport_without_sdk(monkeypatch, _RaisingPositionsClient(None))
    try:
        snapshot = transport.positions(timeout=5.0)
        assert snapshot.available is False
        assert snapshot.positions == ()
        assert "positions endpoint failure" in snapshot.message
    finally:
        transport.close()


def test_positions_non_list_data_is_unavailable() -> None:
    from quantx.plugins.dhan.transport import _positions_snapshot

    snapshot = _positions_snapshot({"status": "success", "remarks": "", "data": {}})

    assert snapshot.available is False
    assert snapshot.positions == ()


def test_positions_failure_status_is_unavailable() -> None:
    from quantx.plugins.dhan.transport import _positions_snapshot

    snapshot = _positions_snapshot({"status": "failure", "remarks": "bad token", "data": []})

    assert snapshot.available is False
    assert snapshot.positions == ()


def test_holdings_failure_status_is_unavailable() -> None:
    from quantx.plugins.dhan.transport import _holdings_snapshot

    snapshot = _holdings_snapshot({"status": "failure", "remarks": "bad token", "data": []})

    assert snapshot.available is False
    assert snapshot.holdings == ()


def test_holding_missing_identity_returns_none() -> None:
    from quantx.plugins.dhan.transport import _holding_snapshot

    assert _holding_snapshot({"securityId": "1333"}) is None
    assert _holding_snapshot({"exchange": "ALL"}) is None


def test_holding_missing_total_quantity_returns_none() -> None:
    from quantx.plugins.dhan.transport import _holding_snapshot

    assert _holding_snapshot({"securityId": "1333", "exchange": "ALL"}) is None


def test_intraday_interval_rejects_unknown_timeframe() -> None:
    from quantx.plugins.dhan.transport import _intraday_interval

    with pytest.raises(ValueError, match="unsupported Dhan intraday timeframe"):
        _intraday_interval("2h")


def test_depth_level_rejects_malformed_best_level() -> None:
    from quantx.plugins.dhan.transport import _depth_level

    with pytest.raises(ValueError, match="Dhan market depth level is malformed"):
        _depth_level({"depth": {"buy": [1]}}, "buy")


def test_profile_snapshot_status_branch_is_covered() -> None:
    from quantx.plugins.dhan.transport import _profile_snapshot

    snapshot = _profile_snapshot(
        {"status": "success", "remarks": "", "data": {"dhanClientId": "client-1"}}
    )

    assert snapshot.available is True
    assert snapshot.client_id == "client-1"


class _QuoteMarketFeed:
    def __init__(self, context: object) -> None:
        pass

    def quote_data(self, subscription: object) -> object:
        return {
            "status": "success",
            "remarks": "",
            "data": {
                "NSE_EQ": {
                    "1333": {
                        "last_price": 100.25,
                        "last_trade_time": "2026-01-01 10:00:00",
                        "depth": {
                            "buy": [{"price": 100.00, "quantity": 10}],
                            "sell": [{"price": 100.50, "quantity": 5}],
                        },
                    }
                }
            },
        }


def test_sdk_quote_snapshot_reads_through_market_feed(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    transport = _sdk_transport_without_sdk(monkeypatch, _CancelEchoFakeDhanClient(None))
    fake_dhanhq = sys.modules["dhanhq"]
    fake_market_feed = types.ModuleType("dhanhq._market_feed")
    fake_market_feed.MarketFeed = _QuoteMarketFeed  # type: ignore[attr-defined]
    fake_dhanhq._market_feed = fake_market_feed  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dhanhq._market_feed", fake_market_feed)
    try:
        quote = transport.quote_snapshot("1333", "NSE_EQ", timeout=5.0)

        assert quote is not None
        assert quote.last_price == Decimal("100.25")
        assert quote.bid_price == Decimal("100.00")
        assert quote.ask_price == Decimal("100.50")
    finally:
        transport.close()


def test_sdk_quote_snapshot_transport_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    class _RaisingMarketFeed:
        def __init__(self, context: object) -> None:
            pass

        def quote_data(self, subscription: object) -> object:
            raise RuntimeError("quote endpoint failure")

    import sys
    import types

    transport = _sdk_transport_without_sdk(monkeypatch, _CancelEchoFakeDhanClient(None))
    fake_dhanhq = sys.modules["dhanhq"]
    fake_market_feed = types.ModuleType("dhanhq._market_feed")
    fake_market_feed.MarketFeed = _RaisingMarketFeed  # type: ignore[attr-defined]
    fake_dhanhq._market_feed = fake_market_feed  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dhanhq._market_feed", fake_market_feed)
    try:
        assert transport.quote_snapshot("1333", "NSE_EQ", timeout=5.0) is None
    finally:
        transport.close()


def test_quote_snapshot_helper_normalizes_full_packet() -> None:
    from quantx.plugins.dhan.transport import _quote_snapshot

    quote = _quote_snapshot(
        {
            "status": "success",
            "remarks": "",
            "data": {
                "NSE_EQ": {
                    "1333": {
                        "last_price": 100.25,
                        "last_trade_time": "2026-01-01 10:00:00",
                        "depth": {
                            "buy": [{"price": 100.00, "quantity": 10}],
                            "sell": [{"price": 100.50, "quantity": 5}],
                        },
                    }
                }
            },
        },
        "1333",
        "NSE_EQ",
    )

    assert quote is not None
    assert quote.last_price == Decimal("100.25")
    assert quote.observed_at.year == 2026


def test_quote_snapshot_helper_returns_none_for_missing_or_failed_data() -> None:
    from quantx.plugins.dhan.transport import _quote_snapshot

    assert (
        _quote_snapshot({"status": "failure", "remarks": "", "data": {}}, "1333", "NSE_EQ") is None
    )
    assert (
        _quote_snapshot({"status": "success", "remarks": "", "data": {}}, "1333", "NSE_EQ") is None
    )
    assert (
        _quote_snapshot(
            {"status": "success", "remarks": "", "data": {"NSE_EQ": {}}}, "1333", "NSE_EQ"
        )
        is None
    )


def test_quote_snapshot_helper_falls_back_to_current_time_without_trade_time() -> None:
    from quantx.plugins.dhan.transport import _quote_snapshot

    quote = _quote_snapshot(
        {
            "status": "success",
            "remarks": "",
            "data": {"NSE_EQ": {"1333": {"last_price": 100}}},
        },
        "1333",
        "NSE_EQ",
    )

    assert quote is not None
    assert quote.last_price == Decimal("100")
    assert quote.observed_at is not None


class _HistoricalData:
    def __init__(self, context: object) -> None:
        pass

    def historical_daily_data(self, *args: object, **kwargs: object) -> object:
        return {
            "status": "success",
            "remarks": "",
            "data": {
                "open": [10],
                "high": [11],
                "low": [9],
                "close": [10.5],
                "volume": [100],
                "start_Time": [1704067200],
            },
        }

    def intraday_minute_data(self, *args: object, interval: int = 1, **kwargs: object) -> object:
        return {
            "status": "success",
            "remarks": "",
            "data": {
                "open": [10],
                "high": [11],
                "low": [9],
                "close": [10.5],
                "volume": [100],
                "start_Time": [1704067200],
            },
        }


def test_sdk_candles_reads_daily_and_intraday_history(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    transport = _sdk_transport_without_sdk(monkeypatch, _CancelEchoFakeDhanClient(None))
    fake_dhanhq = sys.modules["dhanhq"]
    fake_dhanhq.HistoricalData = _HistoricalData  # type: ignore[attr-defined]
    try:
        daily = transport.candles(
            "1333",
            "NSE_EQ",
            timeframe="1d",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )
        intraday = transport.candles(
            "1333",
            "NSE_EQ",
            timeframe="5m",
            start=datetime(2024, 1, 1, tzinfo=UTC),
            end=datetime(2024, 1, 2, tzinfo=UTC),
        )

        assert len(daily) == 1
        assert len(intraday) == 1
        assert daily[0].close == Decimal("10.5")
    finally:
        transport.close()


def test_candle_snapshots_parse_parallel_arrays() -> None:
    from quantx.plugins.dhan.transport import _candle_snapshots

    snapshots = _candle_snapshots(
        {
            "status": "success",
            "remarks": "",
            "data": {
                "open": [10],
                "high": [11],
                "low": [9],
                "close": [10.5],
                "volume": [100],
                "start_Time": [1704067200],
            },
        },
        timeframe="1d",
    )

    assert len(snapshots) == 1
    assert snapshots[0].open == Decimal("10")
    assert snapshots[0].volume == Decimal("100")


def test_candle_snapshots_reject_failure_and_malformed_series() -> None:
    from quantx.plugins.dhan.transport import _candle_snapshots

    with pytest.raises(ValueError, match="Dhan historical data reported failure"):
        _candle_snapshots({"status": "failure", "remarks": "bad", "data": {}}, timeframe="1d")

    with pytest.raises(ValueError, match="Dhan candle payload must be a mapping"):
        _candle_snapshots(
            {"status": "success", "remarks": "", "data": {"data": "not-a-mapping"}}, timeframe="1d"
        )

    with pytest.raises(ValueError, match="Dhan candle series is missing"):
        _candle_snapshots(
            {"status": "success", "remarks": "", "data": {"open": [1]}}, timeframe="1d"
        )

    with pytest.raises(ValueError, match="Dhan candle series lengths do not match"):
        _candle_snapshots(
            {
                "status": "success",
                "remarks": "",
                "data": {
                    "open": [1],
                    "high": [1, 2],
                    "low": [1],
                    "close": [1],
                    "volume": [1],
                    "start_Time": [1],
                },
            },
            timeframe="1d",
        )


def test_candle_snapshots_reject_malformed_entry() -> None:
    from quantx.plugins.dhan.transport import _candle_snapshots

    with pytest.raises(ValueError, match="Dhan candle entry is malformed"):
        _candle_snapshots(
            {
                "status": "success",
                "remarks": "",
                "data": {
                    "open": ["bad"],
                    "high": [11],
                    "low": [9],
                    "close": [10.5],
                    "volume": [100],
                    "start_Time": [1704067200],
                },
            },
            timeframe="1d",
        )


def test_candle_timestamp_parses_string_and_epoch() -> None:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from quantx.plugins.dhan.transport import _candle_timestamp

    assert _candle_timestamp(1704067200).tzinfo == ZoneInfo("Asia/Kolkata")
    parsed = _candle_timestamp("2026-01-01 10:00:00")
    assert isinstance(parsed, datetime)


def test_candle_timestamp_rejects_unrecognized_value() -> None:
    from quantx.plugins.dhan.transport import _candle_timestamp

    with pytest.raises(ValueError, match="unrecognized Dhan candle timestamp"):
        _candle_timestamp(object())


def test_order_detail_failure_branch_is_covered() -> None:
    from quantx.plugins.dhan.transport import _order_detail

    detail = _order_detail({"status": "failure", "remarks": "bad", "data": {}})

    assert detail.order_status == "UNKNOWN"
    assert detail.order_id is None


def test_envelope_rejects_non_mapping() -> None:
    from quantx.plugins.dhan.transport import _envelope

    with pytest.raises(TypeError, match="Dhan SDK response must be a mapping"):
        _envelope("not-a-mapping")


def test_dhan_error_code_returns_none_for_empty_or_non_mapping() -> None:
    from quantx.plugins.dhan.transport import _dhan_error_code

    assert _dhan_error_code("not-a-mapping") is None
    assert _dhan_error_code({"remarks": {"error_code": "   "}}) is None
    assert _dhan_error_code({"remarks": {"error_code": "AUTH"}}) == "AUTH"


def test_close_handles_missing_and_raising_executors() -> None:
    from concurrent.futures import ThreadPoolExecutor

    from quantx.plugins.dhan.transport import DhanSDKTransport

    transport = DhanSDKTransport.__new__(DhanSDKTransport)
    transport._submit_executor = None
    transport._reconcile_executor = ThreadPoolExecutor(max_workers=1)
    transport._query_executor = ThreadPoolExecutor(max_workers=1)

    class _RaisingExecutor:
        def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
            raise RuntimeError("shutdown failed")

    transport._reconcile_executor = _RaisingExecutor()  # type: ignore[assignment]
    transport.close()

    assert transport._query_executor._shutdown is True


def test_profile_snapshot_raw_and_failure_branches() -> None:
    from quantx.plugins.dhan.transport import _profile_snapshot

    assert _profile_snapshot({"dhanClientId": "client-1"}).client_id == "client-1"
    assert _profile_snapshot({"status": "failure", "remarks": "bad", "data": {}}).available is False


def test_sdk_positions_success_returns_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    class _PositionsClient(_CancelEchoFakeDhanClient):
        def get_positions(self) -> object:
            return {"status": "success", "remarks": "", "data": []}

    transport = _sdk_transport_without_sdk(monkeypatch, _PositionsClient(None))
    try:
        snapshot = transport.positions(timeout=5.0)
        assert snapshot.available is True
        assert snapshot.positions == ()
    finally:
        transport.close()


def test_money_field_blank_string_is_missing() -> None:
    from quantx.plugins.dhan.transport import _money_field

    assert _money_field({"value": "   "}, "value") is None


def test_funds_snapshot_rejects_non_mapping_response() -> None:
    from quantx.plugins.dhan.transport import _funds_snapshot

    snapshot = _funds_snapshot("not-a-mapping")

    assert snapshot.available is False
    assert "unrecognized Dhan fund-limits response" in snapshot.message


def test_positions_snapshot_rejects_non_mapping_response() -> None:
    from quantx.plugins.dhan.transport import _positions_snapshot

    snapshot = _positions_snapshot("not-a-mapping")

    assert snapshot.available is False
    assert snapshot.message == "Dhan positions response must be a mapping"


def test_holdings_snapshot_rejects_non_mapping_response() -> None:
    from quantx.plugins.dhan.transport import _holdings_snapshot

    snapshot = _holdings_snapshot("not-a-mapping")

    assert snapshot.available is False
    assert snapshot.message == "Dhan holdings response must be a mapping"


def test_position_snapshot_rejects_missing_identity() -> None:
    from quantx.plugins.dhan.transport import _position_snapshot

    assert _position_snapshot({}) is None
    assert _position_snapshot({"securityId": "1333"}) is None


def test_quote_snapshot_helper_rejects_malformed_envelope() -> None:
    from quantx.plugins.dhan.transport import _quote_snapshot

    assert _quote_snapshot("not-a-mapping", "1333", "NSE_EQ") is None


def test_depth_level_returns_none_without_levels() -> None:
    from quantx.plugins.dhan.transport import _depth_level

    assert _depth_level({"depth": {"buy": []}}, "buy") == (None, None)


def test_dhan_error_code_rejects_non_string_value() -> None:
    from quantx.plugins.dhan.transport import _dhan_error_code

    assert _dhan_error_code({"remarks": {"error_code": 123}}) is None


def test_format_dhan_remarks_returns_code_or_message_only() -> None:
    from quantx.plugins.dhan.transport import _format_dhan_remarks

    assert (
        _format_dhan_remarks({"remarks": {"error_code": "AUTH", "error_message": "denied"}})
        == "AUTH: denied"
    )
    assert _format_dhan_remarks({"remarks": {"error_code": "AUTH"}}) == "AUTH"
    assert _format_dhan_remarks({"remarks": {"error_message": "denied"}}) == "denied"


def test_position_snapshot_rejects_non_mapping() -> None:
    from quantx.plugins.dhan.transport import _position_snapshot

    assert _position_snapshot("not-a-mapping") is None


def test_in_memory_transport_health_quote_and_candles_cover_defaults() -> None:
    from datetime import UTC, datetime

    transport = InMemoryDhanTransport()

    assert transport.health() is True
    assert transport.quote_snapshot("1333", "NSE_EQ") is None
    assert (
        transport.candles(
            "1333",
            "NSE_EQ",
            timeframe="1d",
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2026, 1, 2, tzinfo=UTC),
        )
        == ()
    )



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

