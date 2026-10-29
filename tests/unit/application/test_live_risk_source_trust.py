"""Regression tests for the LIVE risk-evidence source-trust boundary.

The bypass this file pins: a caller-created source implemented the evidence
protocol, claimed every required field, echoed the configured account,
connection, client id and transport, and returned internally consistent but
fabricated financial values. Identity binding and HMAC sealing proved only that
the authority had wrapped those values, so the fabricated evidence reached the
risk engine and the broker.

The correction: trust is an application-registered construction path over a
connection this process registered. No API accepts a source instance, source
metadata, or a ``trusted`` flag, so a source can neither self-authorize nor be
wrapped into authority by a caller.
"""

from __future__ import annotations

import inspect
from dataclasses import replace
from decimal import Decimal

import pytest

from quantx.application.execution import ExecutionDispatchStatus
from quantx.application.live_execution import (
    LiveExecutionCompositionError,
    LiveExecutionConfig,
    build_live_execution,
)
from quantx.application.live_risk import (
    LiveRiskEvidenceAuthority,
    LiveRiskEvidenceField,
)
from quantx.application.live_risk_sources import (
    LiveRiskEvidenceSourceBuilder,
    LiveRiskEvidenceSourceCatalog,
    LiveRiskEvidenceSourceGrant,
    TrustedLiveRiskEvidenceBinding,
)
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.clock import FixedClock
from quantx.domain.risk import PreTradeRiskEngine
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.trading_gate import TradingGateState
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteSubmissionQuarantineRepository,
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)
from tests.unit._execution_request_proofs import policy_verifier
from tests.unit.application._live_risk_trust import (
    BROKER_ID,
    catalog_for,
    catalog_with_builder,
    registered_connection,
    registry_with,
)
from tests.unit.application.test_execution import FakeBroker
from tests.unit.application.test_live_execution import (
    EVALUATED_AT,
    _limits,
    _policy,
    _runtime,
)
from tests.unit.application.test_live_execution_authority import (
    ACCOUNT,
    CLIENT,
    CONNECTION,
    TRANSPORT,
    _config_for_catalog,
    _evidence,
    _live_runtime,
    _request,
    _source,
)

_ALL_FIELDS = frozenset(LiveRiskEvidenceField)


def _blob(seal: str = "0" * 64) -> LiveRiskEvidenceSourceGrant:
    """A grant-shaped record with no catalog behind it."""
    return LiveRiskEvidenceSourceGrant(
        broker_id=BROKER_ID,
        builder_module="tests.unit.application.test_live_risk_source_trust",
        builder_qualname="_hostile_builder",
        binding=TrustedLiveRiskEvidenceBinding(
            source=_source(),
            account_id=ACCOUNT,
            broker_connection_id=CONNECTION,
            broker_client_id=CLIENT,
            transport=TRANSPORT,
        ),
        seal=seal,
    )


# The entry points that made the bypass possible are gone.


def test_execution_config_has_no_source_instance_field() -> None:
    assert "risk_evidence_source" not in inspect.signature(LiveExecutionConfig).parameters

    with pytest.raises(TypeError, match="risk_evidence_source"):
        LiveExecutionConfig(
            risk_limits=_limits(),
            risk_engine=PreTradeRiskEngine(),
            clock=FixedClock(EVALUATED_AT),
            market_policy=_policy(),
            policy_verifier=policy_verifier(),
            risk_evidence_source=_source(),  # type: ignore[call-arg]
        )


def test_authority_has_no_source_instance_parameter() -> None:
    assert "source" not in inspect.signature(LiveRiskEvidenceAuthority).parameters

    registered = registered_connection(account_id=ACCOUNT, connection_id=CONNECTION)
    catalog = catalog_for(_source(), broker_client_id=CLIENT, transport=TRANSPORT)
    grant = catalog.grant(registered)
    assert grant is not None

    with pytest.raises(TypeError, match="unexpected keyword argument 'source'"):
        LiveRiskEvidenceAuthority(
            source=_source(),  # type: ignore[call-arg]
            grant=grant,
            catalog=catalog,
            registry=registry_with(registered),
            limits=_limits(),
            clock=FixedClock(EVALUATED_AT),
        )


