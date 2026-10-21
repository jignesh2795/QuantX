"""Adversarial coverage for contract identity through the execution boundary (QX-05).

The selected contract/rule identity is execution semantics: it must survive the
approved request, the canonical fingerprint, durable recovery, continuations,
and the trusted verifier unchanged. A forged or stale resolution is never
repaired; the trusted point-in-time resolver re-derives it and fails closed.
"""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.deployment import (
    ExecutionContext,
    ExecutionMode,
    PortfolioId,
    StrategyDeploymentId,
)
from quantx.domain.enums import (
    AssetClass,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionEffect,
    TimeInForce,
)
from quantx.domain.execution_request import (
    ApprovedExecutionRequest,
    PendingExecutionRecoveryRequest,
    build_order_from_intent,
)
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
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import PolicyDecision, PolicyResult
from quantx.domain.policy_verification import MarketPackPolicyVerifier, ProofVerificationError
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.domain.value_objects import InstrumentId
from quantx.execution.idempotency import PendingExecutionContext
from quantx.execution.idempotency.fingerprint import fingerprint_payload, request_fingerprint
from quantx.execution.receipts.lifecycle import ExecutionLifecycle
from quantx.research.market_rules import (
    PointInTimeContractCatalog,
    PointInTimeInstrumentRegistry,
    PointInTimeInstrumentResolver,
    VersionedContractMetadata,
    VersionedInstrumentRule,
)
from tests.unit._execution_request_proofs import (
    TEST_POSITION_EFFECT_POLICY,
    TEST_PRODUCT_SELECTION,
    approved_request,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
T1 = datetime(2026, 2, 1, tzinfo=UTC)
NOW = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)
EXPIRY = datetime(2026, 12, 31, 15, 30, tzinfo=UTC)
OPTION = InstrumentId("NSE", "NIFTY26DEC25000CE")
EQUITY = InstrumentId("NSE", "TCS")
UNDERLYING = InstrumentId("NSE", "NIFTY")
MARKET = MarketContext(MarketRegion.INDIA, MarketFamily.DERIVATIVES, "NSE", "IN")
EQUITY_MARKET = MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN")


def _option_instrument() -> Instrument:
    return Instrument(
        instrument_id=OPTION,
        symbol=OPTION.symbol,
        asset_class=AssetClass.OPTION,
        market=MARKET,
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("25"),
    )


def _equity_instrument() -> Instrument:
    return Instrument(
        instrument_id=EQUITY,
        symbol=EQUITY.symbol,
        asset_class=AssetClass.EQUITY,
        market=EQUITY_MARKET,
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )


def _option_contract(*, strike: str = "25000") -> Contract:
    return Contract(
        instrument_id=OPTION,
        asset_class=AssetClass.OPTION,
        underlying=UNDERLYING,
        expiry=EXPIRY,
        strike=Decimal(strike),
        option_type=OptionType.CALL,
    )


def _resolution(
    *,
    instrument: Instrument | None = None,
    contract: Contract | None = None,
    resolved_at: datetime = NOW,
    metadata_version: str = "contract-v1",
    rule_version: str = "rule-v1",
) -> InstrumentResolution:
    return InstrumentResolution(
        instrument=instrument or _option_instrument(),
        contract=_option_contract() if contract is None else contract,
        instrument_rule_version=rule_version,
        instrument_rule_effective_from=T0,
        resolved_at=resolved_at,
        contract_metadata_version=metadata_version,
        contract_source="nse-bhavcopy",
        contract_effective_from=T0,
    )


def _equity_resolution() -> InstrumentResolution:
    return InstrumentResolution(
        instrument=_equity_instrument(),
        instrument_rule_version="rule-v1",
        instrument_rule_effective_from=T0,
        resolved_at=NOW,
    )


def _context(mode: ExecutionMode) -> ExecutionContext:
    return ExecutionContext(
        account_id=AccountId("acct-1"),
        portfolio_id=PortfolioId("portfolio-1"),
        deployment_id=StrategyDeploymentId("deploy-1"),
        market=MARKET,
        broker_connection_id=BrokerConnectionId("conn-1") if mode is ExecutionMode.LIVE else None,
        execution_mode=mode,
        market_pack_id="test-pack",
        rule_version="test-v1",
    )


