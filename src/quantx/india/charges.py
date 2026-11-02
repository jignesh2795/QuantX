from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any, cast
from zoneinfo import ZoneInfo

from quantx.execution.charges import (
    ChargeBreakdown,
    ChargeCalculationContext,
    ChargeComponent,
)
from quantx.india.domain import IndianExchange

_IST = ZoneInfo("Asia/Kolkata")
_PAISE = Decimal("0.01")
_COMPONENTS = (
    "stt",
    "stamp_duty",
    "exchange_txn",
    "ipft",
    "sebi_turnover_fee",
    "gst",
)

_PASS_THROUGH_COMPONENTS = frozenset(
    {"stt", "stamp_duty", "exchange_txn", "ipft", "sebi_turnover_fee"}
)


class IndiaChargeRuleUnavailable(ValueError):
    """Raised when an India charge rule, source, or supported scope is missing."""


class IndiaChargeInputUnavailable(ValueError):
    """Raised when required India charge calculation input is missing."""


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
    stt: IndiaChargeIncidence
    stamp_duty: IndiaChargeIncidence
    exchange_txn: IndiaChargeIncidence
    ipft: IndiaChargeIncidence
    sebi_turnover_fee: IndiaChargeIncidence
    version: str
    source_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "stt", _enum(IndiaChargeIncidence, self.stt, "stt"))
        object.__setattr__(
            self, "stamp_duty", _enum(IndiaChargeIncidence, self.stamp_duty, "stamp_duty")
        )
        object.__setattr__(
            self, "exchange_txn", _enum(IndiaChargeIncidence, self.exchange_txn, "exchange_txn")
        )
        object.__setattr__(self, "ipft", _enum(IndiaChargeIncidence, self.ipft, "ipft"))
        object.__setattr__(
            self,
            "sebi_turnover_fee",
            _enum(IndiaChargeIncidence, self.sebi_turnover_fee, "sebi_turnover_fee"),
        )
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("pass-through policy version must be a non-empty string")
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise ValueError("pass-through policy source_ref must be a non-empty string")
        object.__setattr__(self, "version", self.version.strip())
        object.__setattr__(self, "source_ref", self.source_ref.strip())

    def incidence(self, component: str) -> IndiaChargeIncidence:
        return getattr(self, component)  # type: ignore[no-any-return]


