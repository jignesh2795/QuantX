"""SQLite persistence for account identity and configured base currency."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from quantx.domain.accounts import Account, AccountRole
from quantx.domain.value_objects import AccountId

from .database import SqliteDatabase


class SqliteAccountRepository:
    """Persist account configuration without silently changing its currency.

    Account currency is durable configuration. A base-currency change cannot
    be done by overwriting the same account ID because that would relabel
    existing money; create a separately governed migration for such changes.
    """

    def __init__(self, database: SqliteDatabase) -> None:
        self._database = database

    def create(self, account: Account) -> Account:
        """Create one account; duplicate identities never overwrite existing data."""

        if type(account) is not Account:
            raise ValueError("account must be an Account")
        if type(account.account_id) is not AccountId:
            raise ValueError("account_id must be AccountId")
        if type(account.role) is not AccountRole:
            raise ValueError("account role must use AccountRole")

        created_at = datetime.now(UTC).isoformat(timespec="microseconds")
        try:
            with self._database.transaction() as connection:
                connection.execute(
                    "INSERT INTO accounts "
                    "(account_id, owner_id, display_name, role, base_currency, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        str(account.account_id),
                        account.owner_id,
                        account.display_name,
                        account.role.value,
                        account.base_currency,
                        created_at,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("account already exists or violates account schema") from exc
        return account

    def get(self, account_id: AccountId) -> Account | None:
        """Load one persisted account, validating its canonical currency and role."""

        if type(account_id) is not AccountId:
            raise ValueError("account_id must be AccountId")
        with self._database.read_transaction() as connection:
            row = connection.execute(
                "SELECT account_id, owner_id, display_name, role, base_currency "
                "FROM accounts WHERE account_id = ?",
                (str(account_id),),
            ).fetchone()
        if row is None:
            return None
        persisted_id, owner_id, display_name, role, base_currency = row
        try:
            return Account(
                account_id=AccountId(persisted_id),
                owner_id=owner_id,
                display_name=display_name,
                role=AccountRole(role),
                base_currency=base_currency,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("persisted account configuration is invalid") from exc


__all__ = ["SqliteAccountRepository"]
