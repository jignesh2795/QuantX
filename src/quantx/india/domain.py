"""Deprecated compatibility shim for `quantx.markets.india.domain`."""

from __future__ import annotations

from quantx.markets.india import domain as _canonical
from quantx.markets.india.domain import *  # noqa: F403

__all__ = list(getattr(_canonical, "__all__", []))
