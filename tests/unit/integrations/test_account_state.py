from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from quantx.integrations.account_state import (
    AccountFinancialState,
    AccountReconciler,
    ReconciliationStatus,
    StateSource,
)


def test_reconciliation_matches_explicit_observed_state() -> None:
    account_id = uuid4()
    connection_id = uuid4()
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
    report = AccountReconciler().compare(state, state)
    assert report.status is ReconciliationStatus.MATCHED


def test_reconciliation_never_invents_missing_observed_state() -> None:
    state = AccountFinancialState(
        account_id=uuid4(),
        connection_id=uuid4(),
        observed_at=datetime.now(timezone.utc),
        source=StateSource.PAPER,
        currency="USD",
        available_cash=Decimal("100"),
    )
    report = AccountReconciler().compare(state, None)
    assert report.status is ReconciliationStatus.UNAVAILABLE


def test_negative_financial_values_are_rejected() -> None:
    with pytest.raises(ValueError):
        AccountFinancialState(
            account_id=uuid4(),
            connection_id=uuid4(),
            observed_at=datetime.now(timezone.utc),
            source=StateSource.BROKER,
            currency="USD",
            equity=Decimal("-1"),
        )
