"""Tests for the Dhan production host/deployment adapter."""

import sqlite3
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
from quantx.domain.enums import AssetClass, OrderSide, OrderType, TimeInForce
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Fill
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.idempotency import PendingExecutionContext
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.order_lifecycle import OrderLifecycleStatus
from quantx.integrations.reconciliation import (
    AccountFinancialState,
    OrderObservation,
    PositionState,
    StateSource,
)
from quantx.persistence.sqlite import SqliteReceiptRepository
from quantx.plugins.dhan.host import DhanHostConfig, DhanHostRuntime, build_dhan_host_runtime
from quantx.plugins.dhan.market_data import DhanMarketDataAdapter
from quantx.plugins.dhan.models import DhanCandleSnapshot, DhanCredentials, DhanInstrumentRef
from quantx.plugins.dhan.transport import DhanSDKTransport, InMemoryDhanTransport

CHECKED_AT = datetime(2026, 1, 1, 0, 0, 10, tzinfo=UTC)


def _instrument() -> Instrument:
    return Instrument(
        InstrumentId("NSE", "TCS"),
        "TCS",
        AssetClass.EQUITY,
        MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        "INR",
        Decimal("0.05"),
        Decimal("1"),
    )


def _instrument_ref() -> DhanInstrumentRef:
    return DhanInstrumentRef(
        security_id="1333",
        exchange_segment="NSE_EQ",
        trading_symbol="TCS",
        product_type="CNC",
    )


def _config(tmp_path, **overrides) -> DhanHostConfig:
    return DhanHostConfig(
        database_path=overrides.pop("database_path", tmp_path / "quantx.db"),
        account_id=overrides.pop("account_id", AccountId("acct-1")),
        connection_id=overrides.pop("connection_id", BrokerConnectionId("conn-1")),
        market_context_id=overrides.pop("market_context_id", "NSE_EQ"),
        instruments=overrides.pop("instruments", ((_instrument(), _instrument_ref()),)),
        transport=overrides.pop("transport", InMemoryDhanTransport()),
        credentials=overrides.pop("credentials", None),
        submit_timeout_seconds=overrides.pop("submit_timeout_seconds", 5.0),
        cancel_timeout_seconds=overrides.pop("cancel_timeout_seconds", 5.0),
        reconcile_timeout_seconds=overrides.pop("reconcile_timeout_seconds", 5.0),
        **overrides,
    )


def _approved() -> ApprovedExecutionRequest:
    instrument = _instrument()
    context = ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=instrument.market,
        broker_connection_id=BrokerConnectionId("conn-1"),
        execution_mode=ExecutionMode.LIVE,
    )
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        execution_context=context,
    )
    return ApprovedExecutionRequest(
        build_order_from_intent(intent),
        context,
        RiskResult(RiskDecision.APPROVE, "approved"),
        PolicyResult(PolicyDecision.APPROVE, "approved"),
    )


def _seed_pending(host: DhanHostRuntime, approved: ApprovedExecutionRequest) -> str:
    fingerprint = request_fingerprint(approved)
    host.runtime.unit_of_work.idempotency.reserve_or_get(
        approved.order.client_order_id,
        fingerprint,
        PendingExecutionContext.from_request(approved, fingerprint),
    )
    return fingerprint


def _filled_transport() -> InMemoryDhanTransport:
    from quantx.plugins.dhan.models import DhanPositionSnapshot

    return InMemoryDhanTransport(
        response_status="TRADED",
        filled_quantity=Decimal("2"),
        average_traded_price=Decimal("100"),
        position_snapshots=(
            DhanPositionSnapshot(
                security_id="1333",
                exchange_segment="NSE_EQ",
                net_quantity=Decimal("10"),
                average_price=Decimal("100"),
            ),
        ),
    )


def _resolving_config(tmp_path, approved: ApprovedExecutionRequest) -> DhanHostConfig:
    order_id = approved.order.client_order_id
    context = approved.execution_context
    return DhanHostConfig(
        database_path=tmp_path / "quantx.db",
        account_id=context.account_id,
        connection_id=context.broker_connection_id,
        market_context_id="NSE_EQ",
        instruments=((_instrument(), _instrument_ref()),),
        transport=_filled_transport(),
        submit_timeout_seconds=5.0,
        cancel_timeout_seconds=5.0,
        reconcile_timeout_seconds=5.0,
        local_order_provider=lambda request: OrderObservation(
            order_id,
            OrderLifecycleStatus.FILLED,
            "2",
            "2",
            broker_order_id="dhan-test-order",
            account_id=context.account_id,
            connection_id=context.broker_connection_id,
        ),
        local_position_provider=lambda request: PositionState(
            context.account_id,
            context.broker_connection_id,
            "NSE:TCS",
            Decimal("10"),
            Decimal("100"),
            CHECKED_AT,
            StateSource.PAPER,
        ),
        local_account_provider=lambda request: AccountFinancialState(
            context.account_id,
            context.broker_connection_id,
            CHECKED_AT,
            StateSource.PAPER,
            "INR",
            available_cash=Decimal("5000"),
            margin_used=Decimal("1200"),
        ),
        fill_provider=lambda request, local_order: (
            Fill(
                client_order_id=order_id,
                instrument=approved.order.instrument,
                side=approved.order.side,
                quantity=Decimal("2"),
                price=Decimal("100"),
                filled_at=CHECKED_AT,
            ),
        ),
    )