def _request(
    *,
    instrument: Instrument | None = None,
    resolution: InstrumentResolution | None = None,
    mode: ExecutionMode = ExecutionMode.PAPER,
) -> ApprovedExecutionRequest:
    instrument = instrument or _option_instrument()
    context = _context(mode)
    intent = TradeIntent(
        instrument=instrument.instrument_id,
        side=OrderSide.BUY,
        quantity=Decimal("2"),
        order_type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
        required_capabilities=frozenset({"ORDER_SUBMISSION"}),
        position_effect=PositionEffect.OPEN,
        execution_context=context,
    )
    return approved_request(
        order=build_order_from_intent(intent),
        execution_context=context,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=(
            PolicyResult(PolicyDecision.APPROVE, "approved") if mode is ExecutionMode.LIVE else None
        ),
        position_effect=PositionEffect.OPEN,
        instrument_resolution=resolution,
    )


def _rule(
    instrument_id: InstrumentId, start: datetime, end: datetime | None
) -> VersionedInstrumentRule:
    return VersionedInstrumentRule(
        instrument_id=str(instrument_id),
        effective_from=start,
        effective_to=end,
        tick_size=Decimal("0.05"),
        lot_size=Decimal("25"),
        multiplier=Decimal("1"),
        currency="INR",
        rule_version="rule-v1",
    )


def _record(
    contract: Contract,
    start: datetime,
    end: datetime | None,
    *,
    version: str = "contract-v1",
) -> VersionedContractMetadata:
    return VersionedContractMetadata(
        contract=contract,
        effective_from=start,
        effective_to=end,
        metadata_version=version,
        source="nse-bhavcopy",
    )


def _resolver(
    *records: VersionedContractMetadata,
    instrument: Instrument | None = None,
) -> PointInTimeInstrumentResolver:
    instrument = instrument or _option_instrument()
    return PointInTimeInstrumentResolver(
        instruments=InMemoryInstrumentRegistry((instrument,)),
        rules=PointInTimeInstrumentRegistry((_rule(instrument.instrument_id, T0, None),)),
        contracts=PointInTimeContractCatalog(records),
    )


def _verifier(resolver: PointInTimeInstrumentResolver | None) -> MarketPackPolicyVerifier:
    return MarketPackPolicyVerifier(
        product_selection_policies=(TEST_PRODUCT_SELECTION,),
        position_effect_policies=(TEST_POSITION_EFFECT_POLICY,),
        instrument_resolver=resolver,
    )


def test_approved_request_rejects_a_resolution_for_another_instrument() -> None:
    with pytest.raises(ValueError, match="does not describe the executed instrument"):
        _request(instrument=_option_instrument(), resolution=_equity_resolution())


def test_recovery_request_rejects_a_resolution_for_another_instrument() -> None:
    context = _context(ExecutionMode.PAPER)
    with pytest.raises(ValueError, match="does not describe the executed instrument"):
        PendingExecutionRecoveryRequest(
            order=build_order_from_intent(
                TradeIntent(
                    instrument=OPTION,
                    side=OrderSide.BUY,
                    quantity=Decimal("2"),
                    order_type=OrderType.MARKET,
                    time_in_force=TimeInForce.DAY,
                    position_effect=PositionEffect.OPEN,
                    execution_context=context,
                )
            ),
            execution_context=context,
            position_effect=PositionEffect.OPEN,
            instrument_resolution=_equity_resolution(),
        )


def test_fingerprint_payload_carries_the_selected_identity() -> None:
    resolution = _resolution()

    payload = fingerprint_payload(_request(resolution=resolution))

    assert payload["instrument_resolution"] == resolution.identity_payload()


def test_requests_without_a_resolution_keep_the_pre_qx_05_payload() -> None:
    payload = fingerprint_payload(_request())

    assert "instrument_resolution" not in payload


def test_fingerprint_changes_with_the_selected_contract() -> None:
    base = request_fingerprint(_request(resolution=_resolution()))

    other_strike = request_fingerprint(
        _request(resolution=_resolution(contract=_option_contract(strike="26000")))
    )
    other_version = request_fingerprint(
        _request(resolution=_resolution(metadata_version="contract-v2"))
    )
    other_rule = request_fingerprint(_request(resolution=_resolution(rule_version="rule-v2")))

    assert len({base, other_strike, other_version, other_rule}) == 4


def test_fingerprint_ignores_the_resolution_instant_inside_the_same_window() -> None:
    first = request_fingerprint(_request(resolution=_resolution(resolved_at=NOW)))
    later = request_fingerprint(
        _request(resolution=_resolution(resolved_at=datetime(2026, 1, 6, 10, 0, tzinfo=UTC)))
    )

    assert first == later


