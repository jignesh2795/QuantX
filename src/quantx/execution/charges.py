"""Deterministic transaction-cost contracts for paper and research execution.

This module models explicit, configured transaction charges. It deliberately
does not encode broker tariffs, taxes, exchange schedules, or other
market-specific rules.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, getcontext, localcontext
from enum import StrEnum
from typing import Protocol

from quantx.domain.enums import OrderSide


@dataclass(frozen=True, slots=True)
class ChargeCalculationContext:
    """Explicit monetary basis supplied to a transaction-cost model."""

    transaction_value: Decimal
    currency: str | None = None
    side: OrderSide | None = None
    unit_price: Decimal | None = None
    quantity: Decimal | None = None

    def __post_init__(self) -> None:
        _require_nonnegative_decimal(self.transaction_value, "transaction_value")
        if self.currency is not None and not self.currency.strip():
            raise ValueError("currency must not be empty when provided")
        if self.side is not None and not isinstance(self.side, OrderSide):
            raise TypeError("side must be an OrderSide when provided")
        for name, value in (("unit_price", self.unit_price), ("quantity", self.quantity)):
            if value is not None:
                _require_nonnegative_decimal(value, name)


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
        if not self.amount.is_finite():
            raise ValueError("charge component amount must be finite")
        if self.amount < 0:
            raise ValueError("charge component amount cannot be negative")


def sum_charge_amounts(values: tuple[Decimal, ...]) -> Decimal:
    """Sum charge amounts exactly without ambient Decimal-context truncation."""
    if not values:
        return Decimal("0")
    precision = sum(
        len(value.as_tuple().digits)
        + abs(value.as_tuple().exponent)
        + abs(value.adjusted())
        + 2
        for value in values
    ) + len(values) * 4
    with localcontext() as context:
        context.prec = max(getcontext().prec, precision)
        return sum(values, Decimal("0"))


@dataclass(frozen=True, slots=True)
class ChargeBreakdown:
    """Immutable, auditable transaction-cost result."""

    currency: str | None
    components: tuple[ChargeComponent, ...]
    model_id: str
    model_version: str
    provenance: tuple[str, ...] = ()
    rounded_total: Decimal | None = None

    def __post_init__(self) -> None:
        if self.currency is not None and not self.currency.strip():
            raise ValueError("currency must not be empty when provided")
        if not self.model_id.strip():
            raise ValueError("model_id must not be empty")
        if not self.model_version.strip():
            raise ValueError("model_version must not be empty")
        if self.rounded_total is not None:
            _require_nonnegative_decimal(self.rounded_total, "rounded_total")
        names = [component.name for component in self.components]
        if len(names) != len(set(names)):
            raise ValueError("charge component names must be unique")

    @property
    def total(self) -> Decimal:
        return sum_charge_amounts(tuple(component.amount for component in self.components))

    @property
    def applied_total(self) -> Decimal:
        """Return the booked total when rounded, otherwise the exact component sum."""
        return self.total if self.rounded_total is None else self.rounded_total

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


def _require_nonnegative_decimal(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value < 0:
        raise ValueError(f"{name} cannot be negative")


class ChargeBase(StrEnum):
    """Calculation basis for one caller-supplied cost line."""

    TURNOVER = "TURNOVER"
    UNITS = "UNITS"
    ORDER = "ORDER"
    CHARGES = "CHARGES"


class ChargeSide(StrEnum):
    """Fill side on which one cost line applies."""

    BUY = "BUY"
    SELL = "SELL"
    BOTH = "BOTH"


@dataclass(frozen=True, slots=True)
class CostLine:
    """One immutable OpenAlgo-style charge line.

    The rate unit is defined by base: fraction for turnover/charges, money per
    unit for units, and money per fill for order.
    """

    name: str
    base: ChargeBase
    rate: Decimal
    side: ChargeSide = ChargeSide.BOTH
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    of: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("cost line name must not be empty")
        if not isinstance(self.base, ChargeBase):
            raise TypeError("base must be a ChargeBase")
        if not isinstance(self.side, ChargeSide):
            raise TypeError("side must be a ChargeSide")
        _require_nonnegative_decimal(self.rate, "rate")
        for name, value in (("minimum", self.minimum), ("maximum", self.maximum)):
            if value is not None:
                _require_nonnegative_decimal(value, name)
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        if not isinstance(self.of, tuple) or any(
            not isinstance(item, str) or not item.strip() for item in self.of
        ):
            raise ValueError("of must be a tuple of non-empty line names")
        if len(self.of) != len(set(self.of)):
            raise ValueError("of references must be unique")
        if self.base is ChargeBase.CHARGES and not self.of:
            raise ValueError("CHARGES lines require at least one of reference")
        if self.base is not ChargeBase.CHARGES and self.of:
            raise ValueError("of references are only valid for CHARGES lines")
        object.__setattr__(self, "of", tuple(sorted(self.of)))


@dataclass(frozen=True, slots=True)
class CostSchedule:
    """Immutable caller-supplied schedule with canonical material parameters."""

    lines: tuple[CostLine, ...]
    currency: str
    digits: int
    source: str
    model_version: str = "1"

    def __post_init__(self) -> None:
        if not isinstance(self.lines, tuple) or not self.lines:
            raise ValueError("cost schedule must contain at least one line")
        if any(not isinstance(line, CostLine) for line in self.lines):
            raise TypeError("cost schedule lines must be CostLine values")
        names = [line.name for line in self.lines]
        if len(names) != len(set(names)):
            raise ValueError("cost line names must be unique")
        if not isinstance(self.currency, str) or not self.currency.strip():
            raise ValueError("currency must not be empty")
        if not isinstance(self.digits, int) or isinstance(self.digits, bool):
            raise TypeError("digits must be an integer")
        if not 0 <= self.digits <= 18:
            raise ValueError("digits must be between 0 and 18")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("source must not be empty")
        if not isinstance(self.model_version, str) or not self.model_version.strip():
            raise ValueError("model_version must not be empty")
        line_names = set(names)
        for line in self.lines:
            missing = sorted(set(line.of) - line_names)
            if missing:
                raise ValueError(f"cost line {line.name!r} references unknown lines: {missing}")
        object.__setattr__(self, "lines", tuple(sorted(self.lines, key=lambda line: line.name)))
        self.evaluation_order

    @property
    def evaluation_order(self) -> tuple[str, ...]:
        """Return stable topological order, rejecting cyclic dependencies."""
        by_name = {line.name: line for line in self.lines}
        indegree = {line.name: 0 for line in self.lines}
        dependents: dict[str, list[str]] = {line.name: [] for line in self.lines}
        for line in self.lines:
            for dependency in line.of:
                indegree[line.name] += 1
                dependents[dependency].append(line.name)
        ready = sorted(name for name, degree in indegree.items() if degree == 0)
        ordered: list[str] = []
        while ready:
            name = ready.pop(0)
            ordered.append(name)
            for dependent in sorted(dependents[name]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
                    ready.sort()
        if len(ordered) != len(by_name):
            cyclic = sorted(name for name, degree in indegree.items() if degree > 0)
            raise ValueError(f"cost schedule contains cyclic dependencies: {cyclic}")
        return tuple(ordered)

    @property
    def material_parameters(self) -> tuple[tuple[str, str], ...]:
        """Full, stable parameter representation for research provenance."""
        values: list[tuple[str, str]] = [
            ("currency", self.currency),
            ("digits", str(self.digits)),
            ("model_version", self.model_version),
            ("rounding", "ROUND_HALF_EVEN"),
            ("source", self.source),
        ]
        for index, line in enumerate(self.lines):
            prefix = f"line:{index:04d}"
            values.extend(
                (
                    (f"{prefix}:name", line.name),
                    (f"{prefix}:base", line.base.value),
                    (f"{prefix}:side", line.side.value),
                    (f"{prefix}:rate", str(line.rate)),
                    (f"{prefix}:minimum", "null" if line.minimum is None else str(line.minimum)),
                    (f"{prefix}:maximum", "null" if line.maximum is None else str(line.maximum)),
                    (f"{prefix}:of", json.dumps(line.of, separators=(",", ":"))),
                )
            )
        return tuple(sorted(values))

    @property
    def model_id(self) -> str:
        encoded = json.dumps(self.material_parameters, separators=(",", ":"), ensure_ascii=True)
        return f"paper.cost_schedule.sha256:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


def _round_currency_total(value: Decimal, digits: int) -> Decimal:
    """Round one fill total once using the schedule's explicit half-even policy."""
    quantum = Decimal(1).scaleb(-digits)
    required_precision = max(
        getcontext().prec,
        len(value.as_tuple().digits) + max(0, value.adjusted() + digits + 1) + 2,
    )
    try:
        with localcontext() as context:
            context.prec = required_precision
            return value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    except InvalidOperation as exc:
        raise ValueError("fill charge total cannot be represented at configured precision") from exc


