"""Canonical instrument resolution boundary.

Execution code must consume instrument metadata from an explicit registry. It
must never manufacture market, currency, lot-size, tick-size, or multiplier
values when valuing or accounting for a position.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .instruments import DERIVATIVE_ASSET_CLASSES, Contract, Instrument
from .value_objects import InstrumentId, canonical_instant


class InstrumentRegistry(Protocol):
    """Resolve an instrument from authoritative or explicitly supplied data."""

    def resolve(self, instrument_id: InstrumentId) -> Instrument | None:
        """Return the canonical instrument, or None when it is unavailable."""


class InstrumentResolutionResolver(Protocol):
    """Resolve instrument facts, contract metadata, and rule identity at one instant."""

    def resolve_at(self, instrument_id: InstrumentId, timestamp: datetime) -> InstrumentResolution:
        """Return exactly one point-in-time resolution, or fail closed."""


@dataclass(frozen=True, slots=True)
class InstrumentResolution:
    """One explicit point-in-time resolution of instrument and contract identity.

    The resolution composes the canonical ``Instrument`` with the derivative
    ``Contract`` that applies at ``resolved_at``, plus the selected
    instrument-rule version and contract metadata version/provenance. A
    derivative resolution always carries its contract; a non-derivative
    resolution never fabricates one. The selected identities are immutable and
    are what risk, the approved request, the fingerprint, recovery, and the
    broker preflight bind to.
    """

    instrument: Instrument
    instrument_rule_version: str
    instrument_rule_effective_from: datetime
    resolved_at: datetime
    contract: Contract | None = None
    contract_metadata_version: str | None = None
    contract_source: str | None = None
    contract_effective_from: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.instrument, Instrument):
            raise ValueError("instrument resolution requires a canonical Instrument")
        if not isinstance(self.instrument_rule_version, str) or not (
            self.instrument_rule_version.strip()
        ):
            raise ValueError("instrument resolution requires an instrument rule version")
        if not isinstance(self.instrument_rule_effective_from, datetime):
            raise ValueError("instrument rule effective_from must be a datetime")
        if (
            self.instrument_rule_effective_from.tzinfo is None
            or self.instrument_rule_effective_from.utcoffset() is None
        ):
            raise ValueError("instrument rule effective_from must be timezone-aware")
        if not isinstance(self.resolved_at, datetime):
            raise ValueError("instrument resolution timestamp must be a datetime")
        if self.resolved_at.tzinfo is None or self.resolved_at.utcoffset() is None:
            raise ValueError("instrument resolution timestamp must be timezone-aware")
        if self.instrument_rule_effective_from > self.resolved_at:
            raise ValueError("instrument rule is not effective at the resolution timestamp")

        derivative = self.instrument.asset_class in DERIVATIVE_ASSET_CLASSES
        if derivative:
            if not isinstance(self.contract, Contract):
                raise ValueError(
                    "a derivative instrument resolution requires canonical contract metadata"
                )
            if self.contract.instrument_id != self.instrument.instrument_id:
                raise ValueError(
                    "contract metadata instrument does not match the resolved instrument"
                )
            if self.contract.asset_class is not self.instrument.asset_class:
                raise ValueError(
                    "contract metadata asset class does not match the resolved instrument"
                )
            if not isinstance(self.contract_metadata_version, str) or not (
                self.contract_metadata_version.strip()
            ):
                raise ValueError("a derivative resolution requires a contract metadata version")
            if not isinstance(self.contract_source, str) or not self.contract_source.strip():
                raise ValueError("a derivative resolution requires contract metadata provenance")
            if not isinstance(self.contract_effective_from, datetime):
                raise ValueError("contract effective_from must be a datetime")
            if (
                self.contract_effective_from.tzinfo is None
                or self.contract_effective_from.utcoffset() is None
            ):
                raise ValueError("contract effective_from must be timezone-aware")
            if self.contract_effective_from > self.resolved_at:
                raise ValueError("contract metadata is not effective at the resolution timestamp")
            return

        if self.contract is not None:
            raise ValueError("a non-derivative instrument resolution must not carry a contract")
        if (
            self.contract_metadata_version is not None
            or self.contract_source is not None
            or self.contract_effective_from is not None
        ):
            raise ValueError(
                "a non-derivative instrument resolution must not carry contract provenance"
            )

    def identity_payload(self) -> dict[str, object]:
        """Selected metadata only, excluding the resolution timestamp.

        The canonical instrument facts, the applicable contract, and the
        selected rule/contract versions and provenance are all execution
        semantics: two resolutions are the same execution semantics only when
        every one of them agrees, even when they were resolved at different
        instants inside the same effective window. Hashing the instrument
        facts here also keeps durable recovery from silently substituting
        different tick/lot/multiplier values for the resolved instrument. The
        resolution timestamp itself is provenance.
        """
        return {
            "instrument": self.instrument.to_payload(),
            "contract": None if self.contract is None else self.contract.to_payload(),
            "instrument_rule_version": self.instrument_rule_version,
            "instrument_rule_effective_from": canonical_instant(
                self.instrument_rule_effective_from
            ),
            "contract_metadata_version": self.contract_metadata_version,
            "contract_source": self.contract_source,
            "contract_effective_from": (
                None
                if self.contract_effective_from is None
                else canonical_instant(self.contract_effective_from)
            ),
        }

    def to_payload(self) -> dict[str, object]:
        """Lossless serializable resolution evidence."""
        return {
            "instrument": self.instrument.to_payload(),
            "contract": None if self.contract is None else self.contract.to_payload(),
            "instrument_rule_version": self.instrument_rule_version,
            "instrument_rule_effective_from": canonical_instant(
                self.instrument_rule_effective_from
            ),
            "resolved_at": canonical_instant(self.resolved_at),
            "contract_metadata_version": self.contract_metadata_version,
            "contract_source": self.contract_source,
            "contract_effective_from": (
                None
                if self.contract_effective_from is None
                else canonical_instant(self.contract_effective_from)
            ),
        }

    @classmethod
    def from_payload(cls, payload: object) -> InstrumentResolution:
        """Rebuild resolution evidence, rejecting missing or unexpected fields."""
        if not isinstance(payload, dict):
            raise ValueError("instrument resolution must be an object")
        expected = {
            "instrument",
            "contract",
            "instrument_rule_version",
            "instrument_rule_effective_from",
            "resolved_at",
            "contract_metadata_version",
            "contract_source",
            "contract_effective_from",
        }
        if set(payload) != expected:
            raise ValueError("instrument resolution has unexpected fields")
        rule_version = payload["instrument_rule_version"]
        rule_effective_from = payload["instrument_rule_effective_from"]
        resolved_at = payload["resolved_at"]
        contract_version = payload["contract_metadata_version"]
        contract_source = payload["contract_source"]
        contract_effective_from = payload["contract_effective_from"]
        if not isinstance(rule_version, str):
            raise ValueError("instrument resolution rule version must be a string")
        if not isinstance(rule_effective_from, str) or not isinstance(resolved_at, str):
            raise ValueError("instrument resolution timestamps must be strings")
        if contract_version is not None and not isinstance(contract_version, str):
            raise ValueError("contract metadata version must be a string or None")
        if contract_source is not None and not isinstance(contract_source, str):
            raise ValueError("contract metadata source must be a string or None")
        if contract_effective_from is not None and not isinstance(contract_effective_from, str):
            raise ValueError("contract effective_from must be a string or None")
        contract_value = payload["contract"]
        return cls(
            instrument=Instrument.from_payload(payload["instrument"]),
            contract=None if contract_value is None else Contract.from_payload(contract_value),
            instrument_rule_version=rule_version,
            instrument_rule_effective_from=datetime.fromisoformat(rule_effective_from),
            resolved_at=datetime.fromisoformat(resolved_at),
            contract_metadata_version=contract_version,
            contract_source=contract_source,
            contract_effective_from=(
                None
                if contract_effective_from is None
                else datetime.fromisoformat(contract_effective_from)
            ),
        )


class InMemoryInstrumentRegistry:
    """Small deterministic registry suitable for tests and local simulation."""

    def __init__(self, instruments: tuple[Instrument, ...] = ()) -> None:
        self._instruments = {instrument.instrument_id: instrument for instrument in instruments}

    def resolve(self, instrument_id: InstrumentId) -> Instrument | None:
        return self._instruments.get(instrument_id)

    def add(self, instrument: Instrument) -> None:
        self._instruments[instrument.instrument_id] = instrument


__all__ = [
    "InMemoryInstrumentRegistry",
    "InstrumentRegistry",
    "InstrumentResolution",
    "InstrumentResolutionResolver",
]