def test_pending_context_round_trip_preserves_contract_identity() -> None:
    resolution = _resolution()
    request = _request(resolution=resolution, mode=ExecutionMode.LIVE)
    context = PendingExecutionContext.from_request(request, request_fingerprint(request))

    restored = PendingExecutionContext.from_json(context.to_json())

    assert restored.instrument_resolution == resolution
    assert restored.instrument_resolution is not None
    assert restored.instrument_resolution.contract == resolution.contract
    assert restored.instrument_resolution.instrument_rule_version == "rule-v1"
    assert restored.instrument_resolution.contract_metadata_version == "contract-v1"
    assert restored.instrument_resolution.contract_source == "nse-bhavcopy"
    assert restored.to_json() == context.to_json()


def test_pending_context_recovery_request_preserves_contract_identity() -> None:
    resolution = _resolution()
    request = _request(resolution=resolution, mode=ExecutionMode.LIVE)
    context = PendingExecutionContext.from_request(request, request_fingerprint(request))

    recovery = context.to_recovery_request()

    assert recovery.instrument_resolution == resolution


def test_continuation_preserves_contract_identity() -> None:
    resolution = _resolution()
    request = _request(resolution=resolution, mode=ExecutionMode.LIVE)
    lifecycle = ExecutionLifecycle(
        client_order_id=request.order.client_order_id,
        order_quantity=Decimal("2"),
        filled_quantity=Decimal("1"),
        status=OrderStatus.PARTIALLY_FILLED,
    )

    child = lifecycle.continuation_request(
        request,
        risk_result=RiskResult(RiskDecision.APPROVE, "approved"),
        policy_result=PolicyResult(PolicyDecision.APPROVE, "approved"),
    )

    assert child.instrument_resolution == resolution
    assert child.order.quantity == Decimal("1")
    assert child.order.client_order_id != request.order.client_order_id


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("contract", "strike"), "26000"),
        (("contract", "option_type"), "PUT"),
        (("contract_metadata_version",), "contract-v2"),
        (("instrument", "tick_size"), "0.10"),
    ],
)
def test_pending_context_rejects_tampered_contract_identity(
    path: tuple[str, ...], value: str
) -> None:
    request = _request(resolution=_resolution(), mode=ExecutionMode.LIVE)
    context = PendingExecutionContext.from_request(request, request_fingerprint(request))
    payload = json.loads(context.to_json())
    target = payload["instrument_resolution"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValueError, match="fingerprint does not match"):
        PendingExecutionContext.from_json(json.dumps(payload))


def test_pending_context_rejects_a_dropped_resolution() -> None:
    request = _request(resolution=_resolution(), mode=ExecutionMode.LIVE)
    context = PendingExecutionContext.from_request(request, request_fingerprint(request))
    payload = json.loads(context.to_json())
    payload.pop("instrument_resolution")

    with pytest.raises(ValueError, match="invalid pending execution context"):
        PendingExecutionContext.from_json(json.dumps(payload))


def test_pre_qx_05_pending_row_without_the_key_still_decodes() -> None:
    request = _request(mode=ExecutionMode.LIVE)
    context = PendingExecutionContext.from_request(request, request_fingerprint(request))
    payload = json.loads(context.to_json())
    payload["version"] = 1
    payload.pop("instrument_resolution")

    restored = PendingExecutionContext.from_json(json.dumps(payload))

    assert restored.instrument_resolution is None


def test_version_1_pending_row_cannot_claim_a_resolution() -> None:
    request = _request(resolution=_resolution(), mode=ExecutionMode.LIVE)
    context = PendingExecutionContext.from_request(request, request_fingerprint(request))
    payload = json.loads(context.to_json())
    payload["version"] = 1

    with pytest.raises(ValueError, match="invalid pending execution context"):
        PendingExecutionContext.from_json(json.dumps(payload))


@pytest.mark.parametrize("version", [0, 3, "2", True])
def test_pending_context_rejects_an_unsupported_schema_version(version: object) -> None:
    request = _request(mode=ExecutionMode.LIVE)
    context = PendingExecutionContext.from_request(request, request_fingerprint(request))
    payload = json.loads(context.to_json())
    payload["version"] = version

    with pytest.raises(ValueError, match="invalid pending execution context"):
        PendingExecutionContext.from_json(json.dumps(payload))