# A self-attesting source cannot reach admission by any caller-side route.


def test_a_forged_grant_for_the_sanctioned_broker_is_rejected() -> None:
    registered = registered_connection(account_id=ACCOUNT, connection_id=CONNECTION)
    catalog = catalog_for(_source(), broker_client_id=CLIENT, transport=TRANSPORT)
    forged = _blob()

    assert catalog.verify(forged) is False
    with pytest.raises(TypeError, match="application-issued source grant"):
        LiveRiskEvidenceAuthority(
            grant=forged,
            catalog=catalog,
            registry=registry_with(registered),
            limits=_limits(),
            clock=FixedClock(EVALUATED_AT),
        )


def test_swapping_a_hostile_source_into_a_real_grant_breaks_the_seal() -> None:
    registered = registered_connection(account_id=ACCOUNT, connection_id=CONNECTION)
    catalog = catalog_for(_source(), broker_client_id=CLIENT, transport=TRANSPORT)
    sanctioned = catalog.grant(registered)
    assert sanctioned is not None

    swapped = replace(
        sanctioned,
        binding=TrustedLiveRiskEvidenceBinding(
            source=_source(supported_fields=_ALL_FIELDS),
            account_id=ACCOUNT,
            broker_connection_id=CONNECTION,
            broker_client_id=CLIENT,
            transport=TRANSPORT,
        ),
    )

    assert catalog.verify(swapped) is False
    with pytest.raises(TypeError, match="application-issued source grant"):
        LiveRiskEvidenceAuthority(
            grant=swapped,
            catalog=catalog,
            registry=registry_with(registered),
            limits=_limits(),
            clock=FixedClock(EVALUATED_AT),
        )


def test_matching_identities_in_a_grant_shape_do_not_establish_trust() -> None:
    """Every identity value matches the registered connection and is still refused."""
    registered = registered_connection(account_id=ACCOUNT, connection_id=CONNECTION)
    fabricated = _blob()

    assert fabricated.binding.account_id == registered.ref.account_id
    assert fabricated.binding.broker_connection_id == registered.ref.connection_id
    assert fabricated.binding.broker_client_id == CLIENT
    assert fabricated.broker_id == registered.ref.broker_id

    catalog = catalog_for(_source(), broker_client_id=CLIENT, transport=TRANSPORT)
    assert catalog.verify(fabricated) is False


def test_a_catalog_that_sanctions_another_broker_cannot_grant_this_connection() -> None:
    registered = registered_connection(account_id=ACCOUNT, connection_id=CONNECTION)
    catalog = catalog_for(
        _source(),
        broker_client_id=CLIENT,
        transport=TRANSPORT,
        broker_id="some-other-broker",
    )

    assert catalog.grant(registered) is None
    assert catalog.verify(_blob()) is False


@pytest.mark.parametrize(
    "builder_result",
    [
        None,
        object(),
        TrustedLiveRiskEvidenceBinding(
            source=_source(),
            account_id=ACCOUNT,
            broker_connection_id=BrokerConnectionId("conn-foreign"),
            broker_client_id=CLIENT,
            transport=TRANSPORT,
        ),
        TrustedLiveRiskEvidenceBinding(
            source=_source(),
            account_id=AccountId("acct-foreign"),
            broker_connection_id=CONNECTION,
            broker_client_id=CLIENT,
            transport=TRANSPORT,
        ),
        TrustedLiveRiskEvidenceBinding(
            source=_source(),
            account_id=ACCOUNT,
            broker_connection_id=CONNECTION,
            broker_client_id="   ",
            transport=TRANSPORT,
        ),
        TrustedLiveRiskEvidenceBinding(
            source=_source(),
            account_id=ACCOUNT,
            broker_connection_id=CONNECTION,
            broker_client_id=CLIENT,
            transport=None,
        ),
        TrustedLiveRiskEvidenceBinding(
            source=object(),  # type: ignore[arg-type]
            account_id=ACCOUNT,
            broker_connection_id=CONNECTION,
            broker_client_id=CLIENT,
            transport=TRANSPORT,
        ),
    ],
    ids=[
        "none",
        "wrong-type",
        "foreign-connection",
        "foreign-account",
        "empty-client",
        "missing-transport",
        "not-a-source",
    ],
)
def test_a_binding_that_is_not_the_registered_construction_is_not_granted(
    builder_result,
) -> None:
    registered = registered_connection(account_id=ACCOUNT, connection_id=CONNECTION)
    catalog = catalog_with_builder(lambda _registered: builder_result)

    assert catalog.grant(registered) is None