@dataclass(frozen=True, slots=True)
class IndiaChargeCalculationContext(ChargeCalculationContext):
    exchange: object | None = None
    trade_side: object | None = None
    product: object | None = None
    event: object = IndiaChargeEvent.TRADE
    effective_at: datetime | None = None
    premium_value: Decimal | None = None
    option_type: object | None = None
    quantity: Decimal | None = None
    settlement_price: Decimal | None = None
    strike: Decimal | None = None
    exercise_notional_value: Decimal | None = None
    brokerage: Decimal | None = None
    dp_charges: Decimal | None = None
    other_taxable_service_charges: Decimal | None = None
    stt_gst_treatment: object | None = None
    stamp_duty_gst_treatment: object | None = None
    pass_through_policy: IndiaChargePassThroughPolicy | None = None
    gst_policy_version: str | None = None
    gst_policy_source_ref: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.transaction_value, Decimal):
            raise TypeError("transaction_value must be a Decimal")
        if self.transaction_value < 0:
            raise ValueError("transaction_value cannot be negative")
        if self.currency is not None and (
            not isinstance(self.currency, str) or not self.currency.strip()
        ):
            raise ValueError("currency must not be empty when provided")
        if not self.transaction_value.is_finite():
            raise ValueError("transaction_value must be finite")
        if self.currency != "INR":
            raise IndiaChargeRuleUnavailable("currency must be INR")
        if self.exchange is None:
            raise IndiaChargeRuleUnavailable("exchange is required")
        self_exchange = _enum_or_none(IndianExchange, self.exchange, "exchange")
        if self_exchange is not IndianExchange.NSE:
            raise IndiaChargeRuleUnavailable("only NSE is supported")
        object.__setattr__(self, "exchange", self_exchange)

        if self.trade_side is None:
            raise IndiaChargeInputUnavailable("trade_side is required")
        self_trade_side = _enum(IndiaTradeSide, self.trade_side, "trade_side")
        object.__setattr__(self, "trade_side", self_trade_side)

        if self.product is None:
            raise IndiaChargeInputUnavailable("product is required")
        self_product = _enum(IndiaChargeProduct, self.product, "product")
        object.__setattr__(self, "product", self_product)

        self_event = _enum(IndiaChargeEvent, self.event, "event")
        object.__setattr__(self, "event", self_event)

        if self.effective_at is None:
            raise IndiaChargeInputUnavailable("effective_at is required")
        if not isinstance(self.effective_at, datetime) or self.effective_at.tzinfo is None:
            raise ValueError("effective_at must be timezone-aware")
        object.__setattr__(self, "effective_at", self.effective_at)

        _optional_decimal(self.premium_value, "premium_value")
        if (
            self.product is IndiaChargeProduct.EQUITY_OPTIONS
            and self.event is IndiaChargeEvent.TRADE
        ):
            if self.premium_value is None:
                raise IndiaChargeInputUnavailable("premium_value is required")
        if self.option_type is not None:
            object.__setattr__(
                self, "option_type", _enum(IndiaOptionType, self.option_type, "option_type")
            )
        _optional_decimal(self.quantity, "quantity", positive=True)
        _optional_decimal(self.settlement_price, "settlement_price", non_negative=True)
        _optional_decimal(self.strike, "strike", non_negative=True)
        _optional_decimal(
            self.exercise_notional_value, "exercise_notional_value", non_negative=True
        )

        if self.event is IndiaChargeEvent.OPTION_EXERCISE:
            if self.trade_side is not IndiaTradeSide.BUY:
                raise IndiaChargeInputUnavailable("option exercise requires the exercising buyer")
            if self.option_type is None:
                raise IndiaChargeInputUnavailable("option_type is required")
            if self.quantity is None:
                raise IndiaChargeInputUnavailable("quantity is required")
            if self.settlement_price is None:
                raise IndiaChargeInputUnavailable("settlement_price is required")
            if self.strike is None:
                raise IndiaChargeInputUnavailable("strike is required")
            if self.exercise_notional_value is None:
                raise IndiaChargeInputUnavailable("exercise_notional_value is required")

        object.__setattr__(self, "brokerage", _require_decimal(self.brokerage, "brokerage"))
        object.__setattr__(self, "dp_charges", _require_decimal(self.dp_charges, "dp_charges"))
        object.__setattr__(
            self,
            "other_taxable_service_charges",
            _require_decimal(self.other_taxable_service_charges, "other_taxable_service_charges"),
        )

        if self.stt_gst_treatment is None:
            raise IndiaChargeInputUnavailable("stt_gst_treatment is required")
        object.__setattr__(
            self,
            "stt_gst_treatment",
            _enum(IndiaRecoveryTaxTreatment, self.stt_gst_treatment, "stt_gst_treatment"),
        )
        if self.stamp_duty_gst_treatment is None:
            raise IndiaChargeInputUnavailable("stamp_duty_gst_treatment is required")
        object.__setattr__(
            self,
            "stamp_duty_gst_treatment",
            _enum(
                IndiaRecoveryTaxTreatment, self.stamp_duty_gst_treatment, "stamp_duty_gst_treatment"
            ),
        )
        if self.pass_through_policy is None:
            raise IndiaChargeInputUnavailable("pass_through_policy is required")
        if not isinstance(self.pass_through_policy, IndiaChargePassThroughPolicy):
            raise IndiaChargeInputUnavailable(
                "pass_through_policy must be an IndiaChargePassThroughPolicy"
            )
        if self.gst_policy_version is None or not str(self.gst_policy_version).strip():
            raise IndiaChargeInputUnavailable("gst_policy_version is required")
        object.__setattr__(self, "gst_policy_version", str(self.gst_policy_version).strip())
        if self.gst_policy_source_ref is None or not str(self.gst_policy_source_ref).strip():
            raise IndiaChargeInputUnavailable("gst_policy_source_ref is required")
        object.__setattr__(self, "gst_policy_source_ref", str(self.gst_policy_source_ref).strip())