def test_host_registers_exact_account_connection(tmp_path) -> None:
    host = build_dhan_host_runtime(_config(tmp_path))
    try:
        registered = host.registry.get(BrokerConnectionId("conn-1"))

        assert registered is not None
        assert registered.ref.account_id == AccountId("acct-1")
        assert registered.ref.connection_id == BrokerConnectionId("conn-1")
        assert registered.ref.broker_id == "dhan"
        assert registered.ref.market_context_id == "NSE_EQ"
        assert registered.adapter is host.adapter
        assert host.registry.get(BrokerConnectionId("conn-unknown")) is None
    finally:
        host.close()


def test_host_wires_dhan_recovery_provider(tmp_path) -> None:
    approved = _approved()
    host = build_dhan_host_runtime(_resolving_config(tmp_path, approved))
    try:
        _seed_pending(host, approved)

        result = host.start(checked_at=CHECKED_AT)

        assert host.started
        assert result.recovered == 1
        persisted = SqliteReceiptRepository(host.runtime.database).get_by_client_order(
            approved.order.client_order_id
        )
        assert persisted is not None
    finally:
        host.close()


def test_host_start_delegates_to_production_runtime(tmp_path) -> None:
    host = build_dhan_host_runtime(_config(tmp_path))
    try:
        result = host.start(checked_at=CHECKED_AT)

        assert host.started
        assert result.pending == 0
        with pytest.raises(RuntimeError, match="already started"):
            host.start(checked_at=CHECKED_AT)
    finally:
        host.close()


def test_host_startup_failure_propagates_without_started(tmp_path) -> None:
    host = build_dhan_host_runtime(_config(tmp_path))
    host.close()

    with pytest.raises(sqlite3.ProgrammingError):
        host.start(checked_at=CHECKED_AT)

    assert not host.started


def test_host_close_is_deterministic(tmp_path) -> None:
    host = build_dhan_host_runtime(_config(tmp_path))
    host.close()
    host.close()

    with build_dhan_host_runtime(_config(tmp_path)) as scoped:
        assert not scoped.started
    assert not scoped.started


def test_host_build_failure_releases_nothing_to_start(tmp_path) -> None:
    with pytest.raises(sqlite3.OperationalError):
        build_dhan_host_runtime(
            _config(tmp_path, database_path=tmp_path / "missing-dir" / "quantx.db")
        )


def test_host_rejects_empty_market_context(tmp_path) -> None:
    with pytest.raises(ValueError, match="market context"):
        _config(tmp_path, market_context_id="  ")


def test_host_requires_exactly_one_transport_source(tmp_path) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        _config(tmp_path, transport=None, credentials=None)
    with pytest.raises(ValueError, match="exactly one"):
        _config(
            tmp_path,
            transport=InMemoryDhanTransport(),
            credentials=DhanCredentials("client", "token"),
        )


def test_host_rejects_empty_account_identity(tmp_path) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        _config(tmp_path, account_id=AccountId("  "))


def test_host_rejects_empty_instruments(tmp_path) -> None:
    with pytest.raises(ValueError, match="instruments"):
        _config(tmp_path, instruments=())


def test_host_rejects_duplicate_instruments(tmp_path) -> None:
    instrument = (_instrument(), _instrument_ref())

    with pytest.raises(ValueError, match="duplicate"):
        _config(tmp_path, instruments=(instrument, instrument))


def test_host_rejects_invalid_submit_timeout(tmp_path) -> None:
    with pytest.raises(ValueError, match="submit_timeout_seconds must be a positive number"):
        _config(tmp_path, submit_timeout_seconds=0)
    with pytest.raises(ValueError, match="submit_timeout_seconds must be a positive number"):
        _config(tmp_path, submit_timeout_seconds=-1)
    with pytest.raises(ValueError, match="submit_timeout_seconds must be a positive number"):
        _config(tmp_path, submit_timeout_seconds="invalid")
    with pytest.raises(ValueError, match="submit_timeout_seconds must be a positive number"):
        _config(tmp_path, submit_timeout_seconds=True)


def test_host_rejects_invalid_cancel_timeout(tmp_path) -> None:
    with pytest.raises(ValueError, match="cancel_timeout_seconds must be a positive number"):
        _config(tmp_path, cancel_timeout_seconds=0)
    with pytest.raises(ValueError, match="cancel_timeout_seconds must be a positive number"):
        _config(tmp_path, cancel_timeout_seconds=True)


