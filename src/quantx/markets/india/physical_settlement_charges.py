"""Source-bounded physical-settlement stamp-duty calculation for NSE India.

This module consumes clearing-recognized delivery obligations and an explicit
final settlement price. It does not infer assignments from local positions,
compute final settlement prices, calculate physical-settlement STT, or contain
production tariff data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, DecimalException, ROUND_HALF_UP
from enum import StrEnum
from zoneinfo import ZoneInfo

from quantx.domain.value_objects import InstrumentId

_ZERO = Decimal("0")
_PAISE = Decimal("0.01")
_RUPEE = Decimal("1")
_IST = ZoneInfo("Asia/Kolkata")
_COMPONENT_NAMES = ("delivery_stamp_duty", "non_delivery_stamp_duty")


class IndiaPhysicalSettlementRuleUnavailable(ValueError):
    """A required effective-dated rate or supported settlement rule is absent."""


class IndiaPhysicalSettlementInputUnavailable(ValueError):
    """A required clearing, client-jurisdiction, or price input is absent."""


class IndiaPhysicalSettlementCollectionDisposition(StrEnum):
    NCL_COLLECTION_APPLIES = "NCL_COLLECTION_APPLIES"
    NCL_COLLECTION_EXCLUDED_FOR_SIKKIM = "NCL_COLLECTION_EXCLUDED_FOR_SIKKIM"


class IndiaPhysicalSettlementJurisdictionSource(StrEnum):
    CLIENT_CODE = "CLIENT_CODE"
    TRADING_MEMBER_FALLBACK = "TRADING_MEMBER_FALLBACK"


@dataclass(frozen=True, slots=True)
class IndiaPhysicalSettlementStampDutyRates:
    """Explicitly sourced delivery and non-delivery stamp-duty rates.

    The contract accepts rate data but embeds no production defaults. A missing
    rate remains None and fails a calculation; it is never converted to zero.
    """

    delivery_stamp_duty_rate: Decimal | None
    non_delivery_stamp_duty_rate: Decimal | None
    component_sources: tuple[tuple[str, str, str], ...]

    def __post_init__(self) -> None:
        _validate_decimal(
            self.delivery_stamp_duty_rate, "delivery_stamp_duty_rate", allow_none=True
        )
        _validate_decimal(
            self.non_delivery_stamp_duty_rate,
            "non_delivery_stamp_duty_rate",
            allow_none=True,
        )
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
            raise ValueError("every physical stamp component requires source/version evidence")
        object.__setattr__(self, "component_sources", tuple(sorted(normalized)))

    def source_for(self, component_name: str) -> tuple[str, str]:
        for name, source_ref, rule_version in self.component_sources:
            if name == component_name:
                return source_ref, rule_version
        raise IndiaPhysicalSettlementRuleUnavailable("stamp component source is unavailable")


@dataclass(frozen=True, slots=True)
class IndiaPhysicalSettlementStampDutyScheduleEntry:
    """One effective interval for the two physical-settlement stamp rates."""

    effective_from: datetime
    effective_to: datetime | None
    version: str
    rates: IndiaPhysicalSettlementStampDutyRates

    def __post_init__(self) -> None:
        _validate_ist_midnight(self.effective_from, "effective_from")
        if self.effective_to is not None:
            _validate_ist_midnight(self.effective_to, "effective_to")
            if self.effective_from >= self.effective_to:
                raise ValueError("effective_from must be earlier than effective_to")
        _require_text(self.version, "schedule entry version")
        if not isinstance(self.rates, IndiaPhysicalSettlementStampDutyRates):
            raise TypeError("rates must be IndiaPhysicalSettlementStampDutyRates")


@dataclass(frozen=True, slots=True)
class IndiaPhysicalSettlementStampDutySchedule:
    """Immutable, non-overlapping, effective-dated physical stamp schedule."""

    entries: tuple[IndiaPhysicalSettlementStampDutyScheduleEntry, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.entries, tuple):
            raise TypeError("schedule entries must be an immutable tuple")
        if not self.entries:
            raise ValueError("physical stamp schedule must contain at least one entry")
        if not all(
            isinstance(entry, IndiaPhysicalSettlementStampDutyScheduleEntry)
            for entry in self.entries
        ):
            raise TypeError("schedule entries must be physical stamp schedule entries")
        ordered = tuple(sorted(self.entries, key=lambda entry: entry.effective_from))
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.effective_to is None or previous.effective_to > current.effective_from:
                raise ValueError("physical stamp schedule intervals must not overlap")
        object.__setattr__(self, "entries", ordered)

    def select(self, effective_at: datetime) -> IndiaPhysicalSettlementStampDutyScheduleEntry:
        if not isinstance(effective_at, datetime) or not _is_aware(effective_at):
            raise IndiaPhysicalSettlementRuleUnavailable(
                "settlement_date must be timezone-aware"
            )
        normalized = effective_at.astimezone(_IST)
        for entry in self.entries:
            start = entry.effective_from.astimezone(_IST)
            end = entry.effective_to.astimezone(_IST) if entry.effective_to is not None else None
            if start <= normalized and (end is None or normalized < end):
                return entry
        raise IndiaPhysicalSettlementRuleUnavailable(
            "no physical stamp schedule covers settlement_date"
        )


@dataclass(frozen=True, slots=True)
class IndiaPhysicalSettlementSecuritySettlementInput:
    """One pre-aggregated client/security/delivery-settlement group.

    BQTY/SQTY must aggregate all clearing-recognized futures and options
    delivery positions for this client/security/day. They must not be guessed
    from local net positions or supplied as separate rows per derivative
    contract. The final settlement price and its methodology are explicit,
    sourced inputs.
    """

    settlement_id: str
    security_id: InstrumentId
    security_receivable_quantity: Decimal
    security_deliverable_quantity: Decimal
    final_settlement_price: Decimal
    final_settlement_price_source_ref: str
    final_settlement_price_method_version: str
    obligation_source_ref: str

    def __post_init__(self) -> None:
        _require_text(self.settlement_id, "settlement_id")
        if not isinstance(self.security_id, InstrumentId):
            raise TypeError("security_id must be an InstrumentId")
        if self.security_id.venue != "NSE":
            raise IndiaPhysicalSettlementRuleUnavailable(
                "only NSE physical-settlement securities are supported"
            )
        _validate_decimal(self.security_receivable_quantity, "security_receivable_quantity", allow_none=False)
        _validate_decimal(self.security_deliverable_quantity, "security_deliverable_quantity", allow_none=False)
        _validate_decimal(
            self.final_settlement_price, "final_settlement_price", allow_none=False
        )
        if self.final_settlement_price <= _ZERO:
            raise ValueError("final_settlement_price must be positive")
        if self.security_receivable_quantity == _ZERO and self.security_deliverable_quantity == _ZERO:
            raise ValueError("at least one clearing settlement quantity must be positive")
        _require_text(
            self.final_settlement_price_source_ref, "final_settlement_price_source_ref"
        )
        _require_text(
            self.final_settlement_price_method_version,
            "final_settlement_price_method_version",
        )
        _require_text(self.obligation_source_ref, "obligation_source_ref")


@dataclass(frozen=True, slots=True)
class IndiaPhysicalSettlementStampDutyClientContext:
    """One client's physical-settlement stamp calculation for a settlement day.

    client_code is the exchange client code after permitted client-code
    modifications. For proprietary transactions it must equal the member code.
    The code is hidden from repr and is not copied into result provenance.
    """

    settlement_date: datetime
    client_code: str = field(repr=False)
    is_proprietary: bool
    trading_member_code: str = field(repr=False)
    client_code_source_ref: str
    client_state_ut: str | None
    client_state_source_ref: str | None
    trading_member_state_ut: str | None
    trading_member_state_source_ref: str | None
    settlements: tuple[IndiaPhysicalSettlementSecuritySettlementInput, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.settlement_date, datetime) or not _is_aware(
            self.settlement_date
        ):
            raise IndiaPhysicalSettlementInputUnavailable(
                "settlement_date must be timezone-aware"
            )
        _require_text(self.client_code, "client_code")
        _require_text(self.trading_member_code, "trading_member_code")
        _require_text(self.client_code_source_ref, "client_code_source_ref")
        if not isinstance(self.is_proprietary, bool):
            raise TypeError("is_proprietary must be boolean")
        if self.is_proprietary and self.client_code != self.trading_member_code:
            raise IndiaPhysicalSettlementInputUnavailable(
                "proprietary settlement must use the trading-member code as client code"
            )
        _validate_state_and_source(
            self.client_state_ut,
            self.client_state_source_ref,
            "client_state_ut",
            "client_state_source_ref",
        )
        _validate_state_and_source(
            self.trading_member_state_ut,
            self.trading_member_state_source_ref,
            "trading_member_state_ut",
            "trading_member_state_source_ref",
        )
        if self.client_state_ut is None and self.trading_member_state_ut is None:
            raise IndiaPhysicalSettlementInputUnavailable(
                "client State/UT and trading-member fallback State/UT are unavailable"
            )
        if not isinstance(self.settlements, tuple) or not self.settlements:
            raise IndiaPhysicalSettlementInputUnavailable(
                "settlements must be a non-empty immutable tuple"
            )
        if not all(
            isinstance(item, IndiaPhysicalSettlementSecuritySettlementInput)
            for item in self.settlements
        ):
            raise TypeError("settlements must contain physical security settlement inputs")
        settlement_ids = [item.settlement_id for item in self.settlements]
        if len(settlement_ids) != len(set(settlement_ids)):
            raise ValueError("settlement_id values must be unique per client settlement day")
        security_ids = [item.security_id for item in self.settlements]
        if len(security_ids) != len(set(security_ids)):
            raise IndiaPhysicalSettlementInputUnavailable(
                "settlement inputs must be pre-aggregated to one BQTY/SQTY group "
                "per client/security/settlement day"
            )


@dataclass(frozen=True, slots=True)
class IndiaPhysicalSettlementStampDutyLine:
    """Paise-rounded delivery and non-delivery stamp duty for one group."""

    settlement_id: str
    security_id: InstrumentId
    security_receivable_quantity: Decimal
    security_deliverable_quantity: Decimal
    deliverable_quantity: Decimal
    non_deliverable_quantity: Decimal
    final_settlement_price: Decimal
    deliverable_value: Decimal
    non_deliverable_value: Decimal
    delivery_stamp_duty: Decimal
    non_delivery_stamp_duty: Decimal

    @property
    def total(self) -> Decimal:
        return self.delivery_stamp_duty + self.non_delivery_stamp_duty


@dataclass(frozen=True, slots=True)
class IndiaPhysicalSettlementStampDutyResult:
    """Client-level result with NCL collection disposition and provenance.

    client_level_total is None when NCL does not collect the duty for Sikkim;
    None is deliberately distinct from a calculated zero amount.
    """

    collection_disposition: IndiaPhysicalSettlementCollectionDisposition
    jurisdiction_state_ut: str
    jurisdiction_source: IndiaPhysicalSettlementJurisdictionSource
    schedule_version: str | None
    settlements: tuple[IndiaPhysicalSettlementStampDutyLine, ...]
    client_level_total: Decimal | None
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(
            self.collection_disposition, IndiaPhysicalSettlementCollectionDisposition
        ):
            raise TypeError("collection_disposition has an unsupported type")
        _require_text(self.jurisdiction_state_ut, "jurisdiction_state_ut")
        if not isinstance(
            self.jurisdiction_source, IndiaPhysicalSettlementJurisdictionSource
        ):
            raise TypeError("jurisdiction_source has an unsupported type")
        if self.jurisdiction_state_ut != self.jurisdiction_state_ut.strip().upper():
            raise ValueError("jurisdiction_state_ut must be normalized")
        if not isinstance(self.settlements, tuple):
            raise TypeError("settlements must be an immutable tuple")
        if not all(
            isinstance(item, IndiaPhysicalSettlementStampDutyLine)
            for item in self.settlements
        ):
            raise TypeError("settlements must contain physical stamp-duty lines")
        if not isinstance(self.provenance, tuple) or not self.provenance or not all(
            isinstance(item, str) and item.strip() for item in self.provenance
        ):
            raise ValueError("provenance must contain non-empty strings")
        if (
            self.collection_disposition
            is IndiaPhysicalSettlementCollectionDisposition.NCL_COLLECTION_APPLIES
        ):
            _require_text(self.schedule_version, "schedule_version")
            if self.jurisdiction_state_ut == "SIKKIM":
                raise ValueError("Sikkim must use the NCL-excluded disposition")
            if not self.settlements or self.client_level_total is None:
                raise ValueError("NCL-applicable result requires settlement lines and client total")
            _validate_decimal(self.client_level_total, "client_level_total", allow_none=False)
            expected_total = _round_client_rupee(
                sum((item.total for item in self.settlements), _ZERO)
            )
            if self.client_level_total != expected_total:
                raise ValueError("client_level_total does not match the rounded settlement lines")
        else:
            if self.jurisdiction_state_ut != "SIKKIM":
                raise ValueError("NCL-excluded disposition is only valid for Sikkim")
            if (
                self.schedule_version is not None
                or self.settlements
                or self.client_level_total is not None
            ):
                raise ValueError(
                    "NCL-excluded result must not carry a zero-valued charge calculation"
                )


@dataclass(frozen=True, slots=True)
class IndiaPhysicalSettlementStampDutyModel:
    """Calculate NCL physical-settlement stamp duty; no STT or production tariff wiring."""

    schedule: IndiaPhysicalSettlementStampDutySchedule

    def __post_init__(self) -> None:
        if not isinstance(self.schedule, IndiaPhysicalSettlementStampDutySchedule):
            raise TypeError("schedule must be IndiaPhysicalSettlementStampDutySchedule")

    @property
    def model_id(self) -> str:
        return "india.physical_settlement_stamp_duty"

    @property
    def model_version(self) -> str:
        return "1"

    def calculate(
        self, context: IndiaPhysicalSettlementStampDutyClientContext
    ) -> IndiaPhysicalSettlementStampDutyResult:
        if not isinstance(context, IndiaPhysicalSettlementStampDutyClientContext):
            raise IndiaPhysicalSettlementInputUnavailable(
                "physical settlement client context is required"
            )
        jurisdiction, jurisdiction_source = _resolve_jurisdiction(context)
        base_provenance = [
            f"model:{self.model_id}:{self.model_version}",
            f"settlement_date:{context.settlement_date.isoformat()}",
            f"client_code_source:{context.client_code_source_ref}",
            (
                "client_code_kind:"
                f"{'TRADING_MEMBER_CODE' if context.is_proprietary else 'CLIENT_CODE'}"
            ),
            f"jurisdiction:{jurisdiction}:{jurisdiction_source.value}",
        ]
        if jurisdiction_source is IndiaPhysicalSettlementJurisdictionSource.CLIENT_CODE:
            assert context.client_state_source_ref is not None
            base_provenance.append(f"client_state_source:{context.client_state_source_ref}")
        else:
            assert context.trading_member_state_source_ref is not None
            base_provenance.append(
                f"trading_member_state_fallback:{context.trading_member_state_source_ref}"
            )

        if jurisdiction == "SIKKIM":
            base_provenance.append(
                "collection_disposition:NCL_COLLECTION_EXCLUDED_FOR_SIKKIM"
            )
            return IndiaPhysicalSettlementStampDutyResult(
                collection_disposition=(
                    IndiaPhysicalSettlementCollectionDisposition.NCL_COLLECTION_EXCLUDED_FOR_SIKKIM
                ),
                jurisdiction_state_ut=jurisdiction,
                jurisdiction_source=jurisdiction_source,
                schedule_version=None,
                settlements=(),
                client_level_total=None,
                provenance=tuple(base_provenance),
            )

        entry = self.schedule.select(context.settlement_date)
        rates = entry.rates
        delivery_rate = rates.delivery_stamp_duty_rate
        non_delivery_rate = rates.non_delivery_stamp_duty_rate
        if delivery_rate is None:
            raise IndiaPhysicalSettlementRuleUnavailable(
                "delivery stamp-duty rate is unavailable"
            )
        if non_delivery_rate is None:
            raise IndiaPhysicalSettlementRuleUnavailable(
                "non-delivery stamp-duty rate is unavailable"
            )

        lines: list[IndiaPhysicalSettlementStampDutyLine] = []
        for settlement in context.settlements:
            try:
                deliverable_quantity = max(
                    settlement.security_receivable_quantity - settlement.security_deliverable_quantity, _ZERO
                )
                non_deliverable_quantity = min(
                    settlement.security_receivable_quantity, settlement.security_deliverable_quantity
                )
                deliverable_value = (
                    deliverable_quantity * settlement.final_settlement_price
                )
                non_deliverable_value = (
                    non_deliverable_quantity * settlement.final_settlement_price
                )
                delivery_duty = _round_paise(deliverable_value * delivery_rate)
                non_delivery_duty = _round_paise(
                    non_deliverable_value * non_delivery_rate
                )
            except DecimalException as exc:
                raise IndiaPhysicalSettlementInputUnavailable(
                    "physical stamp-duty arithmetic is outside Decimal limits"
                ) from exc
            lines.append(
                IndiaPhysicalSettlementStampDutyLine(
                    settlement_id=settlement.settlement_id,
                    security_id=settlement.security_id,
                    security_receivable_quantity=settlement.security_receivable_quantity,
                    security_deliverable_quantity=settlement.security_deliverable_quantity,
                    deliverable_quantity=deliverable_quantity,
                    non_deliverable_quantity=non_deliverable_quantity,
                    final_settlement_price=settlement.final_settlement_price,
                    deliverable_value=deliverable_value,
                    non_deliverable_value=non_deliverable_value,
                    delivery_stamp_duty=delivery_duty,
                    non_delivery_stamp_duty=non_delivery_duty,
                )
            )
            base_provenance.extend(
                (
                    f"settlement:{settlement.settlement_id}:security:{settlement.security_id}",
                    (
                        f"obligation_source:{settlement.settlement_id}:"
                        f"{settlement.obligation_source_ref}"
                    ),
                    (
                        "final_settlement_price:"
                        f"{settlement.settlement_id}:"
                        f"{settlement.final_settlement_price_source_ref}"
                    ),
                    (
                        "final_settlement_price_method:"
                        f"{settlement.settlement_id}:"
                        f"{settlement.final_settlement_price_method_version}"
                    ),
                )
            )

        try:
            total_before_client_rounding = sum((line.total for line in lines), _ZERO)
            client_total = _round_client_rupee(total_before_client_rounding)
        except DecimalException as exc:
            raise IndiaPhysicalSettlementInputUnavailable(
                "client-level stamp-duty aggregation is outside Decimal limits"
            ) from exc
        for name, source_ref, rule_version in rates.component_sources:
            base_provenance.append(f"component:{name}:{rule_version}:{source_ref}")
        base_provenance.extend(
            (
                f"schedule:{entry.version}",
                f"effective_interval:{entry.effective_from.isoformat()}.."
                f"{entry.effective_to.isoformat() if entry.effective_to else 'open'}",
                (
                    "rounding:ROUND_HALF_UP_to_INR_paise_per_component_"
                    "per_client_security_delivery_settlement"
                ),
                "rounding:ROUND_HALF_UP_to_nearest_INR_rupee_at_client_level_50_paise_up",
                "collection_disposition:NCL_COLLECTION_APPLIES",
            )
        )
        return IndiaPhysicalSettlementStampDutyResult(
            collection_disposition=(
                IndiaPhysicalSettlementCollectionDisposition.NCL_COLLECTION_APPLIES
            ),
            jurisdiction_state_ut=jurisdiction,
            jurisdiction_source=jurisdiction_source,
            schedule_version=entry.version,
            settlements=tuple(lines),
            client_level_total=client_total,
            provenance=tuple(base_provenance),
        )


def _resolve_jurisdiction(
    context: IndiaPhysicalSettlementStampDutyClientContext,
) -> tuple[str, IndiaPhysicalSettlementJurisdictionSource]:
    if context.client_state_ut is not None:
        return (
            context.client_state_ut.strip().upper(),
            IndiaPhysicalSettlementJurisdictionSource.CLIENT_CODE,
        )
    assert context.trading_member_state_ut is not None
    return (
        context.trading_member_state_ut.strip().upper(),
        IndiaPhysicalSettlementJurisdictionSource.TRADING_MEMBER_FALLBACK,
    )


def _validate_state_and_source(
    state: str | None,
    source_ref: str | None,
    state_name: str,
    source_name: str,
) -> None:
    if state is None:
        if source_ref is not None:
            raise ValueError(f"{source_name} requires {state_name}")
        return
    _require_text(state, state_name)
    _require_text(source_ref, source_name)


def _validate_decimal(
    value: Decimal | None, name: str, *, allow_none: bool = True
) -> None:
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


def _round_paise(value: Decimal) -> Decimal:
    try:
        if not value.is_finite() or value < _ZERO:
            raise IndiaPhysicalSettlementInputUnavailable(
                "stamp-duty amount must be finite and non-negative"
            )
        return value.quantize(_PAISE, rounding=ROUND_HALF_UP)
    except DecimalException as exc:
        raise IndiaPhysicalSettlementInputUnavailable(
            "stamp-duty amount cannot be rounded to paise"
        ) from exc


def _round_client_rupee(value: Decimal) -> Decimal:
    try:
        if not value.is_finite() or value < _ZERO:
            raise IndiaPhysicalSettlementInputUnavailable(
                "client stamp-duty total must be finite and non-negative"
            )
        return value.quantize(_RUPEE, rounding=ROUND_HALF_UP)
    except DecimalException as exc:
        raise IndiaPhysicalSettlementInputUnavailable(
            "client stamp-duty total cannot be rounded to rupees"
        ) from exc


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
    "IndiaPhysicalSettlementCollectionDisposition",
    "IndiaPhysicalSettlementSecuritySettlementInput",
    "IndiaPhysicalSettlementInputUnavailable",
    "IndiaPhysicalSettlementJurisdictionSource",
    "IndiaPhysicalSettlementStampDutyClientContext",
    "IndiaPhysicalSettlementStampDutyLine",
    "IndiaPhysicalSettlementStampDutyModel",
    "IndiaPhysicalSettlementStampDutyRates",
    "IndiaPhysicalSettlementStampDutyResult",
    "IndiaPhysicalSettlementStampDutySchedule",
    "IndiaPhysicalSettlementStampDutyScheduleEntry",
    "IndiaPhysicalSettlementRuleUnavailable",
]
