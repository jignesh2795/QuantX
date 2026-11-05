from __future__ import annotations

import sys
import warnings

from quantx.domain.instruments import MarketRegion
from quantx.markets.india import (
    IndiaSessionCheck,
)
from quantx.ports import market_checks as core
from quantx.ports.market_checks import MarketCheckStage


def _import_legacy_shim():
    sys.modules.pop("quantx.india", None)
    sys.modules.pop("quantx.india.market_checks", None)
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        import quantx.india  # noqa: PLC0415

        assert any(issubclass(w.category, DeprecationWarning) for w in recorded)
    return quantx.india


def test_legacy_shim_reexports_canonical_classes() -> None:
    shim = _import_legacy_shim()

    from quantx.markets import india as canonical

    assert shim.IndiaSessionCheck is canonical.IndiaSessionCheck
    assert shim.IndiaCompatCheck is canonical.IndiaCompatCheck
    assert shim.india_market_policy is canonical.india_market_policy
    assert shim.__all__ == canonical.__all__


def test_legacy_shim_does_not_register_trusted_checks() -> None:
    core._PINNED_TRUSTED_CHECKS.clear()
    _import_legacy_shim()

    assert core._PINNED_TRUSTED_CHECKS == {}
    assert not core.is_trusted_check(
        "india.session-calendar",
        IndiaSessionCheck(lambda _request: None),
        region=MarketRegion.INDIA,
        stage=MarketCheckStage.PRE_DISPATCH,
    )


def test_legacy_shim_domain_reexports_canonical_identity() -> None:
    shim = _import_legacy_shim()
    from quantx.markets.india import domain as canonical_domain

    assert shim.IndianExchange is canonical_domain.IndianExchange
