"""Pre-trade risk evaluation for TradeIntent objects.

The first implementation deliberately evaluates only deterministic domain
constraints. Execution-time and post-trade risk can be layered on later.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from .constraints import ConstraintDecision, ConstraintResult, TradeConstraintInput, evaluate_broker_constraint, evaluate_capital
from .finance import AccountFinancialState, BrokerConstraint
from .instruments import Instrument
from .order_intents import TradeIntent
from .value_objects import Money, Quantity


class RiskDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True, slots=True)
class RiskContext:
    instrument: Instrument
    financial_state: AccountFinancialState
    broker_constraints: tuple[BrokerConstraint, ...] = ()
    reference_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RiskResult:
    decision: RiskDecision
    reason: str
    constraints: tuple[ConstraintDecision, ...] = ()


class PreTradeRiskEngine:
    """Evaluate whether a TradeIntent may proceed to order construction."""

    def evaluate(self, intent: TradeIntent, context: RiskContext) -> RiskResult:
        if intent.execution_context is None:
            return RiskResult(RiskDecision.REJECT, "execution context is required")

        required_margin = Money(
            intent.required_margin,
            context.financial_state.margin_available.currency,
        )
        decisions: list[ConstraintDecision] = [
            evaluate_capital(context.financial_state, required_margin)
        ]
        if decisions[-1].result is ConstraintResult.REJECT:
            return RiskResult(RiskDecision.REJECT, decisions[-1].reason, tuple(decisions))

        order_value = intent.estimated_order_value
        if order_value is None:
            if context.reference_price is None:
                return RiskResult(
                    RiskDecision.REJECT,
                    "order value cannot be determined without estimated value or reference price",
                    tuple(decisions),
                )
            order_value = intent.quantity * context.reference_price * context.instrument.multiplier

        money_order_value = Money(order_value, context.financial_state.available_cash.currency)
        trade_input = TradeConstraintInput(
            order_value=money_order_value,
            quantity=Quantity(intent.quantity),
            required_margin=required_margin,
            approval_required=intent.approval_required,
        )

        for constraint in context.broker_constraints:
            decision = evaluate_broker_constraint(constraint, trade_input)
            decisions.append(decision)
            if decision.result is ConstraintResult.REJECT:
                return RiskResult(RiskDecision.REJECT, decision.reason, tuple(decisions))

        if intent.approval_required or any(
            decision.result is ConstraintResult.REQUIRES_APPROVAL for decision in decisions
        ):
            return RiskResult(
                RiskDecision.APPROVAL_REQUIRED,
                "explicit approval is required before execution",
                tuple(decisions),
            )

        return RiskResult(RiskDecision.APPROVE, "pre-trade risk checks passed", tuple(decisions))
