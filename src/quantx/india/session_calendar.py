"""Deprecated compatibility shim for `quantx.markets.india.session_calendar`."""

from __future__ import annotations

from quantx.markets.india import session_calendar as _canonical
from quantx.markets.india.session_calendar import *  # noqa: F403

__all__ = list(getattr(_canonical, "__all__", []))
