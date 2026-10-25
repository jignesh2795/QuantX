"""Dhan C2a realized daily P&L source: explicit unavailability, never zero."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from quantx.domain.risk_evidence import EvidenceStatus, RealizedPnlSource
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.plugins.dhan.adapter import DhanBrokerAdapter
from quantx.plugins.dhan.daily_pnl import (
    DhanRealizedDailyPnlBlocker,
    DhanRealizedDailyPnlSource,
)
from quantx.plugins.dhan.models import DhanFundsSnapshot, DhanPositionsSnapshot
from quantx.plugins.dhan.transport import DEFAULT_READ_TIMEOUT_SECONDS, InMemoryDhanTransport

ACCOUNT = AccountId("acct-1")
CONNECTION = BrokerConnectionId("conn-1")
TRADING_DAY = date(2026, 1, 1)
DAY_START_AT = datetime(2026, 1, 1, 3, 45, tzinfo=UTC)  # 09:15 IST
AS_OF = datetime(2026, 1, 1, 4, 0, tzinfo=UTC)


def _source() -> DhanRealizedDailyPnlSource:
    return DhanRealizedDailyPnlSource(account_id=ACCOUNT, connection_id=CONNECTION)


def _observe(source: DhanRealizedDailyPnlSource, **overrides):
    values = {
        "trading_day": TRADING_DAY,
        "day_start_at": DAY_START_AT,
        "as_of": AS_OF,
    }
    values.update(overrides)
    return source.observe_realized_daily_pnl(**values)


def test_source_never_claims_complete_or_fabricates_zero() -> None:
    evidence = _observe(_source())

    assert evidence.completeness is EvidenceStatus.UNAVAILABLE
    assert evidence.amount is None
    assert evidence.charges_daily is None
    assert evidence.source is RealizedPnlSource.BROKER_REPORTED
    assert evidence.scope == "WHOLE_ACCOUNT"
    assert evidence.trading_day == TRADING_DAY
    assert evidence.day_start_at == DAY_START_AT
    assert evidence.as_of == AS_OF
    assert evidence.version
    assert evidence.provenance


def test_source_binds_exact_account_connection_and_broker() -> None:
    evidence = _observe(_source())

    assert evidence.account_id == ACCOUNT
    assert evidence.connection_id == CONNECTION
    assert evidence.broker_id == "dhan"


def test_source_reports_every_provider_semantic_blocker() -> None:
    evidence = _observe(_source())

    assert set(evidence.uncaptured_activity) == {
        blocker.value for blocker in DhanRealizedDailyPnlBlocker
    }
    assert evidence.covered_surfaces == ("DHAN_PROVIDER_CONTRACT_AUDIT",)


def test_empty_or_absent_provider_activity_is_not_a_zero_pnl_day() -> None:
    """The source has no empty-response path that could become authoritative zero."""

    evidence = _observe(_source())

    assert evidence.amount is None
    assert evidence.completeness is not EvidenceStatus.COMPLETE


@pytest.mark.parametrize("field", ["day_start_at", "as_of"])
def test_source_rejects_naive_session_instants(field: str) -> None:
    values = {
        "trading_day": TRADING_DAY,
        "day_start_at": DAY_START_AT,
        "as_of": AS_OF,
    }
    values[field] = values[field].replace(tzinfo=None)

    with pytest.raises(ValueError, match=f"{field} must be a timezone-aware datetime"):
        _source().observe_realized_daily_pnl(**values)


def test_source_rejects_as_of_before_session_start() -> None:
    with pytest.raises(ValueError, match="as_of must not precede day_start_at"):
        _observe(_source(), as_of=DAY_START_AT.replace(hour=3, minute=0))


def test_source_rejects_datetime_as_trading_day() -> None:
    with pytest.raises(ValueError, match="trading_day must be a date"):
        _observe(_source(), trading_day=datetime(2026, 1, 1, tzinfo=UTC))


def test_source_rejects_ist_session_date_mismatch() -> None:
    # 20:00 UTC is 01:30 IST on the next calendar day.
    with pytest.raises(ValueError, match="must match the IST session date"):
        _observe(
            _source(),
            day_start_at=datetime(2026, 1, 1, 20, 0, tzinfo=UTC),
            as_of=datetime(2026, 1, 1, 20, 30, tzinfo=UTC),
        )


def test_source_requires_canonical_account_and_connection_identity() -> None:
    with pytest.raises(ValueError, match="account_id must be AccountId"):
        DhanRealizedDailyPnlSource(account_id="acct-1", connection_id=CONNECTION)
    with pytest.raises(ValueError, match="connection_id must be BrokerConnectionId"):
        DhanRealizedDailyPnlSource(account_id=ACCOUNT, connection_id="conn-1")
    with pytest.raises(ValueError, match="broker_id must be 'dhan'"):
        DhanRealizedDailyPnlSource(
            account_id=ACCOUNT,
            connection_id=CONNECTION,
            broker_id="other-broker",
        )


class _NoIoTransport(InMemoryDhanTransport):
    def fund_limits(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> DhanFundsSnapshot:
        raise AssertionError("C2a unavailable evidence must not read funds")

    def positions(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> DhanPositionsSnapshot:
        raise AssertionError("C2a unavailable evidence must not read positions")


def test_adapter_exposes_unavailable_evidence_without_broker_io() -> None:
    adapter = DhanBrokerAdapter(
        _connection=BrokerConnectionRef(ACCOUNT, CONNECTION, "dhan", "NSE_EQ"),
        _instruments={},
        _transport=_NoIoTransport(),
        _submit_timeout=5.0,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
    )

    evidence = adapter.realized_daily_pnl_evidence(
        trading_day=TRADING_DAY,
        day_start_at=DAY_START_AT,
        as_of=AS_OF,
    )

    assert evidence.completeness is EvidenceStatus.UNAVAILABLE
    assert evidence.amount is None
    assert evidence.account_id == ACCOUNT
    assert evidence.connection_id == CONNECTION
