"""Contract tests for realized daily P&L evidence."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from quantx.domain.risk_evidence import (
    EvidenceStatus,
    PositionSurface,
    PositionSurfaceEvidence,
    RealizedDailyPnlEvidence,
    RealizedPnlSource,
    WholeAccountPositionEvidence,
)
from quantx.domain.value_objects import AccountId, BrokerConnectionId, Money

ACCOUNT = AccountId("acct-1")
CONNECTION = BrokerConnectionId("conn-1")
TRADING_DAY = date(2026, 1, 1)
DAY_START_AT = datetime(2026, 1, 1, 3, 45, tzinfo=UTC)
AS_OF = datetime(2026, 1, 1, 4, 0, tzinfo=UTC)


def _pnl(**overrides: Any) -> RealizedDailyPnlEvidence:
    values: dict[str, Any] = {
        "account_id": ACCOUNT,
        "connection_id": CONNECTION,
        "broker_id": "dhan",
        "trading_day": TRADING_DAY,
        "day_start_at": DAY_START_AT,
        "as_of": AS_OF,
        "amount": Money(Decimal("2500"), "INR"),
        "charges_daily": Money(Decimal("0"), "INR"),
        "source": RealizedPnlSource.BROKER_REPORTED,
        "scope": "WHOLE_ACCOUNT",
        "completeness": EvidenceStatus.COMPLETE,
        "covered_surfaces": ("synthetic-test-fixture",),
        "uncaptured_activity": (),
        "version": "synthetic-v1",
        "provenance": "synthetic-test-fixture",
    }
    values.update(overrides)
    return RealizedDailyPnlEvidence(**values)


def test_complete_evidence_requires_a_money_amount() -> None:
    with pytest.raises(ValueError, match="COMPLETE P&L evidence requires a Money amount"):
        _pnl(amount=None, charges_daily=None)


def test_unavailable_evidence_may_omit_amount_and_charges() -> None:
    evidence = _pnl(
        amount=None,
        charges_daily=None,
        completeness=EvidenceStatus.UNAVAILABLE,
    )

    assert evidence.amount is None
    assert evidence.charges_daily is None


def test_non_complete_evidence_must_not_carry_an_amount() -> None:
    with pytest.raises(ValueError, match="non-COMPLETE P&L evidence must not carry an amount"):
        _pnl(completeness=EvidenceStatus.INCOMPLETE)


def test_non_complete_evidence_must_not_carry_daily_charges() -> None:
    with pytest.raises(ValueError, match="non-COMPLETE P&L evidence must not carry daily charges"):
        _pnl(amount=None, completeness=EvidenceStatus.INCOMPLETE)


def test_amount_must_be_money_when_supplied() -> None:
    with pytest.raises(ValueError, match="P&L amount must use Money"):
        _pnl(amount=Decimal("2500"))


def test_non_finite_amount_is_rejected() -> None:
    with pytest.raises(ValueError, match="P&L amount must be a finite Decimal"):
        _pnl(amount=Money(Decimal("NaN"), "INR"))


def test_daily_charges_must_not_be_negative() -> None:
    with pytest.raises(ValueError, match="daily charges must not be negative"):
        _pnl(charges_daily=Money(Decimal("-1"), "INR"))


def test_daily_charges_currency_must_match_pnl_currency() -> None:
    with pytest.raises(ValueError, match="daily charges and P&L must use the same currency"):
        _pnl(charges_daily=Money(Decimal("1"), "USD"))


def test_naive_day_start_is_rejected() -> None:
    with pytest.raises(ValueError, match="P&L day_start_at must be a timezone-aware datetime"):
        _pnl(day_start_at=datetime(2026, 1, 1, 3, 45))


def test_as_of_must_not_precede_day_start() -> None:
    with pytest.raises(ValueError, match="P&L as_of must not precede day_start_at"):
        _pnl(as_of=DAY_START_AT.replace(hour=3, minute=0))


def _position_book(**overrides: Any) -> WholeAccountPositionEvidence:
    surfaces = (
        PositionSurfaceEvidence(
            PositionSurface.POSITIONS,
            EvidenceStatus.COMPLETE,
            AS_OF,
            "synthetic-v1",
            "synthetic-test-fixture",
            0,
        ),
        PositionSurfaceEvidence(
            PositionSurface.HOLDINGS,
            EvidenceStatus.COMPLETE,
            AS_OF,
            "synthetic-v1",
            "synthetic-test-fixture",
            0,
        ),
        PositionSurfaceEvidence(
            PositionSurface.MARKS,
            EvidenceStatus.COMPLETE,
            AS_OF,
            "synthetic-v1",
            "synthetic-test-fixture",
            0,
        ),
    )
    values: dict[str, Any] = {
        "account_id": ACCOUNT,
        "connection_id": CONNECTION,
        "surfaces": surfaces,
        "positions": (),
        "completeness": EvidenceStatus.COMPLETE,
        "merge_policy": "synthetic-no-overlap-v1",
        "observed_at": AS_OF,
        "version": "synthetic-v1",
        "provenance": "synthetic-test-fixture",
        "blockers": (),
    }
    values.update(overrides)
    return WholeAccountPositionEvidence(**values)


def test_position_book_blockers_default_to_empty_tuple() -> None:
    assert _position_book().blockers == ()


def test_non_complete_position_book_preserves_explicit_blockers() -> None:
    book = _position_book(
        completeness=EvidenceStatus.INCOMPLETE,
        blockers=("DHAN_HOLDINGS_PRODUCT_IDENTITY_UNPROVEN",),
    )

    assert book.blockers == ("DHAN_HOLDINGS_PRODUCT_IDENTITY_UNPROVEN",)


def test_position_book_rejects_complete_status_with_blockers() -> None:
    with pytest.raises(ValueError, match="COMPLETE position evidence must not declare blockers"):
        _position_book(blockers=("synthetic-provider-gap",))


def test_position_book_rejects_mutable_blocker_collection() -> None:
    with pytest.raises(ValueError, match="position blockers must be an immutable tuple"):
        _position_book(
            completeness=EvidenceStatus.INCOMPLETE,
            blockers=["synthetic-provider-gap"],
        )


@pytest.mark.parametrize("blocker", ["", "   ", 1])
def test_position_book_rejects_malformed_blocker_values(blocker: object) -> None:
    with pytest.raises(ValueError, match="position blockers must be non-empty strings"):
        _position_book(completeness=EvidenceStatus.INCOMPLETE, blockers=(blocker,))
