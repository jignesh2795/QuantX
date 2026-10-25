"""Dhan C2c financial-authority assessment stays unavailable without defined semantics."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quantx.domain.accounts import Account
from quantx.domain.risk_evidence import EvidenceStatus
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.persistence.sqlite import SqliteAccountRepository, SqliteDatabase
from quantx.plugins.dhan.adapter import DhanBrokerAdapter
from quantx.plugins.dhan.financial_authority import (
    DhanFinancialAuthorityBlocker,
    DhanFinancialAuthoritySource,
)
from quantx.plugins.dhan.models import DhanFundsSnapshot, DhanPositionsSnapshot
from quantx.plugins.dhan.transport import DEFAULT_READ_TIMEOUT_SECONDS, InMemoryDhanTransport

ACCOUNT_ID = AccountId("acct-1")
CONNECTION_ID = BrokerConnectionId("conn-1")
ASSESSED_AT = datetime(2026, 1, 1, 4, 0, tzinfo=UTC)


def _account(*, account_id: AccountId = ACCOUNT_ID, currency: str = "INR") -> Account:
    return Account(account_id, "owner-1", "Primary", base_currency=currency)


def _connection(
    *, account_id: AccountId = ACCOUNT_ID, connection_id: BrokerConnectionId = CONNECTION_ID
) -> BrokerConnectionRef:
    return BrokerConnectionRef(account_id, connection_id, "dhan", "NSE_EQ")


def test_assessment_binds_persisted_currency_and_exact_connection() -> None:
    with SqliteDatabase(":memory:") as database:
        repository = SqliteAccountRepository(database)
        configured = repository.create(_account(currency="INR"))
        loaded = repository.get(ACCOUNT_ID)
        assert loaded == configured
        assert loaded is not None

        assessment = DhanFinancialAuthoritySource(
            account=loaded,
            connection=_connection(),
        ).assess(assessed_at=ASSESSED_AT)

    assert assessment.account_id == ACCOUNT_ID
    assert assessment.connection_id == CONNECTION_ID
    assert assessment.broker_id == "dhan"
    assert assessment.configured_base_currency == "INR"
    assert assessment.status is EvidenceStatus.UNAVAILABLE
    assert assessment.blockers == tuple(DhanFinancialAuthorityBlocker)


def test_assessment_never_returns_complete_financial_evidence() -> None:
    assessment = DhanFinancialAuthoritySource(
        account=_account(),
        connection=_connection(),
    ).assess(assessed_at=ASSESSED_AT)

    assert assessment.status is EvidenceStatus.UNAVAILABLE
    assert DhanFinancialAuthorityBlocker.FUND_LIMIT_CURRENCY_UNDECLARED in assessment.blockers
    assert DhanFinancialAuthorityBlocker.MARGIN_CALCULATOR_ORDER_SCOPED in assessment.blockers
    assert DhanFinancialAuthorityBlocker.COMPLETE_POSITION_BOOK_UNAVAILABLE in assessment.blockers
    assert not hasattr(assessment, "financial_state")
    assert not hasattr(assessment, "margin")


def test_assessment_rejects_naive_timestamp() -> None:
    source = DhanFinancialAuthoritySource(account=_account(), connection=_connection())
    with pytest.raises(
        ValueError,
        match="financial assessment assessed_at must be a timezone-aware datetime",
    ):
        source.assess(assessed_at=ASSESSED_AT.replace(tzinfo=None))


def test_source_rejects_account_connection_mismatch() -> None:
    with pytest.raises(ValueError, match="does not match broker connection"):
        DhanFinancialAuthoritySource(
            account=_account(account_id=AccountId("acct-other")),
            connection=_connection(),
        )


def test_source_rejects_non_dhan_connection() -> None:
    with pytest.raises(ValueError, match="requires a Dhan connection"):
        DhanFinancialAuthoritySource(
            account=_account(),
            connection=BrokerConnectionRef(ACCOUNT_ID, CONNECTION_ID, "other", "NSE_EQ"),
        )


class _NoIoTransport(InMemoryDhanTransport):
    def fund_limits(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> DhanFundsSnapshot:
        raise AssertionError("financial-authority assessment must not query fund limits")

    def positions(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> DhanPositionsSnapshot:
        raise AssertionError("financial-authority assessment must not query positions")


def test_adapter_exposes_assessment_without_broker_io() -> None:
    adapter = DhanBrokerAdapter(
        _connection=_connection(),
        _instruments={},
        _transport=_NoIoTransport(),
        _submit_timeout=5.0,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
    )
    assessment = adapter.financial_authority_assessment(
        account=_account(),
        assessed_at=ASSESSED_AT,
    )
    assert assessment.status is EvidenceStatus.UNAVAILABLE
    assert assessment.configured_base_currency == "INR"
