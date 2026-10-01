"""Canonical instrument resolution boundary.

Execution code must consume instrument metadata from an explicit registry. It
must never manufacture market, currency, lot-size, tick-size, or multiplier
values when valuing or accounting for a position.
"""

from __future__ import annotations

from typing import Protocol

from .instruments import Instrument
from .value_objects import InstrumentId


class InstrumentRegistry(Protocol):
    """Resolve an instrument from authoritative or explicitly supplied data."""

    def resolve(self, instrument_id: InstrumentId) -> Instrument | None:
        """Return the canonical instrument, or None when it is unavailable."""


class InMemoryInstrumentRegistry:
    """Small deterministic registry suitable for tests and local simulation."""

    def __init__(self, instruments: tuple[Instrument, ...] = ()) -> None:
        self._instruments = {instrument.instrument_id: instrument for instrument in instruments}

    def resolve(self, instrument_id: InstrumentId) -> Instrument | None:
        return self._instruments.get(instrument_id)

    def add(self, instrument: Instrument) -> None:
        self._instruments[instrument.instrument_id] = instrument


__all__ = ["InMemoryInstrumentRegistry", "InstrumentRegistry"]
