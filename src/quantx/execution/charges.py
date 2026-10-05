"""Deterministic transaction-cost contracts for paper and research execution.

This module models explicit, configured transaction charges. It deliberately
does not encode broker tariffs, taxes, exchange schedules, or other
market-specific rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ChargeCalculationContext:
    """Explicit monetary basis supplied to a transaction-cost model."""

    transaction_value: Decimal
    currency: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.transaction_value, Decimal):
            raise TypeError("transaction_value must be a Decimal")
        if self.transaction_value < 0:
            raise ValueError("transaction_value cannot be negative")
        if self.currency is not None and not self.currency.strip():
            raise ValueError("currency must not be empty when provided")


@dataclass(frozen=True, slots=True)
class ChargeComponent:
    """One named component of a transaction-cost breakdown."""

    name: str
    amount: Decimal

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("charge component name must not be empty")
        if not isinstance(self.amount, Decimal):
            raise TypeError("charge component amount must be a Decimal")
        if self.amount < 0:
            raise ValueError("charge component amount cannot be negative")


@dataclass(frozen=True, slots=True)
class ChargeBreakdown:
    """Immutable, auditable transaction-cost result."""

    currency: str | None
    components: tuple[ChargeComponent, ...]
    model_id: str
    model_version: str
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.currency is not None and not self.currency.strip():
            raise ValueError("currency must not be empty when provided")
        if not self.model_id.strip():
            raise ValueError("model_id must not be empty")
        if not self.model_version.strip():
            raise ValueError("model_version must not be empty")
        names = [component.name for component in self.components]
        if len(names) != len(set(names)):
            raise ValueError("charge component names must be unique")

    @property
    def total(self) -> Decimal:
        return sum((component.amount for component in self.components), Decimal("0"))

    @classmethod
    def zero(
        cls,
        *,
        model_id: str = "none",
        model_version: str = "0",
        currency: str | None = None,
        provenance: tuple[str, ...] = (),
    ) -> ChargeBreakdown:
        return cls(
            currency=currency,
            components=(),
            model_id=model_id,
            model_version=model_version,
            provenance=provenance,
        )


class ChargeModel(Protocol):
    """Port for deterministic transaction-cost calculation."""

    @property
    def model_id(self) -> str:
        ...

    @property
    def model_version(self) -> str:
        ...

    def calculate(self, context: ChargeCalculationContext) -> ChargeBreakdown:
        ...


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
