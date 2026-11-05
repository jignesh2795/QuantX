"""Deprecated compatibility shim for ``quantx.markets.india``."""

from __future__ import annotations

import warnings

from quantx.markets.india import *  # noqa: F403
from quantx.markets.india import __all__ as _canonical_all

warnings.warn(
    "quantx.india is deprecated; use quantx.markets.india. "
    "This compatibility shim will be removed in a future release.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = list(_canonical_all)
