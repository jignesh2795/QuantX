"""Trusted registration capability boundary tests."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from quantx.domain.instruments import MarketRegion
from quantx.markets.india.market_checks import IndiaCompatCheck, IndiaSessionCheck
from quantx.ports import market_checks as core
from quantx.ports.market_checks import MarketCheckStage, is_trusted_check


@pytest.fixture(autouse=True)
def _reset_pinned_trusted_checks():
    core._PINNED_TRUSTED_CHECKS.clear()
    yield
    core._PINNED_TRUSTED_CHECKS.clear()


def _handle():
    return core._REGISTRAR


def test_registration_without_handle_fails_closed() -> None:
    with pytest.raises(PermissionError):
        core.register_trusted_check("india.session-calendar", IndiaSessionCheck, object())


def test_registration_with_incorrect_handle_fails_closed() -> None:
    with pytest.raises(PermissionError):
        core.register_trusted_check("india.session-calendar", IndiaSessionCheck, SimpleNamespace())


def test_authorized_registration_pins_approved_class() -> None:
    core.register_trusted_check("india.session-calendar", IndiaSessionCheck, _handle())
    assert is_trusted_check(
        "india.session-calendar",
        IndiaSessionCheck(lambda _request: None),
        region=MarketRegion.INDIA,
        stage=MarketCheckStage.PRE_DISPATCH,
    )


def test_early_unauthorized_registration_does_not_pin() -> None:
    class Evil:
        __module__ = "quantx.markets.india.market_checks"
        __qualname__ = "IndiaSessionCheck"

    with pytest.raises(PermissionError):
        core.register_trusted_check("india.session-calendar", Evil, object())
    assert not is_trusted_check(
        "india.session-calendar",
        Evil(),
        region=MarketRegion.INDIA,
        stage=MarketCheckStage.PRE_DISPATCH,
    )


def test_spoofed_module_fails() -> None:
    class Evil:
        __module__ = "quantx.shim.market_checks"
        __qualname__ = "IndiaSessionCheck"

    with pytest.raises(ValueError):
        core.register_trusted_check("india.session-calendar", Evil, _handle())


def test_spoofed_qualname_fails() -> None:
    class Evil:
        __module__ = "quantx.markets.india.market_checks"
        __qualname__ = "EvilSessionCheck"

    with pytest.raises(ValueError):
        core.register_trusted_check("india.session-calendar", Evil, _handle())


def test_spoofed_module_and_qualname_still_requires_handle() -> None:
    class Evil:
        __module__ = "quantx.markets.india.market_checks"
        __qualname__ = "IndiaSessionCheck"

    with pytest.raises(PermissionError):
        core.register_trusted_check("india.session-calendar", Evil, object())


def test_conflicting_registration_after_pinning_fails() -> None:
    core.register_trusted_check("india.session-calendar", IndiaSessionCheck, _handle())

    class Other:
        __module__ = "quantx.markets.india.market_checks"
        __qualname__ = "IndiaSessionCheck"

    with pytest.raises(ValueError):
        core.register_trusted_check("india.session-calendar", Other, _handle())


def test_duplicate_registration_is_idempotent() -> None:
    core.register_trusted_check("india.session-calendar", IndiaSessionCheck, _handle())
    core.register_trusted_check("india.session-calendar", IndiaSessionCheck, _handle())
    assert is_trusted_check(
        "india.session-calendar",
        IndiaSessionCheck(lambda _request: None),
        region=MarketRegion.INDIA,
        stage=MarketCheckStage.PRE_DISPATCH,
    )


def test_unavailable_approved_implementation_fails() -> None:
    with pytest.raises(ValueError):
        core.register_trusted_check("india.session-calendar", None, _handle())


def test_rebinding_canonical_attribute_does_not_retroactively_trust() -> None:
    core.register_trusted_check("india.session-calendar", IndiaSessionCheck, _handle())

    class Evil:
        pass

    original = IndiaSessionCheck
    try:
        import quantx.markets.india.market_checks as module

        module.IndiaSessionCheck = Evil
        # Re-registration uses the rebound attribute and must fail the canonical
        # cross-check before any new identity is pinned.
        from quantx.markets.trusted_checks import ensure_india_trusted_checks_registered

        ensure_india_trusted_checks_registered()
    finally:
        module.IndiaSessionCheck = original

    assert not is_trusted_check(
        "india.session-calendar",
        Evil(),
        region=MarketRegion.INDIA,
        stage=MarketCheckStage.PRE_DISPATCH,
    )


def test_reused_handle_validates_by_identity() -> None:
    handle = _handle()
    assert handle is core._REGISTRAR
    core.register_trusted_check("india.session-calendar", IndiaSessionCheck, handle)
    core.register_trusted_check("india.compatibility-rules", IndiaCompatCheck, handle)


def test_legacy_shim_import_does_not_confer_trust() -> None:
    sys.modules.pop("quantx.india", None)
    sys.modules.pop("quantx.india.market_checks", None)
    import quantx.india  # noqa: F401

    assert not is_trusted_check(
        "india.session-calendar",
        IndiaSessionCheck(lambda _request: None),
        region=MarketRegion.INDIA,
        stage=MarketCheckStage.PRE_DISPATCH,
    )


def test_handle_is_not_publicly_constructible() -> None:
    assert not hasattr(core, "TrustedCheckRegistrar")
    assert "_REGISTRAR" not in dir(core) or core._REGISTRAR is core._REGISTRAR
