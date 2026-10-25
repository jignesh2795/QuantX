"""Fail-closed Dhan account-currency and margin-authority assessment (Slice C2c).

This module reports contract-level blockers rather than converting Dhan fund-limit
values into a fabricated C1 financial state. The persisted account currency is a
configuration binding; the current Dhan fund-limit schema does not echo currency
or a provider observation instant, and margin-calculator results do not establish
a complete account financial snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from quantx.domain.accounts import Account
from quantx.domain.risk_evidence import EvidenceStatus
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.brokers import BrokerConnectionRef


class DhanFinancialAuthorityBlocker(StrEnum):
    """Reasons Dhan's current contract cannot establish complete C1 finance evidence."""

    FUND_LIMIT_CURRENCY_UNDECLARED = "DHAN_FUND_LIMIT_CURRENCY_UNDECLARED"
    FUND_LIMIT_PROVIDER_TIMESTAMP_UNAVAILABLE = "DHAN_FUND_LIMIT_PROVIDER_TIMESTAMP_UNAVAILABLE"
    ACCOUNT_CURRENCY_NOT_BROKER_BOUND = "DHAN_ACCOUNT_CURRENCY_NOT_BROKER_BOUND"
    ACCOUNT_CASH_EQUITY_INCOMPLETE = "DHAN_ACCOUNT_CASH_EQUITY_INCOMPLETE"
    AVAILABLE_BALANCE_NOT_MARGIN_AVAILABLE = "DHAN_AVAILABLE_BALANCE_NOT_MARGIN_AVAILABLE"
    UTILIZED_AMOUNT_SEMANTICS_UNPROVEN = "DHAN_UTILIZED_AMOUNT_SEMANTICS_UNPROVEN"
    FUND_LIMIT_ACCOUNT_ID_NOT_PRESERVED = "DHAN_FUND_LIMIT_ACCOUNT_ID_NOT_PRESERVED"
    MARGIN_CALCULATOR_ORDER_SCOPED = "DHAN_MARGIN_CALCULATOR_ORDER_SCOPED"
    MARGIN_CALCULATOR_INDICATIVE = "DHAN_MARGIN_CALCULATOR_INDICATIVE"
    COMPLETE_POSITION_BOOK_UNAVAILABLE = "DHAN_COMPLETE_POSITION_BOOK_UNAVAILABLE"
    REALIZED_DAILY_PNL_UNAVAILABLE = "DHAN_REALIZED_DAILY_PNL_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class DhanFinancialAuthorityAssessment:
    """Account-bound capability assessment, never a monetary evidence record."""

    account_id: AccountId
    connection_id: BrokerConnectionId
    broker_id: str
    configured_base_currency: str
    assessed_at: datetime
    status: EvidenceStatus
    blockers: tuple[DhanFinancialAuthorityBlocker, ...]
    version: str
    provenance: str

    def __post_init__(self) -> None:
        if type(self.account_id) is not AccountId:
            raise ValueError("financial assessment account_id must be AccountId")
        if type(self.connection_id) is not BrokerConnectionId:
            raise ValueError("financial assessment connection_id must be BrokerConnectionId")
        if type(self.broker_id) is not str or self.broker_id != "dhan":
            raise ValueError("financial assessment broker_id must be 'dhan'")
        if (
            type(self.configured_base_currency) is not str
            or len(self.configured_base_currency) != 3
            or not self.configured_base_currency.isascii()
            or not self.configured_base_currency.isalpha()
            or self.configured_base_currency != self.configured_base_currency.upper()
        ):
            raise ValueError("configured_base_currency must be a three-letter uppercase code")
        _require_aware(self.assessed_at, "financial assessment assessed_at")
        if type(self.status) is not EvidenceStatus or self.status is not EvidenceStatus.UNAVAILABLE:
            raise ValueError("Dhan financial-authority assessment must remain UNAVAILABLE")
        if type(self.blockers) is not tuple or not self.blockers:
            raise ValueError("financial assessment requires explicit blockers")
        if any(type(item) is not DhanFinancialAuthorityBlocker for item in self.blockers):
            raise ValueError("financial assessment blockers must use the canonical enum")
        if not self.version.strip() or not self.provenance.strip():
            raise ValueError("financial assessment version and provenance are required")


@dataclass(frozen=True, slots=True)
class DhanFinancialAuthoritySource:
    """Dhan-scoped assessment bound to persisted account configuration and connection."""

    account: Account
    connection: BrokerConnectionRef
    version: str = "dhan-financial-authority-c2c-v1"
    provenance: str = "dhan-v2-fund-limit-and-margin-contract-audit"

    def __post_init__(self) -> None:
        if type(self.account) is not Account:
            raise ValueError("financial authority source requires canonical Account")
        if type(self.connection) is not BrokerConnectionRef:
            raise ValueError("financial authority source requires BrokerConnectionRef")
        if self.account.account_id != self.connection.account_id:
            raise ValueError("financial authority account does not match broker connection")
        if self.connection.broker_id != "dhan":
            raise ValueError("financial authority source requires a Dhan connection")
        if not self.version.strip() or not self.provenance.strip():
            raise ValueError("financial authority source version and provenance are required")

    def assess(self, *, assessed_at: datetime) -> DhanFinancialAuthorityAssessment:
        """Return all known financial-authority gaps without broker I/O."""

        _require_aware(assessed_at, "financial assessment assessed_at")
        return DhanFinancialAuthorityAssessment(
            account_id=self.account.account_id,
            connection_id=self.connection.connection_id,
            broker_id=self.connection.broker_id,
            configured_base_currency=self.account.base_currency,
            assessed_at=assessed_at,
            status=EvidenceStatus.UNAVAILABLE,
            blockers=tuple(DhanFinancialAuthorityBlocker),
            version=self.version,
            provenance=self.provenance,
        )


def _require_aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


__all__ = [
    "DhanFinancialAuthorityAssessment",
    "DhanFinancialAuthorityBlocker",
    "DhanFinancialAuthoritySource",
]
