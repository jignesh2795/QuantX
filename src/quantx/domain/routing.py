"""Capital-aware, capability-aware routing primitives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from .accounts import AccountId, BrokerConnection, BrokerConnectionId, ConnectionStatus
from .constraints import ConstraintResult
from .finance import AccountFinancialState, BrokerConstraint
from .instruments import Instrument


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
    constraints: tuple[ConstraintResult, ...] = ()


class RoutingPolicyEvaluator:
    """Select eligible broker connections without choosing credentials."""

    def evaluate(
        self,
        *,
        instrument: Instrument,
        candidates: Iterable[RoutingCandidate],
        required_capabilities: frozenset[str] = frozenset(),
    ) -> RoutingResult:
        candidates = tuple(candidates)
        if not candidates:
            return RoutingResult(RoutingDecision.REJECT, None, "no eligible broker connections")

        for candidate in candidates:
            connection = candidate.connection
            if not connection.enabled or connection.status is not ConnectionStatus.READY:
                continue
            if not all(connection.supports(capability) for capability in required_capabilities):
                continue
            if connection.account_id != candidate.account_id:
                continue
            if connection.market != instrument.market:
                continue
            return RoutingResult(
                RoutingDecision.SELECT,
                connection.connection_id,
                "eligible broker connection selected",
            )

        return RoutingResult(RoutingDecision.REJECT, None, "no candidate satisfied routing requirements")