@dataclass(frozen=True, slots=True)
class CostScheduleChargeModel:
    """Deterministic per-fill calculator for an explicit cost schedule."""

    schedule: CostSchedule

    @property
    def model_id(self) -> str:
        return self.schedule.model_id

    @property
    def model_version(self) -> str:
        return self.schedule.model_version

    @property
    def provenance(self) -> tuple[str, ...]:
        return (
            f"source:{self.schedule.source}",
            "rounding:ROUND_HALF_EVEN",
            f"currency:{self.schedule.currency}",
            f"digits:{self.schedule.digits}",
        )

    def calculate(self, context: ChargeCalculationContext) -> ChargeBreakdown:
        if not isinstance(context, ChargeCalculationContext):
            raise TypeError("context must be a ChargeCalculationContext")
        if context.currency is None:
            raise ValueError("cost schedule calculation requires an explicit currency")
        if context.currency != self.schedule.currency:
            raise ValueError("fill currency does not match cost schedule currency")
        if context.side is None or context.unit_price is None or context.quantity is None:
            raise ValueError("cost schedule calculation requires side, unit_price and quantity")
        if context.unit_price <= 0 or context.quantity <= 0:
            raise ValueError("unit_price and quantity must be positive")
        precision_values = [context.transaction_value, context.unit_price, context.quantity]
        for line in self.schedule.lines:
            precision_values.append(line.rate)
            if line.minimum is not None:
                precision_values.append(line.minimum)
            if line.maximum is not None:
                precision_values.append(line.maximum)
        exact_precision = sum(
            len(value.as_tuple().digits)
            + abs(value.as_tuple().exponent)
            + abs(value.adjusted())
            + 2
            for value in precision_values
        ) + (len(self.schedule.lines) + 1) * 8
        with localcontext() as decimal_context:
            decimal_context.prec = max(getcontext().prec, exact_precision)
            if context.transaction_value != context.unit_price * context.quantity:
                raise ValueError(
                    "transaction_value must equal unit_price multiplied by quantity"
                )
            return self._calculate_with_precision(context)

    def _calculate_with_precision(
        self, context: ChargeCalculationContext
    ) -> ChargeBreakdown:
        assert context.side is not None
        assert context.unit_price is not None
        assert context.quantity is not None
        by_name = {line.name: line for line in self.schedule.lines}
        amounts: dict[str, Decimal] = {}
        applicable: set[str] = set()
        for name in self.schedule.evaluation_order:
            line = by_name[name]
            applies = line.side is ChargeSide.BOTH or (
                line.side is ChargeSide.BUY and context.side is OrderSide.BUY
            ) or (line.side is ChargeSide.SELL and context.side is OrderSide.SELL)
            if not applies:
                amounts[name] = Decimal("0")
                continue
            applicable.add(name)
            if line.base is ChargeBase.TURNOVER:
                base_amount = context.transaction_value
            elif line.base is ChargeBase.UNITS:
                base_amount = context.quantity
            elif line.base is ChargeBase.ORDER:
                base_amount = Decimal("1")
            else:
                base_amount = sum(
                    (amounts[dependency] for dependency in line.of),
                    Decimal("0"),
                )
            amount = line.rate * base_amount
            if line.minimum is not None:
                amount = max(amount, line.minimum)
            if line.maximum is not None:
                amount = min(amount, line.maximum)
            amounts[name] = amount

        components = tuple(
            ChargeComponent(line.name, amounts[line.name])
            for line in self.schedule.lines
            if line.name in applicable
        )
        unrounded_total = sum_charge_amounts(tuple(component.amount for component in components))
        rounded_total = _round_currency_total(unrounded_total, self.schedule.digits)
        return ChargeBreakdown(
            currency=self.schedule.currency,
            components=components,
            model_id=self.model_id,
            model_version=self.model_version,
            provenance=self.provenance,
            rounded_total=rounded_total,
        )


class ChargeModel(Protocol):
    """Port for deterministic transaction-cost calculation."""

    @property
    def model_id(self) -> str: ...

    @property
    def model_version(self) -> str: ...

    def calculate(self, context: ChargeCalculationContext) -> ChargeBreakdown: ...


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
    "ChargeBase",
    "ChargeSide",
    "CostLine",
    "CostSchedule",
    "CostScheduleChargeModel",
    "PercentageBpsChargeModel",
    "sum_charge_amounts",
]
