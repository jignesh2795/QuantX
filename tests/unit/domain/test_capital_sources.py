from decimal import Decimal

import pytest

from quantx.domain.accounts import (
    BrokerConnectionId,
    CapitalSource,
    CapitalSourceType,
)
from quantx.domain.value_objects import Money


def test_live_capital_requires_broker_connection_and_no_fixed_balance() -> None:
    source = CapitalSource(
        source_type=CapitalSourceType.LIVE_BROKER,
        connection_id=BrokerConnectionId("dhan-main"),
    )

    assert source.configured_balance is None


def test_paper_capital_uses_explicit_configured_balance() -> None:
    balance = Money(Decimal("2500"), "INR")
    source = CapitalSource(
        source_type=CapitalSourceType.PAPER_CONFIGURED,
        configured_balance=balance,
    )

    assert source.configured_balance == balance


def test_live_capital_cannot_contain_paper_balance() -> None:
    with pytest.raises(ValueError):
        CapitalSource(
            source_type=CapitalSourceType.LIVE_BROKER,
            connection_id=BrokerConnectionId("dhan-main"),
            configured_balance=Money(Decimal("10000"), "INR"),
        )


def test_paper_capital_must_be_non_negative() -> None:
    with pytest.raises(ValueError):
        CapitalSource(
            source_type=CapitalSourceType.PAPER_CONFIGURED,
            configured_balance=Money(Decimal("-1"), "INR"),
        )