def test_a_raising_builder_is_not_granted() -> None:
    registered = registered_connection(account_id=ACCOUNT, connection_id=CONNECTION)

    def build(_registered):
        raise RuntimeError("builder failure detail")

    assert catalog_with_builder(build).grant(registered) is None


def test_catalog_construction_rejects_empty_duplicate_and_wrong_entries() -> None:
    builder = LiveRiskEvidenceSourceBuilder(
        broker_id=BROKER_ID,
        build=lambda _registered: None,
    )

    with pytest.raises(TypeError, match="builder tuple"):
        LiveRiskEvidenceSourceCatalog(builders=[])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="LiveRiskEvidenceSourceBuilder"):
        LiveRiskEvidenceSourceCatalog(builders=(object(),))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="duplicate broker id"):
        LiveRiskEvidenceSourceCatalog(builders=(builder, builder))

    assert LiveRiskEvidenceSourceCatalog(builders=(builder,)).broker_ids == frozenset({BROKER_ID})


def test_builder_record_rejects_an_empty_broker_id_and_a_non_callable() -> None:
    with pytest.raises(ValueError, match="broker id"):
        LiveRiskEvidenceSourceBuilder(broker_id="  ", build=lambda _registered: None)
    with pytest.raises(ValueError, match="construction callable"):
        LiveRiskEvidenceSourceBuilder(broker_id=BROKER_ID, build=object())  # type: ignore[arg-type]


# Composition refuses before any durable state or broker submission exists.


def _assert_no_side_effects(database: SqliteDatabase, broker: FakeBroker) -> None:
    request = _request()
    assert broker.submit_calls == 0
    unit_of_work = SqliteUnitOfWork(database)
    decision = unit_of_work.idempotency.check(
        request.order.client_order_id, request_fingerprint(request)
    )
    assert decision.reservation_pending is False
    assert decision.existing_receipt_id is None
    assert unit_of_work.receipts.get_by_client_order(request.order.client_order_id) is None
    assert (
        SqliteSubmissionQuarantineRepository(database).list_by_client_order(
            request.order.client_order_id
        )
        == ()
    )


