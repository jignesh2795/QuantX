"""Deprecated compatibility shim for `quantx.markets.india.rule_data`."""

from __future__ import annotations

from quantx.markets.india import rule_data as _canonical
from quantx.markets.india.rule_data import *  # noqa: F403

__all__ = list(getattr(_canonical, "__all__", []))