def test_fingerprint_is_stable_across_equivalent_resolution_spelling() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    resolution = _resolution()
    respelled = replace(
        resolution,
        instrument=replace(resolution.instrument, tick_size=Decimal("0.0500")),
        contract=replace(
            _option_contract(),
            strike=Decimal("25000.000"),
            expiry=datetime(2026, 12, 31, 21, 0, tzinfo=ist),
        ),
        resolved_at=datetime(2026, 1, 5, 15, 30, tzinfo=ist),
        instrument_rule_effective_from=datetime(2026, 1, 1, 5, 30, tzinfo=ist),
        contract_effective_from=datetime(2026, 1, 1, 5, 30, tzinfo=ist),
    )
    request = _request(resolution=resolution, mode=ExecutionMode.LIVE)

    assert respelled == resolution
    assert respelled.identity_payload() == resolution.identity_payload()
    assert request_fingerprint(replace(request, instrument_resolution=respelled)) == (
        request_fingerprint(request)
    )


def test_verifier_accepts_an_equivalent_resolution_spelling() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    resolver = _resolver(_record(_option_contract(), T0, None))
    resolution = resolver.resolve_at(OPTION, NOW)
    assert resolution.contract is not None
    respelled = replace(
        resolution,
        contract=replace(
            resolution.contract,
            strike=Decimal("25000.000"),
            expiry=datetime(2026, 12, 31, 21, 0, tzinfo=ist),
        ),
    )

    _verifier(resolver).verify_request(_request(resolution=respelled))


def test_verifier_accepts_the_trusted_point_in_time_resolution() -> None:
    resolver = _resolver(_record(_option_contract(), T0, None))
    resolution = resolver.resolve_at(OPTION, NOW)

    _verifier(resolver).verify_request(_request(resolution=resolution))


def test_verifier_rejects_a_stale_metadata_claim_for_a_historical_request() -> None:
    resolver = _resolver(
        _record(_option_contract(strike="25000"), T0, T1, version="contract-v1"),
        _record(_option_contract(strike="26000"), T1, None, version="contract-v2"),
    )
    historical = resolver.resolve_at(OPTION, NOW)
    forged = replace(
        historical,
        contract=_option_contract(strike="26000"),
        contract_metadata_version="contract-v2",
    )

    with pytest.raises(ProofVerificationError, match="trusted point-in-time resolution"):
        _verifier(resolver).verify_request(_request(resolution=forged))


def test_verifier_rejects_a_resolution_that_contradicts_the_canonical_instrument() -> None:
    resolver = _resolver(_record(_option_contract(), T0, None))
    resolution = resolver.resolve_at(OPTION, NOW)
    forged = replace(
        resolution,
        instrument=replace(resolution.instrument, tick_size=Decimal("0.10")),
    )

    with pytest.raises(ProofVerificationError, match="contradicts the canonical instrument"):
        _verifier(resolver).verify_request(_request(resolution=forged))


def test_verifier_rejects_a_missing_resolution_when_a_resolver_is_composed() -> None:
    with pytest.raises(ProofVerificationError, match="requires an instrument resolution"):
        _verifier(_resolver(_record(_option_contract(), T0, None))).verify_request(_request())


def test_verifier_rejects_a_resolution_without_a_trusted_resolver() -> None:
    with pytest.raises(ProofVerificationError, match="trusted point-in-time resolver"):
        _verifier(None).verify_request(_request(resolution=_resolution()))


def test_verifier_rejects_a_resolution_naming_another_instrument() -> None:
    verifier = _verifier(_resolver(_record(_option_contract(), T0, None)))

    with pytest.raises(ProofVerificationError, match="does not describe the executed instrument"):
        verifier.verify_instrument_resolution(_resolution(), instrument_id=str(EQUITY))


def test_non_derivative_request_with_a_resolution_verifies_without_a_contract() -> None:
    resolver = PointInTimeInstrumentResolver(
        instruments=InMemoryInstrumentRegistry((_equity_instrument(),)),
        rules=PointInTimeInstrumentRegistry((_rule(EQUITY, T0, None),)),
        contracts=PointInTimeContractCatalog(),
    )
    resolution = resolver.resolve_at(EQUITY, NOW)
    request = _request(instrument=_equity_instrument(), resolution=resolution)

    _verifier(resolver).verify_request(request)

    assert request.instrument_resolution is not None
    assert request.instrument_resolution.contract is None
