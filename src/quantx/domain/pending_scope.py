"""Neutral pending-submission scope contracts shared by application and persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from .value_objects import AccountId, BrokerConnectionId


class PendingScopeStatus(StrEnum):
    CLEAR = "CLEAR"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PendingScopeResult:
    account_id: AccountId
    connection_id: BrokerConnectionId
    status: PendingScopeStatus
    reason: str
    checked_at: datetime

    def __post_init__(self) -> None:
        if type(self.account_id) is not AccountId:
            raise ValueError("pending scope account_id must be AccountId")
        if type(self.connection_id) is not BrokerConnectionId:
            raise ValueError("pending scope connection_id must be BrokerConnectionId")
        if type(self.status) is not PendingScopeStatus:
            raise ValueError("pending scope status must use PendingScopeStatus")
        if (
            type(self.checked_at) is not datetime
            or self.checked_at.tzinfo is None
            or self.checked_at.utcoffset() is None
        ):
            raise ValueError("pending scope checked_at must be timezone-aware")
        if type(self.reason) is not str or not self.reason.strip():
            raise ValueError("pending scope result reason is required")


@runtime_checkable
class PendingScopeGuard(Protocol):
    """Durable scope-aware guard; UNKNOWN is never approval."""

    def check(
        self,
        account_id: AccountId,
        connection_id: BrokerConnectionId,
        *,
        checked_at: datetime,
    ) -> PendingScopeResult: ...


__all__ = ["PendingScopeGuard", "PendingScopeResult", "PendingScopeStatus"]
