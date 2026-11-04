"""Deterministic Indian reference-data adapter for canonical instruments."""

from __future__ import annotations

from collections.abc import Iterable

from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.instruments import Contract, Instrument
from quantx.domain.value_objects import InstrumentId

from .domain import IndianInstrumentSpec


class IndianInstrumentCatalog(InstrumentRegistry):
    """Resolve canonical instruments and contract metadata from supplied specs.

    Registration converts each spec at the source boundary and fails closed
    when a derivative spec cannot produce complete canonical contract
    metadata. Derivative metadata is never inferred from a symbol and never
    silently dropped.
    """

    def __init__(self, specs: Iterable[IndianInstrumentSpec] = ()) -> None:
        self._instruments: dict[InstrumentId, Instrument] = {}
        self._contracts: dict[InstrumentId, Contract] = {}
        for spec in specs:
            self.add(spec)

    def resolve(self, instrument_id: InstrumentId) -> Instrument | None:
        return self._instruments.get(instrument_id)

    def resolve_contract(self, instrument_id: InstrumentId) -> Contract | None:
        """Return the registered canonical contract for a derivative, if any."""
        return self._contracts.get(instrument_id)

    def add(self, spec: IndianInstrumentSpec) -> None:
        instrument = spec.to_instrument()
        contract = spec.to_contract()
        self._instruments[spec.instrument_id] = instrument
        if contract is None:
            self._contracts.pop(spec.instrument_id, None)
        else:
            self._contracts[spec.instrument_id] = contract


__all__ = ["IndianInstrumentCatalog"]