@dataclass(frozen=True, slots=True)
class IndiaChargeRateSet:
    stt_rate: Decimal | None
    stamp_duty_rate: Decimal | None
    exchange_txn_rate: Decimal | None
    ipft_rate: Decimal | None
    sebi_turnover_rate: Decimal | None
    gst_rate: Decimal | None
    component_sources: tuple[tuple[str, str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "stt_rate", _optional_rate(self.stt_rate, "stt_rate"))
        object.__setattr__(
            self, "stamp_duty_rate", _optional_rate(self.stamp_duty_rate, "stamp_duty_rate")
        )
        object.__setattr__(
            self, "exchange_txn_rate", _optional_rate(self.exchange_txn_rate, "exchange_txn_rate")
        )
        object.__setattr__(self, "ipft_rate", _optional_rate(self.ipft_rate, "ipft_rate"))
        object.__setattr__(
            self,
            "sebi_turnover_rate",
            _optional_rate(self.sebi_turnover_rate, "sebi_turnover_rate"),
        )
        object.__setattr__(self, "gst_rate", _optional_rate(self.gst_rate, "gst_rate"))
        normalized_sources = _normalize_sources(self.component_sources)
        object.__setattr__(self, "component_sources", normalized_sources)
        for component, source, version in normalized_sources:
            if component not in _COMPONENTS:
                raise IndiaChargeRuleUnavailable(f"unknown charge component source: {component}")
            if not source or not version:
                raise IndiaChargeRuleUnavailable(
                    "charge component source and version must be non-empty"
                )
        for component in _COMPONENTS:
            rate = getattr(self, _rate_field(component))
            if rate is not None and not _has_source(normalized_sources, component):
                raise IndiaChargeRuleUnavailable(
                    f"missing source for charge component: {component}"
                )


@dataclass(frozen=True, slots=True)
class IndiaChargeScheduleEntry:
    effective_from: datetime
    effective_to: datetime | None
    version: str
    rates: object

    def __post_init__(self) -> None:
        if not isinstance(self.effective_from, datetime) or self.effective_from.tzinfo is None:
            raise ValueError("effective_from must be timezone-aware")
        from_ist = self.effective_from.astimezone(_IST)
        if from_ist.timetuple()[3:6] != (0, 0, 0) or from_ist.microsecond != 0:
            raise ValueError("effective_from must be an Asia/Kolkata midnight")
        if self.effective_from.tzinfo != _IST:
            # Equivalent instant is accepted only when expressed in IST.
            raise ValueError("effective_from must use Asia/Kolkata")
        if self.effective_to is not None:
            if not isinstance(self.effective_to, datetime) or self.effective_to.tzinfo is None:
                raise ValueError("effective_to must be timezone-aware or None")
            to_ist = self.effective_to.astimezone(_IST)
            if to_ist.timetuple()[3:6] != (0, 0, 0) or to_ist.microsecond != 0:
                raise ValueError("effective_to must be an Asia/Kolkata midnight")
            if self.effective_to.tzinfo != _IST:
                raise ValueError("effective_to must use Asia/Kolkata")
            if not (self.effective_from < self.effective_to):
                raise ValueError("effective_from must be before effective_to")
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("schedule version must be non-empty")
        object.__setattr__(self, "version", self.version.strip())
        normalized_rates = _normalize_rates(self.rates)
        object.__setattr__(self, "rates", normalized_rates)
        if not normalized_rates:
            raise IndiaChargeRuleUnavailable("schedule entry must contain rates")
        keys = [key for key, _ in normalized_rates]
        if len(keys) != len(set(keys)):
            raise IndiaChargeRuleUnavailable("schedule rates must have unique keys")


@dataclass(frozen=True, slots=True)
class IndiaChargeSchedule:
    entries: tuple[IndiaChargeScheduleEntry, ...] = ()

    def __post_init__(self) -> None:
        normalized_entries = _normalize_entries(self.entries)
        # Validate and sort immutable entries.
        for entry in normalized_entries:
            if not isinstance(entry, IndiaChargeScheduleEntry):
                raise TypeError("entries must contain IndiaChargeScheduleEntry values")
        sorted_entries = tuple(sorted(normalized_entries, key=lambda item: item.effective_from))
        _validate_no_overlaps(sorted_entries)
        object.__setattr__(self, "entries", sorted_entries)

    def select(self, effective_at: datetime) -> IndiaChargeScheduleEntry:
        if not isinstance(effective_at, datetime) or effective_at.tzinfo is None:
            raise ValueError("effective_at must be timezone-aware")
        normalized = effective_at.astimezone(_IST)
        for entry in self.entries:
            upper = entry.effective_to if entry.effective_to is not None else None
            if entry.effective_from <= normalized and (upper is None or normalized < upper):
                return entry
        raise IndiaChargeRuleUnavailable(
            "no India charge schedule entry covers the requested instant"
        )


@dataclass(frozen=True, slots=True)
class IndiaMarketChargeModel:
    schedule: IndiaChargeSchedule
    model_id: str = "india.market_charges"
    model_version: str = "1"

    def __post_init__(self) -> None:
        if not isinstance(self.schedule, IndiaChargeSchedule):
            raise TypeError("schedule must be an IndiaChargeSchedule")
        if not self.model_id.strip():
            raise ValueError("model_id must not be empty")
        if not self.model_version.strip():
            raise ValueError("model_version must not be empty")

    def calculate(self, context: ChargeCalculationContext) -> ChargeBreakdown:
        if not isinstance(context, IndiaChargeCalculationContext):
            raise IndiaChargeInputUnavailable("context must be an IndiaChargeCalculationContext")
        assert context.effective_at is not None
        assert context.pass_through_policy is not None
        assert context.brokerage is not None
        assert context.dp_charges is not None
        assert context.other_taxable_service_charges is not None
        if context.transaction_value < 0:
            raise ValueError("transaction_value cannot be negative")
        if not context.transaction_value.is_finite():
            raise ValueError("transaction_value must be finite")

        entry = self.schedule.select(context.effective_at)
        assert context.product is not None
        assert context.trade_side is not None
        key = (context.product, context.trade_side, context.event)
        rate_set = _rate_set_for(entry, key)
        if rate_set is None:
            raise IndiaChargeRuleUnavailable(
                "no India charge rule for the requested product, side, and event"
            )

        for component in _COMPONENTS:
            rate = getattr(rate_set, _rate_field(component))
            if rate is None:
                raise IndiaChargeRuleUnavailable(f"missing India charge rate: {component}")
            if not isinstance(rate, Decimal) or not rate.is_finite() or rate < 0:
                raise IndiaChargeRuleUnavailable(f"invalid India charge rate: {component}")
        for component in _COMPONENTS:
            if not _has_source(rate_set.component_sources, component):
                raise IndiaChargeRuleUnavailable(f"missing India charge source: {component}")

        assert rate_set.stt_rate is not None
        assert rate_set.stamp_duty_rate is not None
        assert rate_set.exchange_txn_rate is not None
        assert rate_set.ipft_rate is not None
        assert rate_set.sebi_turnover_rate is not None
        assert rate_set.gst_rate is not None

        stt_base = _stt_base(context)
        stamp_base = _stamp_base(context)
        exchange_base = _exchange_base(context)
        ipft_base = exchange_base
        sebi_base = _sebi_base(context)

        incidence: IndiaChargePassThroughPolicy = context.pass_through_policy
        stt_amount = (
            _rounded(stt_base * rate_set.stt_rate)
            if incidence.stt is IndiaChargeIncidence.CLIENT_PASSTHROUGH
            else Decimal("0")
        )
        stamp_amount = (
            _rounded(stamp_base * rate_set.stamp_duty_rate)
            if incidence.stamp_duty is IndiaChargeIncidence.CLIENT_PASSTHROUGH
            else Decimal("0")
        )
        exchange_amount = (
            _rounded(exchange_base * rate_set.exchange_txn_rate)
            if incidence.exchange_txn is IndiaChargeIncidence.CLIENT_PASSTHROUGH
            else Decimal("0")
        )
        ipft_amount = (
            _rounded(ipft_base * rate_set.ipft_rate)
            if incidence.ipft is IndiaChargeIncidence.CLIENT_PASSTHROUGH
            else Decimal("0")
        )
        sebi_amount = (
            _rounded(sebi_base * rate_set.sebi_turnover_rate)
            if incidence.sebi_turnover_fee is IndiaChargeIncidence.CLIENT_PASSTHROUGH
            else Decimal("0")
        )

        components = [
            ChargeComponent("stt", stt_amount),
            ChargeComponent("stamp_duty", stamp_amount),
            ChargeComponent("exchange_txn", exchange_amount),
            ChargeComponent("ipft", ipft_amount),
            ChargeComponent("sebi_turnover_fee", sebi_amount),
        ]

        gst_taxable_base = Decimal("0")
        if (
            incidence.stt is IndiaChargeIncidence.CLIENT_PASSTHROUGH
            and context.stt_gst_treatment is IndiaRecoveryTaxTreatment.INCLUDE_IN_TAXABLE_VALUE
        ):
            gst_taxable_base += stt_amount
        if (
            incidence.stamp_duty is IndiaChargeIncidence.CLIENT_PASSTHROUGH
            and context.stamp_duty_gst_treatment
            is IndiaRecoveryTaxTreatment.INCLUDE_IN_TAXABLE_VALUE
        ):
            gst_taxable_base += stamp_amount
        if incidence.exchange_txn is IndiaChargeIncidence.CLIENT_PASSTHROUGH:
            gst_taxable_base += exchange_amount
        if incidence.ipft is IndiaChargeIncidence.CLIENT_PASSTHROUGH:
            gst_taxable_base += ipft_amount
        if incidence.sebi_turnover_fee is IndiaChargeIncidence.CLIENT_PASSTHROUGH:
            gst_taxable_base += sebi_amount
        gst_taxable_base += (
            context.brokerage + context.dp_charges + context.other_taxable_service_charges
        )

        gst_amount = _rounded(gst_taxable_base * rate_set.gst_rate)
        components.append(ChargeComponent("gst", gst_amount))
        components.append(ChargeComponent("brokerage", context.brokerage))
        components.append(ChargeComponent("dp_charges", context.dp_charges))
        components.append(
            ChargeComponent("other_taxable_service_charges", context.other_taxable_service_charges)
        )

        stt_treatment = context.stt_gst_treatment
        stamp_treatment = context.stamp_duty_gst_treatment
        assert isinstance(stt_treatment, IndiaRecoveryTaxTreatment)
        assert isinstance(stamp_treatment, IndiaRecoveryTaxTreatment)
        provenance: tuple[str, ...] = (
            f"schedule_version={entry.version}",
            f"schedule_interval={entry.effective_from.isoformat()} to "
            f"{entry.effective_to.isoformat() if entry.effective_to is not None else 'open-ended'}",
        )
        for component in _COMPONENTS:
            source, version = _source_for(rate_set, component)
            incidence_value = (
                incidence.incidence(component).value
                if component in _PASS_THROUGH_COMPONENTS
                else "not_applicable"
            )
            provenance += (
                f"{component}:source={source}:rule_version={version}:incidence={incidence_value}",
            )
        provenance += (
            f"stt_gst_treatment={stt_treatment.value}",
            f"stamp_duty_gst_treatment={stamp_treatment.value}",
            f"pass_through_policy={context.pass_through_policy.version}",
            f"pass_through_source={context.pass_through_policy.source_ref}",
            f"gst_policy={context.gst_policy_version}",
            f"gst_policy_source={context.gst_policy_source_ref}",
        )

        return ChargeBreakdown(
            currency="INR",
            components=tuple(components),
            model_id=self.model_id,
            model_version=self.model_version,
            provenance=provenance,
        )


def _enum(enum_type: type, value: object, field_name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value)
        except ValueError as exc:
            raise IndiaChargeInputUnavailable(
                f"{field_name} must be a valid {enum_type.__name__}"
            ) from exc
    raise IndiaChargeInputUnavailable(f"{field_name} must be a {enum_type.__name__}")


def _enum_or_none(enum_type: type, value: object, field_name: str) -> Any:
    if value is None:
        return None
    return _enum(enum_type, value, field_name)


def _require_decimal(value: object, field_name: str) -> Decimal:
    if value is None:
        raise IndiaChargeInputUnavailable(f"{field_name} is required")
    if type(value) is not Decimal:
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return value


def _optional_decimal(
    value: object, field_name: str, *, positive: bool = False, non_negative: bool = True
) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not Decimal:
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if non_negative and value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    if positive and value <= 0:
        raise ValueError(f"{field_name} must be positive")
    return value


def _optional_rate(value: object, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not Decimal:
        raise TypeError(f"{field_name} must be a Decimal")
    if not value.is_finite():
        raise ValueError(f"{field_name} must be finite")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return value


def _normalize_rates(value: object) -> tuple[tuple[object, object], ...]:
    if isinstance(value, Mapping):
        items = list(value.items())
    elif isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise TypeError("rates must be a mapping or sequence")
    normalized = []
    for item in items:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise TypeError("rates entries must be (key, rate set) pairs")
        key, rate_set = item
        if not isinstance(key, (tuple, list)) or len(key) != 3:
            raise TypeError("rate key must be (product, side, event)")
        product = _enum(IndiaChargeProduct, key[0], "product")
        side = _enum(IndiaTradeSide, key[1], "side")
        event = _enum(IndiaChargeEvent, key[2], "event")
        if not isinstance(rate_set, IndiaChargeRateSet):
            raise TypeError("rate set must be an IndiaChargeRateSet")
        normalized.append(((product, side, event), rate_set))
    normalized.sort(key=lambda item: (item[0][0].value, item[0][1].value, item[0][2].value))
    return tuple(normalized)


def _normalize_entries(value: object) -> tuple[IndiaChargeScheduleEntry, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(value)
    if value is None:
        return ()
    raise TypeError("entries must be a sequence")


def _validate_no_overlaps(entries: tuple[IndiaChargeScheduleEntry, ...]) -> None:
    for i, left in enumerate(entries):
        left_end = left.effective_to
        if left_end is None:
            left_end = datetime.max.replace(tzinfo=_IST)
        for right in entries[i + 1 :]:
            right_end = right.effective_to
            if right_end is None:
                right_end = datetime.max.replace(tzinfo=_IST)
            if left.effective_from < right_end and right.effective_from < left_end:
                raise ValueError("schedule entries must not overlap")


def _normalize_sources(value: object) -> tuple[tuple[str, str, str], ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        items = list(value)
    else:
        raise TypeError("component_sources must be a sequence")
    normalized = []
    for item in items:
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise TypeError("component source must be a (component, source, version) tuple")
        component, source, version = item
        if not isinstance(component, str) or not component.strip():
            raise ValueError("component source name must be non-empty")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("component source reference must be non-empty")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("component source version must be non-empty")
        normalized.append((component.strip(), source.strip(), version.strip()))
    normalized.sort(key=lambda item: item[0])
    if len({item[0] for item in normalized}) != len(normalized):
        raise ValueError("component sources must be unique")
    return tuple(normalized)


def _has_source(sources: tuple[tuple[str, str, str], ...], component: str) -> bool:
    return any(item[0] == component for item in sources)


def _source_for(rate_set: IndiaChargeRateSet, component: str) -> tuple[str, str]:
    for item in rate_set.component_sources:
        if item[0] == component:
            return item[1], item[2]
    raise IndiaChargeRuleUnavailable(f"missing source for charge component: {component}")


def _rate_set_for(
    entry: IndiaChargeScheduleEntry,
    key: tuple[object, object, object],
) -> IndiaChargeRateSet | None:
    for item in cast(tuple[object, ...], entry.rates):
        item_key, rate_set = cast(tuple[object, object], item)
        if item_key == key:
            return cast(IndiaChargeRateSet, rate_set)
    return None


def _stt_base(context: IndiaChargeCalculationContext) -> Decimal:
    if (
        context.product is IndiaChargeProduct.EQUITY_OPTIONS
        and context.event is IndiaChargeEvent.TRADE
    ):
        assert context.premium_value is not None
        return context.premium_value
    if context.event is IndiaChargeEvent.OPTION_EXERCISE:
        assert context.settlement_price is not None
        assert context.strike is not None
        assert context.quantity is not None
        if context.option_type is IndiaOptionType.CALL:
            return max(context.settlement_price - context.strike, Decimal("0")) * context.quantity
        return max(context.strike - context.settlement_price, Decimal("0")) * context.quantity
    return context.transaction_value


def _stamp_base(context: IndiaChargeCalculationContext) -> Decimal:
    if (
        context.product is IndiaChargeProduct.EQUITY_OPTIONS
        and context.event is IndiaChargeEvent.TRADE
    ):
        assert context.premium_value is not None
        return context.premium_value
    return context.transaction_value


def _exchange_base(context: IndiaChargeCalculationContext) -> Decimal:
    if (
        context.product is IndiaChargeProduct.EQUITY_OPTIONS
        and context.event is IndiaChargeEvent.TRADE
    ):
        assert context.premium_value is not None
        return context.premium_value
    return context.transaction_value


def _sebi_base(context: IndiaChargeCalculationContext) -> Decimal:
    if (
        context.product is IndiaChargeProduct.EQUITY_OPTIONS
        and context.event is IndiaChargeEvent.TRADE
    ):
        assert context.premium_value is not None
        return context.premium_value
    if context.event is IndiaChargeEvent.OPTION_EXERCISE:
        assert context.exercise_notional_value is not None
        return context.exercise_notional_value
    return context.transaction_value


def _rounded(value: Decimal) -> Decimal:
    return value.quantize(_PAISE, rounding=ROUND_HALF_UP)


def _rate_field(component: str) -> str:
    if component == "stt":
        return "stt_rate"
    if component == "sebi_turnover_fee":
        return "sebi_turnover_rate"
    return f"{component}_rate"


__all__ = [
    "IndiaChargeCalculationContext",
    "IndiaChargeEvent",
    "IndiaChargeIncidence",
    "IndiaChargeInputUnavailable",
    "IndiaOptionType",
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
