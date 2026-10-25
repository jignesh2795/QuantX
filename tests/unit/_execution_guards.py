"""Test-only explicit LIVE pending-scope guard double."""

from __future__ import annotations

from datetime import datetime

from quantx.domain.pending_scope import PendingScopeResult, PendingScopeStatus
from quantx.domain.value_objects import AccountId, BrokerConnectionId


class ClearPendingScopeGuard:
    """Explicitly clear scope for tests focused on other execution contracts."""

    def check(
        self,
        account_id: AccountId,
        connection_id: BrokerConnectionId,
        *,
        checked_at: datetime,
    ) -> PendingScopeResult:
        return PendingScopeResult(
            account_id=account_id,
            connection_id=connection_id,
            status=PendingScopeStatus.CLEAR,
            reason="test scope guard explicitly reports clear",
            checked_at=checked_at,
        )
