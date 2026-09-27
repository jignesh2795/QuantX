from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.reconciliation import (
    AccountFinancialState,
    AccountReconciler,
    AccountReconciliationStatus,
    StateSource,
)


def test_reconciliation_matches_explicit_observed_state() -> None:
    account_id = AccountId("acct-1")
    connection_id = BrokerConnectionId("conn-1")
    now = datetime.now(timezone.utc)
    state = AccountFinancialState(
        account_id=account_id,
        connection_id=connection_id,
        observed_at=now,
        source=StateSource.PAPER,
        currency="USD",
        available_cash=Decimal("100"),
        equity=Decimal("100"),
    )
    report = AccountReconciler().compare(
        state,
        state,
        checked_at=now,
        max_state_age=timedelta(seconds=30),
    )
    assert report.status is AccountReconciliationStatus.MATCHED


def test_reconciliation_never_invents_missing_observed_state() -> None:
    state = AccountFinancialState(
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        observed_at=datetime.now(timezone.utc),
        source=StateSource.PAPER,
        currency="USD",
        available_cash=Decimal("100"),
    )
    report = AccountReconciler().compare(
        state,
        None,
        checked_at=state.observed_at,
        max_state_age=timedelta(seconds=30),
    )
    assert report.status is AccountReconciliationStatus.UNAVAILABLE


def test_future_observed_account_state_is_stale() -> None:
    checked_at = datetime.now(timezone.utc)
    observed = AccountFinancialState(
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        observed_at=checked_at + timedelta(minutes=1),
        source=StateSource.BROKER,
        currency="USD",
        available_cash=Decimal("100"),
    )
    local = AccountFinancialState(
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        observed_at=checked_at,
        source=StateSource.PAPER,
        currency="USD",
        available_cash=Decimal("100"),
    )

    report = AccountReconciler().compare(
        local,
        observed,
        checked_at=checked_at,
        max_state_age=timedelta(seconds=30),
    )

    assert report.status is AccountReconciliationStatus.STALE
    assert "future-dated" in report.findings[0].message


def test_negative_financial_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        AccountFinancialState(
            account_id=AccountId("acct-1"),
            connection_id=BrokerConnectionId("conn-1"),
            observed_at=datetime.now(timezone.utc),
            source=StateSource.BROKER,
            currency="USD",
            equity=Decimal("-1"),
        )
