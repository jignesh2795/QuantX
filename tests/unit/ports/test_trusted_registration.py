"""Trusted registration capability-boundary and identity tests."""

from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

from quantx.application.trusted_check_bootstrap import ensure_india_trusted_checks_registered
from quantx.domain._trusted_check_authority import _CORE_REGISTRAR, _is_core_trusted_check_registrar
from quantx.domain.instruments import MarketRegion
from quantx.markets.india.market_checks import IndiaCompatCheck, IndiaSessionCheck
from quantx.ports import market_checks as core
from quantx.ports.market_checks import MarketCheckStage, is_trusted_check


@pytest.fixture(autouse=True)
def _reset_pinned_trusted_checks():
    core._PINNED_TRUSTED_CHECKS.clear()
    ensure_india_trusted_checks_registered()
    yield
    core._PINNED_TRUSTED_CHECKS.clear()


def _spoofed_class(module: str, qualname: str) -> type:
    return type(
        qualname.rsplit(".", 1)[-1],
        (),
        {"__module__": module, "__qualname__": qualname},
    )


def _is_session_trusted(check: object) -> bool:
    return is_trusted_check(
        "india.session-calendar",
        check,
        region=MarketRegion.INDIA,
        stage=MarketCheckStage.PRE_DISPATCH,
    )


def test_registration_without_capability_fails_closed() -> None:
    with pytest.raises(PermissionError):
        core._register_trusted_check("india.session-calendar", IndiaSessionCheck, object())


def test_registration_with_incorrect_capability_fails_closed() -> None:
    with pytest.raises(PermissionError):
        core._register_trusted_check(
            "india.session-calendar", IndiaSessionCheck, SimpleNamespace()
        )


def test_authorized_core_bootstrap_pins_both_canonical_classes() -> None:
    core._PINNED_TRUSTED_CHECKS.clear()
    ensure_india_trusted_checks_registered()

    assert core._PINNED_TRUSTED_CHECKS["india.session-calendar"] is IndiaSessionCheck
    assert core._PINNED_TRUSTED_CHECKS["india.compatibility-rules"] is IndiaCompatCheck
    assert _is_session_trusted(IndiaSessionCheck(lambda _request: None))


def test_bootstrap_is_idempotent() -> None:
    ensure_india_trusted_checks_registered()
    ensure_india_trusted_checks_registered()

    assert core._PINNED_TRUSTED_CHECKS["india.session-calendar"] is IndiaSessionCheck
    assert core._PINNED_TRUSTED_CHECKS["india.compatibility-rules"] is IndiaCompatCheck


@pytest.mark.parametrize(
    ("module", "qualname"),
    [
        ("quantx.shim.market_checks", "IndiaSessionCheck"),
        ("quantx.markets.india.market_checks", "SpoofedSessionCheck"),
        ("quantx.markets.india.market_checks", "IndiaSessionCheck"),
    ],
)
def test_spoofed_metadata_never_authorizes_replacement_class(
    module: str, qualname: str
) -> None:
    evil = _spoofed_class(module, qualname)

    # Deliberately use the real internal capability: the rejection must come
    # from the exact-class approval map, not merely from a missing handle.
    with pytest.raises(ValueError):
        core._register_trusted_check("india.session-calendar", evil, _CORE_REGISTRAR)

    assert not _is_session_trusted(evil)
    assert _is_session_trusted(IndiaSessionCheck(lambda _request: None))


def test_spoofed_class_cannot_preempt_canonical_registration() -> None:
    evil = _spoofed_class(
        "quantx.markets.india.market_checks",
        "IndiaSessionCheck",
    )

    with pytest.raises(ValueError):
        core._register_trusted_check("india.session-calendar", evil, _CORE_REGISTRAR)

    ensure_india_trusted_checks_registered()
    assert core._PINNED_TRUSTED_CHECKS["india.session-calendar"] is IndiaSessionCheck


def test_conflicting_pinned_registration_fails_closed() -> None:
    evil = _spoofed_class(
        "quantx.markets.india.market_checks",
        "IndiaSessionCheck",
    )
    core._PINNED_TRUSTED_CHECKS["india.session-calendar"] = evil

    with pytest.raises(ValueError, match="conflicting trusted implementation"):
        core._register_trusted_check(
            "india.session-calendar", IndiaSessionCheck, _CORE_REGISTRAR
        )


def test_unavailable_implementation_fails_closed() -> None:
    with pytest.raises(ValueError, match="implementation must be a class"):
        core._register_trusted_check("india.session-calendar", None, _CORE_REGISTRAR)


def test_rebinding_canonical_module_attribute_does_not_replace_captured_class() -> None:
    module = importlib.import_module("quantx.markets.india.market_checks")
    original = module.IndiaSessionCheck
    evil = _spoofed_class(
        "quantx.markets.india.market_checks",
        "IndiaSessionCheck",
    )
    try:
        module.IndiaSessionCheck = evil
        core._PINNED_TRUSTED_CHECKS.clear()
        ensure_india_trusted_checks_registered()
    finally:
        module.IndiaSessionCheck = original

    assert core._PINNED_TRUSTED_CHECKS["india.session-calendar"] is original
    assert _is_session_trusted(original(lambda _request: None))
    assert not _is_session_trusted(evil())


def test_legacy_shim_import_does_not_register_trusted_checks() -> None:
    core._PINNED_TRUSTED_CHECKS.clear()
    sys.modules.pop("quantx.india", None)
    sys.modules.pop("quantx.india.market_checks", None)

    import quantx.india  # noqa: F401

    assert core._PINNED_TRUSTED_CHECKS == {}
    assert not _is_session_trusted(IndiaSessionCheck(lambda _request: None))


def test_registrar_is_not_exposed_by_ports_or_market_bootstrap_api() -> None:
    assert "_REGISTRAR" not in vars(core)
    assert "_CORE_REGISTRAR" not in vars(core)
    assert not hasattr(core, "register_trusted_check")
    assert not hasattr(core, "register_trusted_check_bootstrap")
    assert not hasattr(core, "bootstrap_trusted_checks")
    assert not hasattr(core, "_TRUSTED_CHECK_BOOTSTRAPPERS")
    assert _is_core_trusted_check_registrar(_CORE_REGISTRAR)
    assert not _is_core_trusted_check_registrar(object())
