from decimal import Decimal

from quantx.domain.constraints import (
    ConstraintResult,
    TradeConstraintInput,
    evaluate_broker_constraint,
    evaluate_capital,
)
from quantx.domain.finance import AccountFinancialState, BrokerConstraint, CapitalSourceType
from quantx.domain.value_objects import Money, Quantity


def test_broker_minimum_is_explicit_constraint() -> None:
    constraint = BrokerConstraint(
        name="broker-minimum-order",
        description="venue requires minimum order value",
        minimum_order_value=Decimal("100"),
    )
    candidate = TradeConstraintInput(
        order_value=Money(Decimal("50"), "INR"),
        quantity=Quantity(Decimal("1")),
    )

    decision = evaluate_broker_constraint(constraint, candidate)

    assert decision.result == ConstraintResult.REJECT


def test_no_universal_minimum_capital_is_injected() -> None:
    state = AccountFinancialState(
        capital_source=CapitalSourceType.PAPER_CONFIGURED,
        cash_balance=Money(Decimal("25"), "INR"),
        available_cash=Money(Decimal("25"), "INR"),
        blocked_cash=Money(Decimal("0"), "INR"),
        margin_used=Money(Decimal("0"), "INR"),
        margin_available=Money(Decimal("25"), "INR"),
        buying_power=Money(Decimal("25"), "INR"),
    )

    decision = evaluate_capital(state, Money(Decimal("20"), "INR"))

    assert decision.result == ConstraintResult.PASS
