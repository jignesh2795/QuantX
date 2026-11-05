"""Deprecated compatibility shim for `quantx.markets.india.execution_rules`."""

from __future__ import annotations

from quantx.markets.india import execution_rules as _canonical
from quantx.markets.india.execution_rules import *  # noqa: F403

__all__ = list(getattr(_canonical, "__all__", []))
