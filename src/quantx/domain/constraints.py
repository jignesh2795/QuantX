"""Trade constraint evaluation primitives."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .finance import AccountFinancialState, BrokerConstraint
from .value_objects import Money, Quantity


class ConstraintResult(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    REJECT = "REJECT"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"


@dataclass(frozen=True, slots=True)
class ConstraintDecision:
    result: ConstraintResult
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class TradeConstraintInput:
    order_value: Money
    quantity: Quantity
    required_margin: Money | None = None
    approval_required: bool = False


def evaluate_broker_constraint(
    constraint: BrokerConstraint,
    candidate: TradeConstraintInput,
) -> ConstraintDecision:
    if constraint.minimum_order_value is not None and candidate.order_value.amount < constraint.minimum_order_value:
        return ConstraintDecision(
            ConstraintResult.REJECT,
            constraint.name,
            "order value is below the broker/venue minimum",
        )

    if constraint.minimum_quantity is not None and candidate.quantity.value < constraint.minimum_quantity:
        return ConstraintDecision(
            ConstraintResult.REJECT,
            constraint.name,
            "quantity is below the broker/venue minimum",
        )

    if (
        constraint.minimum_margin is not None
        and candidate.required_margin is not None
        and candidate.required_margin.amount < constraint.minimum_margin.amount
    ):
        return ConstraintDecision(
            ConstraintResult.REJECT,
            constraint.name,
            "required margin does not satisfy the declared broker constraint",
        )

    if candidate.approval_required:
        return ConstraintDecision(
            ConstraintResult.REQUIRES_APPROVAL,
            constraint.name,
            "explicit approval policy is required",
        )

    return ConstraintDecision(ConstraintResult.PASS, constraint.name, "constraint satisfied")


def evaluate_capital(
    financial_state: AccountFinancialState,
    required_margin: Money,
) -> ConstraintDecision:
    if required_margin.currency != financial_state.margin_available.currency:
        return ConstraintDecision(
            ConstraintResult.REJECT,
            "capital_currency",
            "required margin currency does not match account financial state",
        )

    if required_margin.amount > financial_state.margin_available.amount:
        return ConstraintDecision(
            ConstraintResult.REJECT,
            "margin_available",
            "required margin exceeds currently available margin",
        )

    return ConstraintDecision(ConstraintResult.PASS, "margin_available", "sufficient available margin")
