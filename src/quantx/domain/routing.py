"""Capital-aware, capability-aware routing primitives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .accounts import AccountId, BrokerConnection, BrokerConnectionId, ConnectionStatus
from .constraints import ConstraintDecision, ConstraintResult, TradeConstraintInput, evaluate_broker_constraint, evaluate_capital
from .finance import AccountFinancialState, BrokerConstraint
from .instruments import Instrument
from .value_objects import Money, Quantity


class RoutingDecision(StrEnum):
    SELECT = "select"
    REJECT = "reject"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True, slots=True)
class RoutingCandidate:
    account_id: AccountId
    connection: BrokerConnection
    financial_state: AccountFinancialState
    broker_constraints: tuple[BrokerConstraint, ...] = ()


@dataclass(frozen=True, slots=True)
class RoutingResult:
    decision: RoutingDecision
    connection_id: BrokerConnectionId | None
    reason: str
    constraints: tuple[ConstraintDecision, ...] = ()


class RoutingPolicyEvaluator:
    """Select eligible broker connections without choosing credentials."""

    def evaluate(
        self,
        *,
        instrument: Instrument,
        order_value: Money,
        quantity: Quantity,
        required_margin: Money,
        candidates: Iterable[RoutingCandidate],
        required_capabilities: frozenset[str] = frozenset(),
        approval_required: bool = False,
    ) -> RoutingResult:
        candidates = tuple(candidates)
        if not candidates:
            return RoutingResult(RoutingDecision.REJECT, None, "no eligible broker connections")

        for candidate in candidates:
            connection = candidate.connection
            if not connection.enabled or connection.status is not ConnectionStatus.READY:
                continue
            if connection.account_id != candidate.account_id:
                continue
            if connection.market != instrument.market:
                continue
            if not all(connection.supports(capability) for capability in required_capabilities):
                continue

            decisions: list[ConstraintDecision] = []
            capital_decision = evaluate_capital(candidate.financial_state, required_margin)
            decisions.append(capital_decision)
            if capital_decision.result is ConstraintResult.REJECT:
                continue

            trade_input = TradeConstraintInput(
                order_value=order_value,
                quantity=quantity,
                required_margin=required_margin,
                approval_required=approval_required,
            )
            rejected = False
            approval = False
            for constraint in candidate.broker_constraints:
                decision = evaluate_broker_constraint(constraint, trade_input)
                decisions.append(decision)
                if decision.result is ConstraintResult.REJECT:
                    rejected = True
                    break
                if decision.result is ConstraintResult.REQUIRES_APPROVAL:
                    approval = True
            if rejected:
                continue

            if approval:
                return RoutingResult(
                    RoutingDecision.APPROVAL_REQUIRED,
                    connection.connection_id,
                    "eligible connection requires approval",
                    tuple(decisions),
                )

            return RoutingResult(
                RoutingDecision.SELECT,
                connection.connection_id,
                "eligible broker connection selected",
                tuple(decisions),
            )

        return RoutingResult(RoutingDecision.REJECT, None, "no candidate satisfied routing requirements")
