"""Deterministic symbol normalization for Digital Assets spot."""

from __future__ import annotations

from quantx.domain.value_objects import InstrumentId

from .rules import rule_for_symbol


def normalize_symbol(value: str) -> str:
    """Return a canonical pair symbol or raise for ambiguous/unknown input."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("symbol must be a non-empty string")
    candidate = value.strip().upper().replace("-", "/").replace("_", "")
    # Accept canonical "BTC/USDT" or venue "BTCUSDT".
    if "/" in candidate:
        parts = candidate.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError("symbol must be a base/quote pair")
        candidate = f"{parts[0]}/{parts[1]}"
    else:
        # Attempt to split using known quote assets.
        for quote in ("USDT", "USD", "BTC", "ETH"):
            if candidate.endswith(quote) and len(candidate) > len(quote):
                base = candidate[: -len(quote)]
                candidate = f"{base}/{quote}"
                break
    rule = rule_for_symbol(candidate)
    if rule is None:
        raise ValueError(f"unknown or ambiguous digital-asset symbol: {value!r}")
    return rule.canonical_symbol


def resolve_instrument_id(value: str) -> InstrumentId:
    rule = rule_for_symbol(normalize_symbol(value))
    if rule is None:
        raise ValueError(f"unknown digital-asset symbol: {value!r}")
    return rule.instrument_id


__all__ = ["normalize_symbol", "resolve_instrument_id"]
