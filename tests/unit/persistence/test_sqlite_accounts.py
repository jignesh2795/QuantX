"""SQLite account configuration and base-currency persistence tests."""

from __future__ import annotations

import sqlite3

import pytest

from quantx.domain.accounts import Account, AccountId, AccountRole
from quantx.persistence.sqlite import SqliteAccountRepository, SqliteDatabase
from quantx.persistence.sqlite.schema import SCHEMA_VERSION


def _account(
    *,
    account_id: str = "acct-1",
    owner_id: str = "owner-1",
    display_name: str = "Primary",
    role: AccountRole = AccountRole.PRIMARY,
    base_currency: str = "INR",
) -> Account:
    return Account(
        AccountId(account_id),
        owner_id,
        display_name,
        role,
        base_currency,
    )


def test_account_repository_persists_currency_and_profile() -> None:
    with SqliteDatabase(":memory:") as database:
        repository = SqliteAccountRepository(database)
        original = _account(role=AccountRole.MEMBER, base_currency="INR")

        created = repository.create(original)
        loaded = repository.get(AccountId("acct-1"))

    assert created == original
    assert loaded == original
    assert loaded is not None
    assert loaded.base_currency == "INR"


def test_account_repository_does_not_overwrite_currency_on_duplicate_id() -> None:
    with SqliteDatabase(":memory:") as database:
        repository = SqliteAccountRepository(database)
        repository.create(_account(base_currency="INR"))

        with pytest.raises(ValueError, match="account already exists"):
            repository.create(_account(base_currency="USD"))

        assert repository.get(AccountId("acct-1")) == _account(base_currency="INR")


def test_account_repository_returns_none_for_unknown_account() -> None:
    with SqliteDatabase(":memory:") as database:
        repository = SqliteAccountRepository(database)
        assert repository.get(AccountId("missing")) is None


def test_account_repository_rejects_noncanonical_account_or_id() -> None:
    with SqliteDatabase(":memory:") as database:
        repository = SqliteAccountRepository(database)
        with pytest.raises(ValueError, match="account must be an Account"):
            repository.create(object())  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="account_id must be AccountId"):
            repository.get("acct-1")  # type: ignore[arg-type]


def test_corrupt_persisted_currency_fails_closed(tmp_path) -> None:
    path = tmp_path / "quantx.db"
    with SqliteDatabase(path) as database:
        repository = SqliteAccountRepository(database)
        repository.create(_account())

    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA ignore_check_constraints = ON")
        connection.execute("UPDATE accounts SET base_currency = 'usd' WHERE account_id = 'acct-1'")
        connection.commit()
    finally:
        connection.close()

    with SqliteDatabase(path) as database:
        with pytest.raises(ValueError, match="persisted account configuration is invalid"):
            SqliteAccountRepository(database).get(AccountId("acct-1"))


def test_schema_v9_is_current() -> None:
    with SqliteDatabase(":memory:") as database:
        version = database.connection().execute("SELECT version FROM schema_version").fetchone()[0]
        assert version == SCHEMA_VERSION == 10
