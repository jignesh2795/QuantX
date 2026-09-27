"""Deterministic Indian reference-data adapter for canonical instruments."""

from __future__ import annotations

from collections.abc import Iterable

from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.instruments import Instrument
from quantx.domain.value_objects import InstrumentId

from .domain import IndianInstrumentSpec


class IndianInstrumentCatalog(InstrumentRegistry):
    """Resolve canonical instruments from explicitly supplied Indian metadata."""

    def __init__(self, specs: Iterable[IndianInstrumentSpec] = ()) -> None:
        self._instruments = {spec.instrument_id: spec.to_instrument() for spec in specs}

    def resolve(self, instrument_id: InstrumentId) -> Instrument | None:
        return self._instruments.get(instrument_id)

    def add(self, spec: IndianInstrumentSpec) -> None:
        self._instruments[spec.instrument_id] = spec.to_instrument()


__all__ = ["IndianInstrumentCatalog"]
