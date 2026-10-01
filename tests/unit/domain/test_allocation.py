from decimal import Decimal

import pytest

from quantx.domain.allocation import CapitalAllocationError, CapitalAllocator
from quantx.domain.deployment import CapitalAllocation, StrategyDeploymentId
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.value_objects import Money


def state(amount: str) -> AccountFinancialState:
    money = Money(Decimal(amount), "INR")
    zero = Money(Decimal("0"), "INR")
    return AccountFinancialState(
        capital_source=CapitalSourceType.PAPER_CONFIGURED,
        cash_balance=money,
        available_cash=money,
        blocked_cash=zero,
        margin_used=zero,
        margin_available=money,
        buying_power=money,
    )


def test_fraction_uses_current_available_cash() -> None:
    result = CapitalAllocator().allocate(
        allocation=CapitalAllocation(
            deployment_id=StrategyDeploymentId("strategy-a"),
            fraction=Decimal("0.25"),
        ),
        financial_state=state("10000"),
    )
    assert result.allocated == Money(Decimal("2500"), "INR")
    assert result.available_after == Money(Decimal("7500"), "INR")


def test_explicit_amount_cannot_exceed_available_cash() -> None:
    with pytest.raises(CapitalAllocationError):
        CapitalAllocator().allocate(
            allocation=CapitalAllocation(
                deployment_id=StrategyDeploymentId("strategy-a"),
                amount=Decimal("10001"),
            ),
            financial_state=state("10000"),
        )