def test_host_rejects_invalid_reconcile_timeout(tmp_path) -> None:
    with pytest.raises(ValueError, match="reconcile_timeout_seconds must be a positive number"):
        _config(tmp_path, reconcile_timeout_seconds=0)
    with pytest.raises(ValueError, match="reconcile_timeout_seconds must be a positive number"):
        _config(tmp_path, reconcile_timeout_seconds=False)


def test_host_builds_sdk_transport_from_credentials(tmp_path) -> None:
    pytest.importorskip("dhanhq", reason="optional dhan extra is not installed")
    host = build_dhan_host_runtime(
        _config(
            tmp_path,
            transport=None,
            credentials=DhanCredentials("client-id", "access-token"),
            submit_timeout_seconds=5.0,
            cancel_timeout_seconds=5.0,
            reconcile_timeout_seconds=5.0,
        )
    )
    try:
        assert isinstance(host.transport, DhanSDKTransport)
    finally:
        host.close()


def test_host_exposes_no_submission_surface(tmp_path) -> None:
    approved = _approved()
    transport = _filled_transport()
    host = build_dhan_host_runtime(_config(tmp_path, transport=transport))
    try:
        for name in ("submit", "execute", "dispatch", "cancel", "reconcile", "place_order"):
            assert not hasattr(host, name), name

        _seed_pending(host, approved)
        host.start(checked_at=CHECKED_AT)

        assert transport.submitted == ()
        assert transport.cancelled == ()
    finally:
        host.close()


def test_host_threads_read_timeout_into_adapter(tmp_path) -> None:
    host = build_dhan_host_runtime(_config(tmp_path, read_timeout_seconds=7.5))
    try:
        assert host.adapter._read_timeout == 7.5
    finally:
        host.close()


def test_host_read_timeout_defaults_to_bounded_constant(tmp_path) -> None:
    from quantx.plugins.dhan.transport import DEFAULT_READ_TIMEOUT_SECONDS

    host = build_dhan_host_runtime(_config(tmp_path))
    try:
        assert host.adapter._read_timeout == DEFAULT_READ_TIMEOUT_SECONDS
    finally:
        host.close()


def test_host_rejects_non_positive_read_timeout(tmp_path) -> None:
    with pytest.raises(ValueError, match="read_timeout_seconds"):
        _config(tmp_path, read_timeout_seconds=0)


def test_host_wires_market_data_adapter_to_same_transport(tmp_path) -> None:
    transport = InMemoryDhanTransport(
        candle_snapshots={
            ("1333", "NSE_EQ"): (
                DhanCandleSnapshot(
                    timeframe="1m",
                    timestamp=CHECKED_AT,
                    open=Decimal("99"),
                    high=Decimal("101"),
                    low=Decimal("98"),
                    close=Decimal("100"),
                    volume=Decimal("1000"),
                ),
            )
        }
    )
    host = build_dhan_host_runtime(_config(tmp_path, transport=transport))
    try:
        assert host.transport is transport
        assert isinstance(host.market_data, DhanMarketDataAdapter)
        candles = host.market_data.candles(
            _instrument().instrument_id,
            timeframe="1m",
            start=CHECKED_AT,
            end=CHECKED_AT,
        )
        assert len(candles) == 1
        assert candles[0].instrument == _instrument().instrument_id
        assert candles[0].timeframe == "1m"
        assert candles[0].timestamp == CHECKED_AT
        assert candles[0].open == Decimal("99")
        assert candles[0].high == Decimal("101")
        assert candles[0].low == Decimal("98")
        assert candles[0].close == Decimal("100")
        assert candles[0].volume == Decimal("1000")
    finally:
        host.close()


def test_host_restart_preserves_resolved_execution_without_redispatch(tmp_path) -> None:
    approved = _approved()
    host = build_dhan_host_runtime(_resolving_config(tmp_path, approved))
    try:
        _seed_pending(host, approved)
        first = host.start(checked_at=CHECKED_AT)

        assert host.started
        assert first.recovered == 1
        assert host.transport.submitted == ()
        assert host.transport.cancelled == ()
        before = SqliteReceiptRepository(host.runtime.database).get_by_client_order(
            approved.order.client_order_id
        )
        assert before is not None
    finally:
        host.close()

    rebuilt = build_dhan_host_runtime(_resolving_config(tmp_path, approved))
    try:
        second = rebuilt.start(checked_at=CHECKED_AT)

        assert rebuilt.started
        assert second.recovered == 0
        assert rebuilt.transport.submitted == ()
        assert rebuilt.transport.cancelled == ()
        after = SqliteReceiptRepository(rebuilt.runtime.database).get_by_client_order(
            approved.order.client_order_id
        )
        assert after is not None
        assert after == before
        assert after.receipt_id == before.receipt_id
    finally:
        rebuilt.close()
