"""Deprecated compatibility shim for `quantx.markets.india.instrument_catalog`."""

from __future__ import annotations

from quantx.markets.india import instrument_catalog as _canonical
from quantx.markets.india.instrument_catalog import *  # noqa: F403

__all__ = list(getattr(_canonical, "__all__", []))
