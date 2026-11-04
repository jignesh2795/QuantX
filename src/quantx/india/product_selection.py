"""Deprecated compatibility shim for `quantx.markets.india.product_selection`."""

from __future__ import annotations

from quantx.markets.india import product_selection as _canonical
from quantx.markets.india.product_selection import *  # noqa: F403

__all__ = list(getattr(_canonical, "__all__", []))
