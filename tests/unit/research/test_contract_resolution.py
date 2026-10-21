"""Adversarial coverage for point-in-time contract resolution (QX-05).

The resolver is the only seam that composes the canonical instrument, the
applicable trading rule, and the applicable contract metadata at one instant.
These tests pin the fail-closed behaviour from ADR-012: exactly one record per
dimension, no fallback to current metadata for a historical request, and a
non-derivative resolution that never fabricates a contract.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instrument_registry import (
    InMemoryInstrumentRegistry,
    InstrumentResolution,
)
from quantx.domain.instruments import (
    Contract,
    Instrument,
    MarketContext,
    MarketFamily,
    MarketRegion,
    OptionType,
)
from quantx.domain.value_objects import InstrumentId
from quantx.research.market_rules import (
    InstrumentResolutionError,
    PointInTimeContractCatalog,
    PointInTimeInstrumentRegistry,
    PointInTimeInstrumentResolver,
    TradabilityStatus,
    VersionedContractMetadata,
    VersionedInstrumentRule,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 2, 1, tzinfo=UTC)
T2 = datetime(2026, 3, 1, tzinfo=UTC)
EXPIRY = datetime(2026, 12, 31, 15, 30, tzinfo=UTC)

OPTION = InstrumentId("NSE", "NIFTY26DEC25000CE")
FUTURE = InstrumentId("NSE", "NIFTY26DECFUT")
EQUITY = InstrumentId("NSE", "TCS")
UNDERLYING = InstrumentId("NSE", "NIFTY")


def _instrument(instrument_id: InstrumentId, asset_class: AssetClass) -> Instrument:
    derivative = asset_class in {AssetClass.OPTION, AssetClass.FUTURE}
    return Instrument(
        instrument_id=instrument_id,
        symbol=instrument_id.symbol,
        asset_class=asset_class,
        market=MarketContext(
            MarketRegion.INDIA,
            MarketFamily.DERIVATIVES if derivative else MarketFamily.EQUITY,
            instrument_id.venue,
            "IN",
        ),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("25") if derivative else Decimal("1"),
        multiplier=Decimal("1"),
    )


def _rule(
    instrument_id: InstrumentId,
    start: datetime,
    end: datetime | None,
    *,
    version: str = "rule-v1",
    status: TradabilityStatus = TradabilityStatus.TRADABLE,
) -> VersionedInstrumentRule:
    return VersionedInstrumentRule(
        instrument_id=str(instrument_id),
        effective_from=start,
        effective_to=end,
        tick_size=Decimal("0.05"),
        lot_size=Decimal("25"),
        multiplier=Decimal("1"),
        currency="INR",
        status=status,
        rule_version=version,
    )


def _option_contract(instrument_id: InstrumentId = OPTION, *, strike: str = "25000") -> Contract:
    return Contract(
        instrument_id=instrument_id,
        asset_class=AssetClass.OPTION,
        underlying=UNDERLYING,
        expiry=EXPIRY,
        strike=Decimal(strike),
        option_type=OptionType.CALL,
    )


def _record(
    contract: Contract,
    start: datetime,
    end: datetime | None,
    *,
    version: str = "contract-v1",
    source: str = "nse-bhavcopy",
) -> VersionedContractMetadata:
    return VersionedContractMetadata(
        contract=contract,
        effective_from=start,
        effective_to=end,
        metadata_version=version,
        source=source,
    )


def _resolver(
    instruments: tuple[Instrument, ...],
    rules: tuple[VersionedInstrumentRule, ...],
    records: tuple[VersionedContractMetadata, ...] = (),
) -> PointInTimeInstrumentResolver:
    return PointInTimeInstrumentResolver(
        instruments=InMemoryInstrumentRegistry(instruments),
        rules=PointInTimeInstrumentRegistry(rules),
        contracts=PointInTimeContractCatalog(records),
    )


def _option_resolver(
    *records: VersionedContractMetadata,
    rules: tuple[VersionedInstrumentRule, ...] | None = None,
) -> PointInTimeInstrumentResolver:
    return _resolver(
        (_instrument(OPTION, AssetClass.OPTION),),
        rules if rules is not None else (_rule(OPTION, T0, None),),
        records,
    )


def test_option_resolution_composes_instrument_rule_and_contract() -> None:
    resolver = _option_resolver(_record(_option_contract(), T0, None))

    resolution = resolver.resolve_at(OPTION, T2)

    assert resolution.instrument == _instrument(OPTION, AssetClass.OPTION)
    assert resolution.contract == _option_contract()
    assert resolution.instrument_rule_version == "rule-v1"
    assert resolution.instrument_rule_effective_from == T0
    assert resolution.contract_metadata_version == "contract-v1"
    assert resolution.contract_source == "nse-bhavcopy"
    assert resolution.contract_effective_from == T0
    assert resolution.resolved_at == T2


def test_historical_request_selects_the_historical_contract_version() -> None:
    resolver = _option_resolver(
        _record(_option_contract(strike="25000"), T0, T1, version="contract-v1"),
        _record(_option_contract(strike="26000"), T1, None, version="contract-v2"),
    )

    historical = resolver.resolve_at(OPTION, T0)
    current = resolver.resolve_at(OPTION, T2)

    assert historical.contract is not None
    assert historical.contract.strike == Decimal("25000")
    assert historical.contract_metadata_version == "contract-v1"
    assert current.contract is not None
    assert current.contract.strike == Decimal("26000")
    assert current.contract_metadata_version == "contract-v2"


def test_historical_resolution_never_falls_back_to_current_metadata() -> None:
    resolver = _option_resolver(
        _record(_option_contract(strike="25000"), T0, T1, version="contract-v1"),
    )

    # The only record has expired; a later request must fail closed instead of
    # adopting any current metadata.
    with pytest.raises(InstrumentResolutionError):
        resolver.resolve_at(OPTION, T2)


def test_request_before_the_first_contract_window_fails_closed() -> None:
    resolver = _option_resolver(_record(_option_contract(), T1, None))

    with pytest.raises(InstrumentResolutionError):
        resolver.resolve_at(OPTION, T0)


def test_resolution_snapshot_is_stable_after_new_metadata_is_registered() -> None:
    resolver = _option_resolver(_record(_option_contract(strike="25000"), T0, T1))
    historical = resolver.resolve_at(OPTION, T0)

    resolver.contracts.add(_record(_option_contract(strike="26000"), T1, None, version="v2"))

    assert historical.contract is not None
    assert historical.contract.strike == Decimal("25000")
    assert resolver.resolve_at(OPTION, T0).identity_payload() == historical.identity_payload()


def test_historical_rule_version_is_selected_independently_of_contract_version() -> None:
    resolver = _option_resolver(
        _record(_option_contract(), T0, None, version="contract-v1"),
        rules=(
            _rule(OPTION, T0, T1, version="rule-v1"),
            _rule(OPTION, T1, None, version="rule-v2"),
        ),
    )

    historical = resolver.resolve_at(OPTION, T0)
    current = resolver.resolve_at(OPTION, T2)

    assert historical.instrument_rule_version == "rule-v1"
    assert historical.contract_metadata_version == "contract-v1"
    assert current.instrument_rule_version == "rule-v2"
    assert current.contract_metadata_version == "contract-v1"


def test_overlapping_contract_windows_are_rejected() -> None:
    catalog = PointInTimeContractCatalog((_record(_option_contract(), T0, T2),))

    with pytest.raises(ValueError, match="overlapping contract metadata"):
        catalog.add(_record(_option_contract(), T1, None, version="v2"))


def test_conflicting_metadata_version_is_rejected() -> None:
    catalog = PointInTimeContractCatalog((_record(_option_contract(), T0, T1),))

    with pytest.raises(ValueError, match="duplicate contract metadata version"):
        catalog.add(_record(_option_contract(), T1, None, version="contract-v1"))


def test_catalog_records_are_oldest_first_and_scoped_to_one_identity() -> None:
    later = _record(_option_contract(strike="26000"), T1, None, version="v2")
    earlier = _record(_option_contract(), T0, T1, version="v1")
    catalog = PointInTimeContractCatalog((later, earlier))

    assert catalog.records_for(OPTION) == (earlier, later)
    assert catalog.records_for(FUTURE) == ()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("effective_from", datetime(2026, 1, 1), "effective_from must be timezone-aware"),
        (
            "effective_to",
            datetime(2025, 12, 1, tzinfo=UTC),
            "effective_to must be after effective_from",
        ),
        ("metadata_version", "  ", "metadata_version must not be empty"),
        ("source", "", "source must not be empty"),
    ],
)
def test_malformed_contract_record_is_rejected(field: str, value: object, message: str) -> None:
    values: dict[str, object] = {
        "contract": _option_contract(),
        "effective_from": T0,
        "effective_to": None,
        "metadata_version": "contract-v1",
        "source": "nse-bhavcopy",
    }
    values[field] = value

    with pytest.raises(ValueError, match=message):
        VersionedContractMetadata(**values)  # type: ignore[arg-type]


def test_catalog_rejects_a_non_record() -> None:
    catalog = PointInTimeContractCatalog()

    with pytest.raises(ValueError, match="VersionedContractMetadata"):
        catalog.add(_option_contract())  # type: ignore[arg-type]


def test_missing_instrument_metadata_fails_closed() -> None:
    resolver = _resolver((), (_rule(OPTION, T0, None),), (_record(_option_contract(), T0, None),))

    with pytest.raises(InstrumentResolutionError, match="instrument metadata unavailable"):
        resolver.resolve_at(OPTION, T0)


def test_missing_point_in_time_rule_fails_closed() -> None:
    resolver = _option_resolver(
        _record(_option_contract(), T0, None),
        rules=(_rule(OPTION, T0, T1),),
    )

    with pytest.raises(InstrumentResolutionError, match="no unique point-in-time rule"):
        resolver.resolve_at(OPTION, T2)


def test_missing_contract_metadata_for_a_derivative_fails_closed() -> None:
    resolver = _option_resolver()

    with pytest.raises(InstrumentResolutionError, match="no unique point-in-time contract"):
        resolver.resolve_at(OPTION, T0)


def test_contract_metadata_registered_for_a_non_derivative_fails_closed() -> None:
    resolver = _resolver(
        (_instrument(EQUITY, AssetClass.EQUITY),),
        (_rule(EQUITY, T0, None),),
        (_record(_option_contract(instrument_id=EQUITY), T0, None),),
    )

    with pytest.raises(InstrumentResolutionError, match="non-derivative instrument"):
        resolver.resolve_at(EQUITY, T0)


def test_contract_asset_class_contradiction_fails_closed() -> None:
    # A record for the future identity that claims to be an option.
    contradictory = Contract(
        instrument_id=FUTURE,
        asset_class=AssetClass.OPTION,
        underlying=UNDERLYING,
        expiry=EXPIRY,
        strike=Decimal("25000"),
        option_type=OptionType.CALL,
    )
    resolver = _resolver(
        (_instrument(FUTURE, AssetClass.FUTURE),),
        (_rule(FUTURE, T0, None),),
        (_record(contradictory, T0, None),),
    )

    with pytest.raises(InstrumentResolutionError, match="asset class contradicts"):
        resolver.resolve_at(FUTURE, T0)


def test_registry_returning_a_different_identity_fails_closed() -> None:
    class _AliasingRegistry(InMemoryInstrumentRegistry):
        def resolve(self, instrument_id: InstrumentId) -> Instrument | None:
            return _instrument(EQUITY, AssetClass.EQUITY)

    resolver = PointInTimeInstrumentResolver(
        instruments=_AliasingRegistry((_instrument(OPTION, AssetClass.OPTION),)),
        rules=PointInTimeInstrumentRegistry((_rule(OPTION, T0, None),)),
        contracts=PointInTimeContractCatalog((_record(_option_contract(), T0, None),)),
    )

    with pytest.raises(InstrumentResolutionError, match="different identity"):
        resolver.resolve_at(OPTION, T0)


def test_resolution_requires_a_canonical_identity_and_aware_timestamp() -> None:
    resolver = _option_resolver(_record(_option_contract(), T0, None))

    with pytest.raises(ValueError, match="canonical InstrumentId"):
        resolver.resolve_at("NSE:NIFTY26DEC25000CE", T0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="timezone-aware"):
        resolver.resolve_at(OPTION, datetime(2026, 3, 1))


def test_contract_applicability_does_not_assert_tradability() -> None:
    resolver = _option_resolver(
        _record(_option_contract(), T0, None),
        rules=(_rule(OPTION, T0, None, status=TradabilityStatus.SUSPENDED),),
    )

    resolution = resolver.resolve_at(OPTION, T2)

    # Selection is metadata applicability only; the rule still reports the
    # suspension and no tradability claim is manufactured here.
    assert resolution.instrument_rule_version == "rule-v1"
    assert resolution.contract is not None


def test_non_derivative_resolution_never_fabricates_a_contract() -> None:
    resolver = _resolver(
        (_instrument(EQUITY, AssetClass.EQUITY),),
        (_rule(EQUITY, T0, None),),
    )

    resolution = resolver.resolve_at(EQUITY, T2)

    assert resolution.contract is None
    assert resolution.contract_metadata_version is None
    assert resolution.contract_source is None
    assert resolution.contract_effective_from is None
    assert resolution.identity_payload()["contract"] is None


def test_derivative_resolution_payload_round_trips_losslessly() -> None:
    resolution = _option_resolver(_record(_option_contract(), T0, None)).resolve_at(OPTION, T2)

    restored = InstrumentResolution.from_payload(resolution.to_payload())

    assert restored == resolution
    assert restored.contract is not None
    assert restored.contract.option_type is OptionType.CALL


def test_non_derivative_resolution_payload_round_trips_losslessly() -> None:
    resolution = _resolver(
        (_instrument(EQUITY, AssetClass.EQUITY),),
        (_rule(EQUITY, T0, None),),
    ).resolve_at(EQUITY, T2)

    assert InstrumentResolution.from_payload(resolution.to_payload()) == resolution


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.pop("contract_source"),
        lambda payload: payload.update({"extra": "forged"}),
        lambda payload: payload.update({"resolved_at": "not-a-timestamp"}),
        lambda payload: payload.update({"contract_metadata_version": 5}),
    ],
)
def test_resolution_payload_rejects_missing_or_invalid_fields(mutate) -> None:
    payload = (
        _option_resolver(_record(_option_contract(), T0, None)).resolve_at(OPTION, T2).to_payload()
    )
    mutate(payload)

    with pytest.raises(ValueError):
        InstrumentResolution.from_payload(payload)


def test_identity_payload_excludes_the_resolution_instant() -> None:
    resolver = _option_resolver(_record(_option_contract(), T0, None))

    earlier = resolver.resolve_at(OPTION, T0)
    later = resolver.resolve_at(OPTION, T2)

    assert earlier.resolved_at != later.resolved_at
    assert earlier.identity_payload() == later.identity_payload()
    assert earlier.to_payload() != later.to_payload()


def test_identity_payload_changes_with_the_selected_contract() -> None:
    resolver = _option_resolver(
        _record(_option_contract(strike="25000"), T0, T1, version="v1"),
        _record(_option_contract(strike="26000"), T1, None, version="v2"),
    )

    historical = resolver.resolve_at(OPTION, T0)
    current = resolver.resolve_at(OPTION, T2)

    assert historical.identity_payload() != current.identity_payload()
    assert historical.identity_payload()["contract_metadata_version"] == "v1"
    assert current.identity_payload()["contract_metadata_version"] == "v2"
