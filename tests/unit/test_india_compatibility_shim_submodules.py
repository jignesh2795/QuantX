from __future__ import annotations

import importlib
import sys
import warnings

from quantx.ports import market_checks as core

SUBMODULES = (
    "domain",
    "execution_rules",
    "instrument_catalog",
    "market_checks",
    "market_pack",
    "product_selection",
    "rule_data",
    "session_calendar",
)


def _import_legacy(name: str):
    full = f"quantx.india.{name}"
    sys.modules.pop(full, None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return importlib.import_module(full)


def _import_canonical(name: str):
    return importlib.import_module(f"quantx.markets.india.{name}")


def test_legacy_submodules_reexport_canonical_identities() -> None:
    for name in SUBMODULES:
        legacy = _import_legacy(name)
        canonical = _import_canonical(name)

        assert legacy is not canonical
        exported = getattr(canonical, "__all__", None)
        if exported is None:
            exported = [name for name in canonical.__dict__ if not name.startswith("_")]
        for name in exported:
            assert getattr(legacy, name) is getattr(canonical, name)


def test_importing_legacy_submodules_does_not_register_trusted_checks() -> None:
    core._PINNED_TRUSTED_CHECKS.clear()
    for name in SUBMODULES:
        _import_legacy(name)

    assert core._PINNED_TRUSTED_CHECKS == {}


def test_legacy_top_level_shim_reexports_canonical_submodules() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import quantx.india as shim

    from quantx.markets import india as canonical

    assert shim is not canonical
    assert shim.__all__ == canonical.__all__
    for exported in canonical.__all__:
        assert getattr(shim, exported) is getattr(canonical, exported)
