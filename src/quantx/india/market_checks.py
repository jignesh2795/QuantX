"""Deprecated compatibility shim for `quantx.markets.india.market_checks`."""

from __future__ import annotations

from quantx.markets.india import market_checks as _canonical
from quantx.markets.india.market_checks import *  # noqa: F403

__all__ = list(getattr(_canonical, "__all__", []))