def test_unregistered_connection_is_rejected_before_reservation_and_submission(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        broker = FakeBroker()
        catalog = catalog_for(_source(), broker_client_id=CLIENT, transport=TRANSPORT)

        with pytest.raises(
            LiveExecutionCompositionError,
            match="account and broker connection this process registered",
        ):
            build_live_execution(_runtime(database), _config_for_catalog(catalog))

        assert SqliteTradingGateStateStore(database).load() is None
        _assert_no_side_effects(database, broker)
    finally:
        database.close()


def test_unsanctioned_broker_is_rejected_before_reservation_and_submission(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        broker = FakeBroker()
        catalog = catalog_for(
            _source(),
            broker_client_id=CLIENT,
            transport=TRANSPORT,
            broker_id="some-other-broker",
        )

        with pytest.raises(
            LiveExecutionCompositionError,
            match="application-registered risk evidence source for this broker",
        ):
            build_live_execution(_live_runtime(database), _config_for_catalog(catalog))

        assert SqliteTradingGateStateStore(database).load() is None
        _assert_no_side_effects(database, broker)
    finally:
        database.close()


def test_a_foreign_identity_builder_is_rejected_before_any_durable_write(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        broker = FakeBroker()

        def build(registered):
            return TrustedLiveRiskEvidenceBinding(
                source=_source(),
                account_id=AccountId("acct-foreign"),
                broker_connection_id=registered.ref.connection_id,
                broker_client_id=CLIENT,
                transport=TRANSPORT,
            )

        catalog = catalog_with_builder(build)

        with pytest.raises(
            LiveExecutionCompositionError,
            match="application-registered risk evidence source for this broker",
        ):
            build_live_execution(_live_runtime(database), _config_for_catalog(catalog))

        assert SqliteTradingGateStateStore(database).load() is None
        _assert_no_side_effects(database, broker)
    finally:
        database.close()


def test_a_rejected_composition_leaves_a_persisted_gate_untouched(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        store = SqliteTradingGateStateStore(database)
        store.save(TradingGateState(enabled=True))

        catalog = catalog_for(
            _source(),
            broker_client_id=CLIENT,
            transport=TRANSPORT,
            broker_id="some-other-broker",
        )
        with pytest.raises(LiveExecutionCompositionError):
            build_live_execution(_live_runtime(database), _config_for_catalog(catalog))

        assert store.load() == TradingGateState(enabled=True)
    finally:
        database.close()


# The sanctioned mechanism still works: an explicitly registered test builder.


def test_a_registered_test_builder_can_exercise_the_sanctioned_path(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        source = _source()
        catalog = catalog_for(source, broker_client_id=CLIENT, transport=TRANSPORT)
        stack = build_live_execution(_live_runtime(database), _config_for_catalog(catalog))
        stack.gate.enable()
        broker = FakeBroker()
        request = _request()

        result = stack.orchestrator.execute(request, broker=broker)

        assert result.status is ExecutionDispatchStatus.EXECUTED
        assert result.receipt is not None
        assert source.calls == 1
        assert broker.submit_calls == 1
        decision = SqliteUnitOfWork(database).idempotency.check(
            request.order.client_order_id, request_fingerprint(request)
        )
        assert decision.reservation_pending is False
        assert decision.existing_receipt_id == result.receipt.receipt_id
    finally:
        database.close()


def test_the_sanctioned_source_is_the_one_the_catalog_built() -> None:
    registered = registered_connection(account_id=ACCOUNT, connection_id=CONNECTION)
    source = _source()
    catalog = catalog_for(source, broker_client_id=CLIENT, transport=TRANSPORT)
    grant = catalog.grant(registered)
    assert grant is not None

    assert grant.binding.source is source
    assert grant.binding.transport is TRANSPORT
    assert grant.broker_id == BROKER_ID
    assert grant.builder_module == catalog_for.__module__
    assert grant.builder_qualname == "catalog_for.<locals>.build"
    assert catalog.verify(grant) is True


def test_fabricated_evidence_is_internally_consistent_yet_unauthorized() -> None:
    """The old design admitted exactly this shape; trust is what changed."""
    evidence = _evidence(
        reference_price=Decimal("100"),
        contradictions=(),
        unavailable_fields=(),
    )

    assert evidence.account_id == ACCOUNT
    assert evidence.broker_connection_id == CONNECTION
    assert evidence.broker_client_id == CLIENT
    assert evidence.transport is TRANSPORT
    assert set(evidence.observations) == _ALL_FIELDS
    assert evidence.unavailable_fields == ()

    registered = registered_connection(account_id=ACCOUNT, connection_id=CONNECTION)
    catalog = catalog_for(_source(), broker_client_id=CLIENT, transport=TRANSPORT)
    forged = _blob()
    assert forged.binding.source.collect(_request()).observations.keys() == (
        evidence.observations.keys()
    )
    assert catalog.verify(forged) is False
    assert catalog.grant(registered) is not None
