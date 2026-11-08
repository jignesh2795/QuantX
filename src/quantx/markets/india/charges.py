"""Effective-dated, source-backed India transaction charges.

This module implements a contract and calculator only. It contains no
production tariff schedule and is not wired into paper or live execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import StrEnum
from zoneinfo import ZoneInfo

from quantx.markets.india.domain import IndianExchange
from quantx.ports.charges import (
    ChargeBreakdown,
    ChargeCalculationContext,
    ChargeComponent,
)

INR = "INR"
_PAISE = Decimal("0.01")
_ZERO = Decimal("0")
_IST = ZoneInfo("Asia/Kolkata")
_COMPONENT_NAMES = (
    "stt",
    "stamp_duty",
    "exchange_txn",
    "ipft",
    "sebi_turnover_fee",
    "gst",
)
_RATE_FIELD_BY_COMPONENT = {
    "stt": "stt_rate",
    "stamp_duty": "stamp_duty_rate",
    "exchange_txn": "exchange_txn_rate",
    "ipft": "ipft_rate",
    "sebi_turnover_fee": "sebi_turnover_rate",
    "gst": "gst_rate",
}


class IndiaChargeRuleUnavailable(ValueError):
    """A required exchange, event, date, rate, or rule is unsupported."""


class IndiaChargeInputUnavailable(ValueError):
    """A required calculation, billing, or tax input is missing or invalid."""


class IndiaTradeSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class IndiaChargeProduct(StrEnum):
    EQUITY_DELIVERY = "EQUITY_DELIVERY"
    EQUITY_INTRADAY = "EQUITY_INTRADAY"
    EQUITY_FUTURES = "EQUITY_FUTURES"
    EQUITY_OPTIONS = "EQUITY_OPTIONS"


class IndiaChargeEvent(StrEnum):
    TRADE = "TRADE"
    OPTION_EXERCISE = "OPTION_EXERCISE"
    OPTION_ASSIGNMENT = "OPTION_ASSIGNMENT"


class IndiaOptionType(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class IndiaRecoveryTaxTreatment(StrEnum):
    EXCLUDE_AS_QUALIFIED_PURE_AGENT = "EXCLUDE_AS_QUALIFIED_PURE_AGENT"
    INCLUDE_IN_TAXABLE_VALUE = "INCLUDE_IN_TAXABLE_VALUE"


class IndiaChargeIncidence(StrEnum):
    CLIENT_PASSTHROUGH = "CLIENT_PASSTHROUGH"
    BROKER_ABSORBED = "BROKER_ABSORBED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class IndiaChargePassThroughPolicy:
    """Explicit client-incidence policy for member-level charge components."""

    stt: IndiaChargeIncidence
    stamp_duty: IndiaChargeIncidence
    exchange_txn: IndiaChargeIncidence
    ipft: IndiaChargeIncidence
    sebi_turnover_fee: IndiaChargeIncidence
    version: str
    source_ref: str

    def __post_init__(self) -> None:
        for name in _COMPONENT_NAMES[:-1]:
            value = getattr(self, name)
            if not isinstance(value, IndiaChargeIncidence):
                raise TypeError(f"{name} must be an IndiaChargeIncidence")
        if not isinstance(self.version, str) or not self.version.strip():
            raise IndiaChargeInputUnavailable("pass-through policy version is required")
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise IndiaChargeInputUnavailable("pass-through policy source_ref is required")


@dataclass(frozen=True, slots=True)
class IndiaChargeCalculationContext(ChargeCalculationContext):
    """India-specific inputs layered on the market-neutral charge context.

    None means unknown or not supplied. A known zero must be supplied as
    Decimal("0"); the calculator never converts missing values into zero.
    """

    exchange: IndianExchange | None = None
    trade_side: IndiaTradeSide | None = None
    product: IndiaChargeProduct | None = None
    event: IndiaChargeEvent = IndiaChargeEvent.TRADE
    effective_at: datetime | None = None
    premium_value: Decimal | None = None
    option_type: IndiaOptionType | None = None
    quantity: Decimal | None = None
    settlement_price: Decimal | None = None
    strike: Decimal | None = None
    exercise_notional_value: Decimal | None = None
    brokerage: Decimal | None = None
    dp_charges: Decimal | None = None
    other_taxable_service_charges: Decimal | None = None
    stt_gst_treatment: IndiaRecoveryTaxTreatment | None = None
    stamp_duty_gst_treatment: IndiaRecoveryTaxTreatment | None = None
    pass_through_policy: IndiaChargePassThroughPolicy | None = None
    gst_policy_version: str | None = None
    gst_policy_source_ref: str | None = None

    def __post_init__(self) -> None:
        _validate_decimal(self.transaction_value, "transaction_value", allow_none=False)
        if self.currency is not None and not isinstance(self.currency, str):
            raise TypeError("currency must be a string when provided")
        ChargeCalculationContext.__post_init__(self)

        for name in (
            "premium_value",
            "quantity",
            "settlement_price",
            "strike",
            "exercise_notional_value",
            "brokerage",
            "dp_charges",
            "other_taxable_service_charges",
        ):
            _validate_decimal(getattr(self, name), name)

        if self.exchange is not None and not isinstance(self.exchange, IndianExchange):
            raise TypeError("exchange must be an IndianExchange")
        if self.trade_side is not None and not isinstance(self.trade_side, IndiaTradeSide):
            raise TypeError("trade_side must be an IndiaTradeSide")
        if self.product is not None and not isinstance(self.product, IndiaChargeProduct):
            raise TypeError("product must be an IndiaChargeProduct")
        if not isinstance(self.event, IndiaChargeEvent):
            raise TypeError("event must be an IndiaChargeEvent")
        if self.option_type is not None and not isinstance(self.option_type, IndiaOptionType):
            raise TypeError("option_type must be an IndiaOptionType")
        if self.stt_gst_treatment is not None and not isinstance(
            self.stt_gst_treatment, IndiaRecoveryTaxTreatment
        ):
            raise TypeError("stt_gst_treatment must be an IndiaRecoveryTaxTreatment")
        if self.stamp_duty_gst_treatment is not None and not isinstance(
            self.stamp_duty_gst_treatment, IndiaRecoveryTaxTreatment
        ):
            raise TypeError("stamp_duty_gst_treatment must be an IndiaRecoveryTaxTreatment")
        if self.pass_through_policy is not None and not isinstance(
            self.pass_through_policy, IndiaChargePassThroughPolicy
        ):
            raise TypeError("pass_through_policy must be an IndiaChargePassThroughPolicy")

        if self.effective_at is not None:
            if not isinstance(self.effective_at, datetime) or not _is_aware(self.effective_at):
                raise ValueError("effective_at must be timezone-aware")

        exercise_values = (
            self.option_type,
            self.quantity,
            self.settlement_price,
            self.strike,
            self.exercise_notional_value,
        )
        if self.event is not IndiaChargeEvent.OPTION_EXERCISE and any(
            value is not None for value in exercise_values
        ):
            raise ValueError("option-exercise inputs are only valid for OPTION_EXERCISE")

        if self.event is IndiaChargeEvent.OPTION_EXERCISE:
            if self.quantity is not None and self.quantity <= _ZERO:
                raise ValueError("exercise quantity must be positive")
            if self.strike is not None and self.strike <= _ZERO:
                raise ValueError("exercise strike must be positive")


@dataclass(frozen=True, slots=True)
class IndiaChargeRateSet:
    """Fractional rates and per-component source/version evidence.

    A rate of 0.1% is Decimal("0.001"). None means unsupported/unavailable;
    Decimal("0") means an explicit, source-backed zero.
    """

    stt_rate: Decimal | None
    stamp_duty_rate: Decimal | None
    exchange_txn_rate: Decimal | None
    ipft_rate: Decimal | None
    sebi_turnover_rate: Decimal | None
    gst_rate: Decimal | None
    component_sources: tuple[tuple[str, str, str], ...]

    def __post_init__(self) -> None:
        for field_name in _RATE_FIELD_BY_COMPONENT.values():
            _validate_decimal(getattr(self, field_name), field_name, allow_none=True)

        if not isinstance(self.component_sources, tuple):
            raise TypeError("component_sources must be an immutable tuple")
        normalized: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for item in self.component_sources:
            if not isinstance(item, tuple) or len(item) != 3:
                raise TypeError("each component source must be a 3-item tuple")
            name, source_ref, rule_version = item
            if name not in _COMPONENT_NAMES:
                raise ValueError("component source has an unknown component name")
            if name in seen:
                raise ValueError("component source names must be unique")
            _require_text(source_ref, "component source_ref")
            _require_text(rule_version, "component rule_version")
            seen.add(name)
            normalized.append((name, source_ref, rule_version))

        if seen != set(_COMPONENT_NAMES):
            raise ValueError("every charge component requires source/version evidence")
        object.__setattr__(self, "component_sources", tuple(sorted(normalized)))

    def source_for(self, component_name: str) -> tuple[str, str]:
        for name, source_ref, rule_version in self.component_sources:
            if name == component_name:
                return source_ref, rule_version
        raise IndiaChargeRuleUnavailable("component source is unavailable")


@dataclass(frozen=True, slots=True)
class IndiaChargeScheduleEntry:
    """One effective interval and immutable product/side/event rate mapping."""

    effective_from: datetime
    effective_to: datetime | None
    version: str
    rates: tuple[
        tuple[
            tuple[IndiaChargeProduct, IndiaTradeSide, IndiaChargeEvent],
            IndiaChargeRateSet,
        ],
        ...,
    ]

    def __post_init__(self) -> None:
        _validate_ist_midnight(self.effective_from, "effective_from")
        if self.effective_to is not None:
            _validate_ist_midnight(self.effective_to, "effective_to")
            if self.effective_from >= self.effective_to:
                raise ValueError("effective_from must be earlier than effective_to")
        _require_text(self.version, "schedule entry version")
        if not isinstance(self.rates, tuple):
            raise TypeError("rates must be an immutable tuple")
        if not self.rates:
            raise ValueError("schedule entry must contain at least one rate mapping")

        normalized = []
        seen = set()
        for item in self.rates:
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError("each schedule rate mapping must be a 2-item tuple")
            key, rate_set = item
            if not isinstance(key, tuple) or len(key) != 3:
                raise TypeError("schedule rate key must be (product, side, event)")
            product, side, event = key
            if not isinstance(product, IndiaChargeProduct):
                raise TypeError("schedule product key must be an IndiaChargeProduct")
            if not isinstance(side, IndiaTradeSide):
                raise TypeError("schedule side key must be an IndiaTradeSide")
            if not isinstance(event, IndiaChargeEvent):
                raise TypeError("schedule event key must be an IndiaChargeEvent")
            if not isinstance(rate_set, IndiaChargeRateSet):
                raise TypeError("schedule value must be an IndiaChargeRateSet")
            if key in seen:
                raise ValueError("schedule rate keys must be unique")
            seen.add(key)
            normalized.append((key, rate_set))

        normalized.sort(key=lambda item: tuple(part.value for part in item[0]))
        object.__setattr__(self, "rates", tuple(normalized))

    def rates_for(
        self,
        product: IndiaChargeProduct,
        side: IndiaTradeSide,
        event: IndiaChargeEvent,
    ) -> IndiaChargeRateSet:
        key = (product, side, event)
        for candidate, rate_set in self.rates:
            if candidate == key:
                return rate_set
        raise IndiaChargeRuleUnavailable("no sourced rule exists for product/side/event")


@dataclass(frozen=True, slots=True)
class IndiaChargeSchedule:
    """Immutable, non-overlapping collection of effective-dated entries."""

    entries: tuple[IndiaChargeScheduleEntry, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise TypeError("schedule entries must be an immutable tuple")
        if not self.entries:
            raise ValueError("charge schedule must contain at least one entry")
        if not all(isinstance(entry, IndiaChargeScheduleEntry) for entry in self.entries):
            raise TypeError("schedule entries must be IndiaChargeScheduleEntry values")

        ordered = tuple(sorted(self.entries, key=lambda entry: entry.effective_from))
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.effective_to is None or previous.effective_to > current.effective_from:
                raise ValueError("charge schedule effective intervals must not overlap")
        object.__setattr__(self, "entries", ordered)

    def select(self, effective_at: datetime) -> IndiaChargeScheduleEntry:
        if not isinstance(effective_at, datetime) or not _is_aware(effective_at):
            raise IndiaChargeRuleUnavailable("effective_at must be timezone-aware")
        normalized = effective_at.astimezone(_IST)
        for entry in self.entries:
            start = entry.effective_from.astimezone(_IST)
            end = entry.effective_to.astimezone(_IST) if entry.effective_to is not None else None
            if start <= normalized and (end is None or normalized < end):
                return entry
        raise IndiaChargeRuleUnavailable("no charge schedule covers effective_at")


@dataclass(frozen=True, slots=True)
class IndiaMarketChargeModel:
    """India-specific calculator implementing the existing market-neutral port."""

    schedule: IndiaChargeSchedule

    def __post_init__(self) -> None:
        if not isinstance(self.schedule, IndiaChargeSchedule):
            raise TypeError("schedule must be an IndiaChargeSchedule")

    @property
    def model_id(self) -> str:
        return "india.market_charges"

    @property
    def model_version(self) -> str:
        return "1"

    def calculate(self, context: ChargeCalculationContext) -> ChargeBreakdown:
        if not isinstance(context, IndiaChargeCalculationContext):
            raise IndiaChargeInputUnavailable("India charge calculation context is required")
        if context.exchange is not IndianExchange.NSE:
            raise IndiaChargeRuleUnavailable("only NSE charges are supported")
        if context.currency != INR:
            raise IndiaChargeInputUnavailable("currency must be INR")
        if context.trade_side is None or context.product is None:
            raise IndiaChargeInputUnavailable("product and trade_side are required")
        if context.effective_at is None:
            raise IndiaChargeInputUnavailable("effective_at is required")
        if context.event is IndiaChargeEvent.OPTION_ASSIGNMENT:
            raise IndiaChargeRuleUnavailable("OPTION_ASSIGNMENT is unsupported")
        if context.event is IndiaChargeEvent.OPTION_EXERCISE:
            self._validate_exercise_context(context)
            if context.premium_value is not None:
                raise IndiaChargeInputUnavailable("premium_value is not valid for OPTION_EXERCISE")
            trade_base = context.transaction_value
        elif context.product is IndiaChargeProduct.EQUITY_OPTIONS:
            if context.premium_value is None:
                raise IndiaChargeInputUnavailable("premium_value is required for option trades")
            trade_base = context.premium_value
        else:
            if context.premium_value is not None:
                raise IndiaChargeInputUnavailable("premium_value is only valid for option trades")
            trade_base = context.transaction_value

        if context.pass_through_policy is None:
            raise IndiaChargeInputUnavailable("pass-through policy is required")
        if context.brokerage is None or context.dp_charges is None or (
            context.other_taxable_service_charges is None
        ):
            raise IndiaChargeInputUnavailable(
                "complete brokerage, DP and other-service inputs are required"
            )
        if context.stt_gst_treatment is None or context.stamp_duty_gst_treatment is None:
            raise IndiaChargeInputUnavailable("STT and stamp-duty GST treatment are required")
        if (
            not isinstance(context.gst_policy_version, str)
            or not context.gst_policy_version.strip()
        ):
            raise IndiaChargeInputUnavailable("GST policy version is required")
        if (
            not isinstance(context.gst_policy_source_ref, str)
            or not context.gst_policy_source_ref.strip()
        ):
            raise IndiaChargeInputUnavailable("GST policy source_ref is required")

        entry = self.schedule.select(context.effective_at)
        rate_set = entry.rates_for(context.product, context.trade_side, context.event)
        rates = {
            component: getattr(rate_set, field_name)
            for component, field_name in _RATE_FIELD_BY_COMPONENT.items()
        }
        for component, rate in rates.items():
            if rate is None:
                raise IndiaChargeRuleUnavailable(f"{component} rate is unavailable")

        if context.event is IndiaChargeEvent.OPTION_EXERCISE:
            for component in ("stamp_duty", "exchange_txn", "ipft"):
                if rates[component] != _ZERO:
                    raise IndiaChargeRuleUnavailable(
                        f"{component} exercise basis is unsupported without a sourced rule"
                    )

        if context.trade_side is IndiaTradeSide.SELL and rates["stamp_duty"] != _ZERO:
            raise IndiaChargeRuleUnavailable("SELL-side stamp duty requires an explicit zero rule")

        policy = context.pass_through_policy
        incidence = {
            "stt": policy.stt,
            "stamp_duty": policy.stamp_duty,
            "exchange_txn": policy.exchange_txn,
            "ipft": policy.ipft,
            "sebi_turnover_fee": policy.sebi_turnover_fee,
        }
        if (
            incidence["stt"] is not IndiaChargeIncidence.CLIENT_PASSTHROUGH
            and context.stt_gst_treatment is IndiaRecoveryTaxTreatment.INCLUDE_IN_TAXABLE_VALUE
        ):
            raise IndiaChargeInputUnavailable(
                "STT cannot enter the GST base when it is not charged to the client"
            )
        if (
            incidence["stamp_duty"] is not IndiaChargeIncidence.CLIENT_PASSTHROUGH
            and context.stamp_duty_gst_treatment
            is IndiaRecoveryTaxTreatment.INCLUDE_IN_TAXABLE_VALUE
        ):
            raise IndiaChargeInputUnavailable(
                "stamp duty cannot enter the GST base when it is not charged to the client"
            )
        for component, value in incidence.items():
            if value is IndiaChargeIncidence.NOT_APPLICABLE and rates[component] != _ZERO:
                raise IndiaChargeRuleUnavailable(
                    f"{component} NOT_APPLICABLE requires a sourced zero rate"
                )

        if context.event is IndiaChargeEvent.OPTION_EXERCISE:
            stt_base = self._intrinsic_value(context)
            sebi_base = context.exercise_notional_value
            if sebi_base is None:
                raise IndiaChargeInputUnavailable("exercise_notional_value is required")
            other_base = _ZERO
        else:
            other_base = trade_base
            stt_base = other_base
            sebi_base = other_base

        raw_amounts = {
            "stt": self._amount(stt_base, rates["stt"]),
            "stamp_duty": self._amount(other_base, rates["stamp_duty"]),
            "exchange_txn": self._amount(other_base, rates["exchange_txn"]),
            "ipft": self._amount(other_base, rates["ipft"]),
            "sebi_turnover_fee": self._amount(sebi_base, rates["sebi_turnover_fee"]),
        }
        client_amounts = {}
        for component, amount in raw_amounts.items():
            if incidence[component] is IndiaChargeIncidence.CLIENT_PASSTHROUGH:
                client_amounts[component] = amount
            else:
                client_amounts[component] = _ZERO

        brokerage = self._round(context.brokerage)
        dp_charges = self._round(context.dp_charges)
        other_services = self._round(context.other_taxable_service_charges)

        taxable_base = brokerage + dp_charges + other_services
        for component in ("exchange_txn", "ipft", "sebi_turnover_fee"):
            if incidence[component] is IndiaChargeIncidence.CLIENT_PASSTHROUGH:
                taxable_base += client_amounts[component]
        if (
            incidence["stt"] is IndiaChargeIncidence.CLIENT_PASSTHROUGH
            and context.stt_gst_treatment
            is IndiaRecoveryTaxTreatment.INCLUDE_IN_TAXABLE_VALUE
        ):
            taxable_base += client_amounts["stt"]
        if (
            incidence["stamp_duty"] is IndiaChargeIncidence.CLIENT_PASSTHROUGH
            and context.stamp_duty_gst_treatment
            is IndiaRecoveryTaxTreatment.INCLUDE_IN_TAXABLE_VALUE
        ):
            taxable_base += client_amounts["stamp_duty"]

        gst = self._amount(taxable_base, rates["gst"])

        components = tuple(
            ChargeComponent(name, client_amounts[name])
            for name in ("stt", "stamp_duty", "exchange_txn", "ipft", "sebi_turnover_fee")
        ) + (
            ChargeComponent("gst", gst),
            ChargeComponent("brokerage", brokerage),
            ChargeComponent("dp_charges", dp_charges),
            ChargeComponent("other_taxable_service_charges", other_services),
        )

        provenance = [
            f"schedule:{entry.version}",
            f"effective_interval:{entry.effective_from.isoformat()}.."
            f"{entry.effective_to.isoformat() if entry.effective_to else 'open'}",
            (
                f"calculation_scope:{context.exchange.value}:"
                f"{context.product.value}:{context.trade_side.value}:{context.event.value}"
            ),
        ]
        for name, source_ref, rule_version in rate_set.component_sources:
            provenance.append(f"component:{name}:{rule_version}:{source_ref}")
        for name, value in incidence.items():
            provenance.append(f"incidence:{name}:{value.value}")
        provenance.extend(
            (
                f"pass_through_policy:{policy.version}:{policy.source_ref}",
                f"stt_gst_treatment:{context.stt_gst_treatment.value}",
                f"stamp_duty_gst_treatment:{context.stamp_duty_gst_treatment.value}",
                f"gst_policy:{context.gst_policy_version}:{context.gst_policy_source_ref}",
                "caller_supplied_component:brokerage",
                "caller_supplied_component:dp_charges",
                "caller_supplied_component:other_taxable_service_charges",
                "amount_convention:ROUND_HALF_UP_to_INR_paise_per_component_per_trade",
            )
        )
        return ChargeBreakdown(
            currency=INR,
            components=components,
            model_id=self.model_id,
            model_version=self.model_version,
            provenance=tuple(provenance),
        )

    @staticmethod
    def _validate_exercise_context(context: IndiaChargeCalculationContext) -> None:
        if context.product is not IndiaChargeProduct.EQUITY_OPTIONS:
            raise IndiaChargeRuleUnavailable("OPTION_EXERCISE is only supported for equity options")
        if context.trade_side is not IndiaTradeSide.BUY:
            raise IndiaChargeRuleUnavailable(
                "OPTION_EXERCISE must represent the exercising purchaser"
            )
        if context.option_type is None:
            raise IndiaChargeInputUnavailable("option_type is required for exercise")
        if context.quantity is None or context.quantity <= _ZERO:
            raise IndiaChargeInputUnavailable("positive exercise quantity is required")
        if context.settlement_price is None or context.strike is None:
            raise IndiaChargeInputUnavailable(
                "settlement_price and strike are required for exercise"
            )
        if context.exercise_notional_value is None:
            raise IndiaChargeInputUnavailable("exercise_notional_value is required")

    @staticmethod
    def _intrinsic_value(context: IndiaChargeCalculationContext) -> Decimal:
        assert context.option_type is not None
        assert context.quantity is not None
        assert context.settlement_price is not None
        assert context.strike is not None
        if context.option_type is IndiaOptionType.CALL:
            intrinsic_per_unit = max(context.settlement_price - context.strike, _ZERO)
        else:
            intrinsic_per_unit = max(context.strike - context.settlement_price, _ZERO)
        return intrinsic_per_unit * context.quantity

    @classmethod
    def _amount(cls, base: Decimal, rate: Decimal) -> Decimal:
        try:
            return cls._round(base * rate)
        except InvalidOperation as exc:
            raise IndiaChargeInputUnavailable(
                "charge arithmetic is outside Decimal limits"
            ) from exc

    @staticmethod
    def _round(value: Decimal) -> Decimal:
        try:
            if not value.is_finite() or value < _ZERO:
                raise IndiaChargeInputUnavailable("charge amount must be finite and non-negative")
            return value.quantize(_PAISE, rounding=ROUND_HALF_UP)
        except InvalidOperation as exc:
            raise IndiaChargeInputUnavailable("charge amount cannot be rounded to paise") from exc


def _validate_decimal(value: Decimal | None, name: str, *, allow_none: bool = True) -> None:
    if value is None:
        if allow_none:
            return
        raise TypeError(f"{name} must be a Decimal")
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite")
    if value < _ZERO:
        raise ValueError(f"{name} cannot be negative")


def _require_text(value: str | None, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be empty")


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _validate_ist_midnight(value: datetime, name: str) -> None:
    if not isinstance(value, datetime) or not _is_aware(value):
        raise ValueError(f"{name} must be timezone-aware")
    local = value.astimezone(_IST)
    if local.hour or local.minute or local.second or local.microsecond:
        raise ValueError(f"{name} must represent Asia/Kolkata midnight")


__all__ = [
    "IndiaChargeCalculationContext",
    "IndiaChargeEvent",
    "IndiaChargeIncidence",
    "IndiaChargeInputUnavailable",
    "IndiaChargePassThroughPolicy",
    "IndiaChargeProduct",
    "IndiaChargeRateSet",
    "IndiaChargeRuleUnavailable",
    "IndiaChargeSchedule",
    "IndiaChargeScheduleEntry",
    "IndiaMarketChargeModel",
    "IndiaOptionType",
    "IndiaRecoveryTaxTreatment",
    "IndiaTradeSide",
]