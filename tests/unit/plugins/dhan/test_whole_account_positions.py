"""Dhan C2b whole-account position evidence capability remains fail-closed."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from quantx.domain.risk_evidence import EvidenceStatus
from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.plugins.dhan.adapter import DhanBrokerAdapter
from quantx.plugins.dhan.models import (
    DhanFundsSnapshot,
    DhanPositionsSnapshot,
    DhanQuoteSnapshot,
)
from quantx.plugins.dhan.transport import (
    DEFAULT_READ_TIMEOUT_SECONDS,
    InMemoryDhanTransport,
)
from quantx.plugins.dhan.whole_account_positions import (
    DhanWholeAccountPositionEvidenceBlocker,
    DhanWholeAccountPositionEvidenceSource,
)

ACCOUNT = AccountId("acct-1")
CONNECTION = BrokerConnectionId("conn-1")
ASSESSED_AT = datetime(2026, 1, 1, 4, 0, tzinfo=UTC)


def _source() -> DhanWholeAccountPositionEvidenceSource:
    return DhanWholeAccountPositionEvidenceSource(
        account_id=ACCOUNT,
        connection_id=CONNECTION,
    )


def test_source_reports_unavailable_capability_not_an_empty_position_book() -> None:
    assessment = _source().assess(assessed_at=ASSESSED_AT)

    assert assessment.status is EvidenceStatus.UNAVAILABLE
    assert assessment.account_id == ACCOUNT
    assert assessment.connection_id == CONNECTION
    assert assessment.broker_id == "dhan"
    assert assessment.assessed_at == ASSESSED_AT
    assert assessment.blockers == tuple(DhanWholeAccountPositionEvidenceBlocker)
    assert assessment.version
    assert assessment.provenance


def test_blockers_cover_overlap_product_mapping_and_mark_authority() -> None:
    assessment = _source().assess(assessed_at=ASSESSED_AT)

    assert set(assessment.blockers) == {
        DhanWholeAccountPositionEvidenceBlocker.POSITION_HOLDINGS_OVERLAP_UNDEFINED,
        DhanWholeAccountPositionEvidenceBlocker.HOLDINGS_PRODUCT_IDENTITY_UNAVAILABLE,
        DhanWholeAccountPositionEvidenceBlocker.CANONICAL_MAPPING_COVERAGE_UNPROVEN,
        DhanWholeAccountPositionEvidenceBlocker.DATA_API_MARK_ENTITLEMENT_REQUIRED,
        DhanWholeAccountPositionEvidenceBlocker.MARK_TIMESTAMP_COVERAGE_UNPROVEN,
        DhanWholeAccountPositionEvidenceBlocker.WHOLE_BOOK_COMPLETENESS_UNPROVEN,
    }


def test_source_rejects_naive_assessment_time() -> None:
    with pytest.raises(ValueError, match="assessed_at must be a timezone-aware datetime"):
        _source().assess(assessed_at=ASSESSED_AT.replace(tzinfo=None))


@pytest.mark.parametrize(
    ("account_id", "connection_id"),
    [
        ("acct-1", CONNECTION),
        (ACCOUNT, "conn-1"),
    ],
)
def test_source_rejects_noncanonical_scope_identity(
    account_id: object,
    connection_id: object,
) -> None:
    with pytest.raises(ValueError):
        DhanWholeAccountPositionEvidenceSource(
            account_id=account_id,  # type: ignore[arg-type]
            connection_id=connection_id,  # type: ignore[arg-type]
        )


class _NoReadTransport(InMemoryDhanTransport):
    def positions(
        self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS
    ) -> DhanPositionsSnapshot:
        raise AssertionError("C2b capability assessment must not query positions")

    def fund_limits(
        self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS
    ) -> DhanFundsSnapshot:
        raise AssertionError("C2b capability assessment must not query account state")

    def quote_snapshot(
        self,
        security_id: str,
        exchange_segment: str,
        *,
        timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> DhanQuoteSnapshot | None:
        raise AssertionError("C2b capability assessment must not request market data")


def test_adapter_exposes_fail_closed_assessment_without_broker_io() -> None:
    adapter = DhanBrokerAdapter(
        _connection=BrokerConnectionRef(ACCOUNT, CONNECTION, "dhan", "NSE_EQ"),
        _instruments={},
        _transport=_NoReadTransport(),
        _submit_timeout=5.0,
        _cancel_timeout=5.0,
        _reconcile_timeout=5.0,
    )

    assessment = adapter.assess_whole_account_position_evidence(assessed_at=ASSESSED_AT)

    assert assessment.status is EvidenceStatus.UNAVAILABLE
    assert assessment.account_id == ACCOUNT
    assert assessment.connection_id == CONNECTION
    assert DhanWholeAccountPositionEvidenceBlocker.POSITION_HOLDINGS_OVERLAP_UNDEFINED in (
        assessment.blockers
    )
