"""Execution-owned configured charge models with compatibility exports.

The neutral charge contracts are canonical in quantx.ports.charges.
This module re-exports those same objects for existing execution callers and
keeps the generic paper percentage model here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantx.ports.charges import (
    ChargeBreakdown,
    ChargeCalculationContext,
    ChargeComponent,
    ChargeModel,
)


@dataclass(frozen=True, slots=True)
class PercentageBpsChargeModel:
    """Configured percentage charge model expressed in basis points."""

    rate_bps: Decimal
    component_name: str = "modeled_fee"
    model_id: str = "paper.percentage_bps"
    model_version: str = "1"
    provenance: tuple[str, ...] = ("configured_simulation_profile",)

    def __post_init__(self) -> None:
        if not isinstance(self.rate_bps, Decimal):
            raise TypeError("rate_bps must be a Decimal")
        if self.rate_bps < 0:
            raise ValueError("rate_bps cannot be negative")
        if not self.component_name.strip():
            raise ValueError("component_name must not be empty")
        if not self.model_id.strip():
            raise ValueError("model_id must not be empty")
        if not self.model_version.strip():
            raise ValueError("model_version must not be empty")

    def calculate(self, context: ChargeCalculationContext) -> ChargeBreakdown:
        amount = context.transaction_value * self.rate_bps / Decimal("10000")
        return ChargeBreakdown(
            currency=context.currency,
            components=(ChargeComponent(self.component_name, amount),),
            model_id=self.model_id,
            model_version=self.model_version,
            provenance=self.provenance,
        )


__all__ = [
    "ChargeBreakdown",
    "ChargeCalculationContext",
    "ChargeComponent",
    "ChargeModel",
    "PercentageBpsChargeModel",
]
