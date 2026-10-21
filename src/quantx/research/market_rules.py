"""Point-in-time market and instrument metadata for historical research.

The universal instrument identity remains market-neutral. Historical research
selects a versioned rule/contract record by timestamp instead of assuming that
current metadata was valid in the past.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from quantx.domain.instrument_registry import InstrumentRegistry, InstrumentResolution
from quantx.domain.instruments import DERIVATIVE_ASSET_CLASSES, Contract
from quantx.domain.value_objects import InstrumentId


class TradabilityStatus(StrEnum):
    TRADABLE = "TRADABLE"
    NOT_LISTED = "NOT_LISTED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class VersionedInstrumentRule:
    instrument_id: str
    effective_from: datetime
    effective_to: datetime | None
    tick_size: Decimal
    lot_size: Decimal
    multiplier: Decimal
    currency: str
    status: TradabilityStatus = TradabilityStatus.TRADABLE
    rule_version: str = "1"

    def __post_init__(self) -> None:
        if self.effective_from.tzinfo is None or self.effective_from.utcoffset() is None:
            raise ValueError("effective_from must be timezone-aware")
        if self.effective_to is not None:
            if self.effective_to.tzinfo is None or self.effective_to.utcoffset() is None:
                raise ValueError("effective_to must be timezone-aware")
            if self.effective_to <= self.effective_from:
                raise ValueError("effective_to must be after effective_from")
        if self.tick_size <= 0 or self.lot_size <= 0 or self.multiplier <= 0:
            raise ValueError("tick_size, lot_size, and multiplier must be positive")
        if not self.currency.strip() or not self.rule_version.strip():
            raise ValueError("currency and rule_version must not be empty")

    def applies_at(self, timestamp: datetime) -> bool:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return self.effective_from <= timestamp and (
            self.effective_to is None or timestamp < self.effective_to
        )


class PointInTimeInstrumentRegistry:
    """Select exactly one versioned instrument rule at a historical timestamp."""

    def __init__(self, rules: tuple[VersionedInstrumentRule, ...] = ()) -> None:
        self._rules: dict[str, tuple[VersionedInstrumentRule, ...]] = {}
        for rule in rules:
            self.add(rule)

    def add(self, rule: VersionedInstrumentRule) -> None:
        existing = self._rules.setdefault(rule.instrument_id, ())
        for other in existing:
            if self._overlaps(rule, other):
                raise ValueError(f"overlapping instrument rules for {rule.instrument_id}")
        self._rules[rule.instrument_id] = tuple(
            sorted((*existing, rule), key=lambda item: item.effective_from)
        )

    def resolve(self, instrument_id: str, timestamp: datetime) -> VersionedInstrumentRule:
        candidates = [
            rule for rule in self._rules.get(instrument_id, ()) if rule.applies_at(timestamp)
        ]
        if len(candidates) != 1:
            raise LookupError(
                f"no unique point-in-time rule for {instrument_id} at {timestamp.isoformat()}"
            )
        return candidates[0]

    @staticmethod
    def _overlaps(a: VersionedInstrumentRule, b: VersionedInstrumentRule) -> bool:
        a_end = a.effective_to or datetime.max.replace(tzinfo=a.effective_from.tzinfo)
        b_end = b.effective_to or datetime.max.replace(tzinfo=b.effective_from.tzinfo)
        return a.effective_from < b_end and b.effective_from < a_end


@dataclass(frozen=True, slots=True)
class PointInTimeTradability:
    instrument_id: str
    timestamp: datetime
    status: TradabilityStatus
    rule_version: str

    @property
    def tradable(self) -> bool:
        return self.status is TradabilityStatus.TRADABLE


def resolve_tradability(
    registry: PointInTimeInstrumentRegistry,
    instrument_id: str,
    timestamp: datetime,
) -> PointInTimeTradability:
    rule = registry.resolve(instrument_id, timestamp)
    return PointInTimeTradability(
        instrument_id=instrument_id,
        timestamp=timestamp,
        status=rule.status,
        rule_version=rule.rule_version,
    )


class InstrumentResolutionError(LookupError):
    """A point-in-time instrument/contract resolution cannot be made uniquely."""


@dataclass(frozen=True, slots=True)
class VersionedContractMetadata:
    """One effective-dated, versioned derivative contract metadata record.

    Contract metadata carries its own lifecycle, separate from the instrument
    trading-rule lifecycle. Corrected source records are new versions in a new
    effective window; historical windows are never overwritten so a
    historical resolution cannot silently adopt current metadata.
    """

    contract: Contract
    effective_from: datetime
    effective_to: datetime | None
    metadata_version: str
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.contract, Contract):
            raise ValueError("contract metadata record requires a canonical Contract")
        if self.effective_from.tzinfo is None or self.effective_from.utcoffset() is None:
            raise ValueError("contract effective_from must be timezone-aware")
        if self.effective_to is not None:
            if self.effective_to.tzinfo is None or self.effective_to.utcoffset() is None:
                raise ValueError("contract effective_to must be timezone-aware")
            if self.effective_to <= self.effective_from:
                raise ValueError("contract effective_to must be after effective_from")
        if not isinstance(self.metadata_version, str) or not self.metadata_version.strip():
            raise ValueError("contract metadata_version must not be empty")
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("contract metadata source must not be empty")

    def applies_at(self, timestamp: datetime) -> bool:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return self.effective_from <= timestamp and (
            self.effective_to is None or timestamp < self.effective_to
        )


class PointInTimeContractCatalog:
    """Select exactly one effective-dated contract record at a timestamp."""

    def __init__(self, records: tuple[VersionedContractMetadata, ...] = ()) -> None:
        self._records: dict[InstrumentId, tuple[VersionedContractMetadata, ...]] = {}
        for record in records:
            self.add(record)

    def add(self, record: VersionedContractMetadata) -> None:
        if not isinstance(record, VersionedContractMetadata):
            raise ValueError("contract catalog requires VersionedContractMetadata records")
        instrument_id = record.contract.instrument_id
        existing = self._records.get(instrument_id, ())
        for other in existing:
            if other.metadata_version == record.metadata_version:
                raise ValueError(
                    f"duplicate contract metadata version {record.metadata_version} "
                    f"for {instrument_id}"
                )
            if self._overlaps(record, other):
                raise ValueError(f"overlapping contract metadata for {instrument_id}")
        self._records[instrument_id] = tuple(
            sorted((*existing, record), key=lambda item: item.effective_from)
        )

    def records_for(self, instrument_id: InstrumentId) -> tuple[VersionedContractMetadata, ...]:
        """Return every registered record for one identity, oldest first."""
        return self._records.get(instrument_id, ())

    def resolve(
        self, instrument_id: InstrumentId, timestamp: datetime
    ) -> VersionedContractMetadata:
        candidates = [
            record
            for record in self._records.get(instrument_id, ())
            if record.applies_at(timestamp)
        ]
        if len(candidates) != 1:
            raise InstrumentResolutionError(
                "no unique point-in-time contract metadata for "
                f"{instrument_id} at {timestamp.isoformat()}"
            )
        return candidates[0]

    @staticmethod
    def _overlaps(a: VersionedContractMetadata, b: VersionedContractMetadata) -> bool:
        a_end = a.effective_to or datetime.max.replace(tzinfo=a.effective_from.tzinfo)
        b_end = b.effective_to or datetime.max.replace(tzinfo=b.effective_from.tzinfo)
        return a.effective_from < b_end and b.effective_from < a_end


@dataclass(frozen=True, slots=True)
class PointInTimeInstrumentResolver:
    """Compose instrument facts, trading rule, and contract metadata at one instant.

    This is the only point-in-time resolution seam. It returns exactly one
    canonical instrument, exactly one applicable contract record for a
    derivative, and the selected rule/contract versions plus provenance. A
    missing instrument, missing/overlapping rule window, missing or malformed
    contract record fails closed; there is no fallback to current metadata.
    Tradability is deliberately not required here: an applicable contract
    record does not assert that the contract was tradable at that instant.
    """

    instruments: InstrumentRegistry
    rules: PointInTimeInstrumentRegistry
    contracts: PointInTimeContractCatalog

    def resolve_at(self, instrument_id: InstrumentId, timestamp: datetime) -> InstrumentResolution:
        if not isinstance(instrument_id, InstrumentId):
            raise ValueError("instrument resolution requires a canonical InstrumentId")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("instrument resolution timestamp must be timezone-aware")

        instrument = self.instruments.resolve(instrument_id)
        if instrument is None:
            raise InstrumentResolutionError(f"instrument metadata unavailable for {instrument_id}")
        if instrument.instrument_id != instrument_id:
            raise InstrumentResolutionError(
                f"instrument registry returned a different identity for {instrument_id}"
            )

        try:
            rule = self.rules.resolve(str(instrument_id), timestamp)
        except LookupError as exc:
            raise InstrumentResolutionError(str(exc)) from exc

        if instrument.asset_class in DERIVATIVE_ASSET_CLASSES:
            record = self.contracts.resolve(instrument_id, timestamp)
            if record.contract.asset_class is not instrument.asset_class:
                raise InstrumentResolutionError(
                    f"contract metadata asset class contradicts {instrument_id}"
                )
            return InstrumentResolution(
                instrument=instrument,
                contract=record.contract,
                instrument_rule_version=rule.rule_version,
                instrument_rule_effective_from=rule.effective_from,
                resolved_at=timestamp,
                contract_metadata_version=record.metadata_version,
                contract_source=record.source,
                contract_effective_from=record.effective_from,
            )

        if self.contracts.records_for(instrument_id):
            raise InstrumentResolutionError(
                f"contract metadata is registered for non-derivative instrument {instrument_id}"
            )
        return InstrumentResolution(
            instrument=instrument,
            instrument_rule_version=rule.rule_version,
            instrument_rule_effective_from=rule.effective_from,
            resolved_at=timestamp,
        )


__all__ = [
    "InstrumentResolutionError",
    "PointInTimeContractCatalog",
    "PointInTimeInstrumentRegistry",
    "PointInTimeInstrumentResolver",
    "PointInTimeTradability",
    "TradabilityStatus",
    "VersionedContractMetadata",
    "VersionedInstrumentRule",
    "resolve_tradability",
]
