"""Capital allocation primitives driven by observed/configured financial state."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .deployment import CapitalAllocation, StrategyDeploymentId
from .finance import AccountFinancialState
from .value_objects import Money


@dataclass(frozen=True, slots=True)
class AllocationResult:
    deployment_id: StrategyDeploymentId
    allocated: Money
    available_after: Money


class CapitalAllocationError(ValueError):
    """Raised when an explicit allocation cannot be satisfied."""


class CapitalAllocator:
    """Resolve deployment allocation against current account financial state."""

    def allocate(
        self,
        *,
        allocation: CapitalAllocation,
        financial_state: AccountFinancialState,
    ) -> AllocationResult:
        available = financial_state.available_cash

        if allocation.amount is not None and allocation.fraction is not None:
            raise CapitalAllocationError("allocation cannot specify both amount and fraction")

        if allocation.amount is not None:
            if allocation.amount > available.amount:
                raise CapitalAllocationError("explicit allocation exceeds currently available cash")
            allocated_amount = allocation.amount
        else:
            fraction = allocation.fraction
            if fraction is None:
                raise CapitalAllocationError("allocation requires amount or fraction")
            allocated_amount = available.amount * fraction

        allocated = Money(allocated_amount, available.currency)
        remaining = Money(available.amount - allocated_amount, available.currency)
        return AllocationResult(allocation.deployment_id, allocated, remaining)
