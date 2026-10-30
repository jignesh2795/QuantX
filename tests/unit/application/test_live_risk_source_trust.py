"""Regression tests for the LIVE risk-evidence source-trust boundary.

Two bypasses are pinned here.

The first, closed earlier: a caller-created source implemented the evidence
protocol, claimed every required field, echoed the configured account,
connection, client id and transport, and returned internally consistent but
fabricated financial values. Identity binding and HMAC sealing proved only that
the authority had wrapped those values.

The second, closed here: the earlier correction introduced a caller-configurable
``LiveRiskEvidenceSourceCatalog``. A caller could build a catalog, register a
builder under the legitimate ``dhan`` broker id, and hand it to the sanctioned
composition root next to a genuine registered connection. The catalog minted
its own grant, the authority verified it against that same catalog, and
fabricated evidence reached the risk engine and the broker.

The correction: trust follows the registered execution path. The sanctioned
configuration has no catalog field, and catalog creation is not exposed as a
public composition API. A module-local constructor token is API encapsulation,
not a security boundary against arbitrary Python code running in the same
process. The only sanctioned construction path is the bound method of the
adapter behind the connection this process registered.
"""

from __future__ import annotations

import inspect
from dataclasses import replace
from decimal import Decimal

import pytest

import quantx.application.live_risk_sources as live_risk_sources
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
    LiveRiskEvidenceSourceCatalog,
    LiveRiskEvidenceSourceGrant,
    TrustedLiveRiskEvidenceBinding,
    live_risk_evidence_catalog_for,
)
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.clock import FixedClock
from quantx.domain.risk import PreTradeRiskEngine
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.trading_gate import TradingGateState
from quantx.integrations.account_registry import RegisteredConnection
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.persistence.sqlite import (
    SqliteDatabase,
    SqliteSubmissionQuarantineRepository,
    SqliteTradingGateStateStore,
    SqliteUnitOfWork,
)
from tests.unit._execution_request_proofs import policy_verifier
from tests.unit.application._live_risk_trust import (
    BROKER_ID,
    RegistryAdapter,
    catalog_for,
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
    _config,
    _evidence,
    _live_runtime,
    _live_stack,
    _request,
    _source,
)

_ALL_FIELDS = frozenset(LiveRiskEvidenceField)


def _blob(seal: str = "0" * 64) -> LiveRiskEvidenceSourceGrant:
    """A grant-shaped record with no application catalog behind it."""
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


class _ReturningAdapter(RegistryAdapter):
    """Registered adapter whose construction path returns a chosen result."""

    def __init__(self, connection: BrokerConnectionRef, result: object) -> None:
        super().__init__(connection)
        self._result = result
        self.binding_calls = 0

    def build_live_risk_evidence_binding(self, registered: RegisteredConnection) -> object:
        self.binding_calls += 1
        return self._result


class _RaisingAdapter(RegistryAdapter):
    """Registered adapter whose construction path fails."""

    def __init__(self, connection: BrokerConnectionRef) -> None:
        super().__init__(connection)
        self.binding_calls = 0

    def build_live_risk_evidence_binding(self, registered: RegisteredConnection) -> object:
        self.binding_calls += 1
        raise RuntimeError("provider failure detail")


def _registered_with(result: object) -> RegisteredConnection:
    ref = BrokerConnectionRef(ACCOUNT, CONNECTION, BROKER_ID, "NSE")
    return RegisteredConnection(ref, _ReturningAdapter(ref, result))


# The configuration surface that made the bypass possible is gone.


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


def test_execution_config_has_no_catalog_field() -> None:
    """The reported exploit's injection point no longer exists."""
    assert "risk_evidence_catalog" not in inspect.signature(LiveExecutionConfig).parameters

    with pytest.raises(TypeError, match="risk_evidence_catalog"):
        LiveExecutionConfig(
            risk_limits=_limits(),
            risk_engine=PreTradeRiskEngine(),
            clock=FixedClock(EVALUATED_AT),
            market_policy=_policy(),
            policy_verifier=policy_verifier(),
            risk_evidence_catalog=object(),  # type: ignore[call-arg]
        )


def test_catalog_has_no_public_construction_path() -> None:
    with pytest.raises(TypeError, match="application construction token"):
        LiveRiskEvidenceSourceCatalog(builders=())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="application construction token"):
        LiveRiskEvidenceSourceCatalog(builders=(object(),), token=object())  # type: ignore[arg-type]

    assert not hasattr(live_risk_sources, "LiveRiskEvidenceSourceBuilder")


def test_authority_has_no_source_instance_parameter() -> None:
    assert "source" not in inspect.signature(LiveRiskEvidenceAuthority).parameters

    registered = registered_connection(
        account_id=ACCOUNT, connection_id=CONNECTION, source=_source()
    )
    catalog = catalog_for(registered)
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


# The reported bypass cannot get past its own first step.


def test_published_catalog_bypass_is_closed_at_public_composition_boundary(tmp_path) -> None:
    """The supported public composition API cannot inject a caller-owned catalog."""
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        source = _source()

        # 1. The public constructor rejects an untrusted token. This is API
        #    encapsulation, not protection from arbitrary in-process Python code.
        with pytest.raises(TypeError, match="application construction token"):
            LiveRiskEvidenceSourceCatalog(
                builders=(object(),),  # type: ignore[arg-type]
                token=object(),
            )

        # 2. A catalog-shaped object has nowhere to go: the sanctioned config
        #    has no such field.
        assert "risk_evidence_catalog" not in inspect.signature(LiveExecutionConfig).parameters

        # 3. The sanctioned root refuses the composition outright, before any
        #    durable write, evidence collection, reservation or submission.
        broker = FakeBroker()
        with pytest.raises(
            LiveExecutionCompositionError,
            match="construction path on the registered broker adapter",
        ):
            build_live_execution(_live_runtime(database), _config())

        assert source.calls == 0
        assert SqliteTradingGateStateStore(database).load() is None
        _assert_no_side_effects(database, broker)
    finally:
        database.close()


# A self-attesting source cannot reach admission by any caller-side route.


def test_a_forged_grant_for_the_sanctioned_broker_is_rejected() -> None:
    registered = registered_connection(
        account_id=ACCOUNT, connection_id=CONNECTION, source=_source()
    )
    catalog = catalog_for(registered)
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
    registered = registered_connection(
        account_id=ACCOUNT, connection_id=CONNECTION, source=_source()
    )
    catalog = catalog_for(registered)
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
    registered = registered_connection(
        account_id=ACCOUNT, connection_id=CONNECTION, source=_source()
    )
    fabricated = _blob()

    assert fabricated.binding.account_id == registered.ref.account_id
    assert fabricated.binding.broker_connection_id == registered.ref.connection_id
    assert fabricated.binding.broker_client_id == CLIENT
    assert fabricated.broker_id == registered.ref.broker_id

    assert catalog_for(registered).verify(fabricated) is False
    with pytest.raises(TypeError, match="application-issued source grant"):
        LiveRiskEvidenceAuthority(
            grant=fabricated,
            catalog=catalog_for(registered),
            registry=registry_with(registered),
            limits=_limits(),
            clock=FixedClock(EVALUATED_AT),
        )


def test_a_catalog_derived_from_another_registration_cannot_grant_this_connection() -> None:
    registered = registered_connection(
        account_id=ACCOUNT, connection_id=CONNECTION, source=_source()
    )
    other = registered_connection(account_id=ACCOUNT, connection_id=CONNECTION, source=_source())

    assert catalog_for(other).verify(_blob()) is False
    grant = catalog_for(registered).grant(registered)
    assert grant is not None
    assert catalog_for(other).verify(grant) is False


@pytest.mark.parametrize(
    "result",
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
def test_a_provider_result_that_is_not_the_registered_construction_is_not_granted(
    result,
) -> None:
    registered = _registered_with(result)
    catalog = live_risk_evidence_catalog_for(registered)
    assert catalog is not None

    assert catalog.grant(registered) is None


def test_a_raising_provider_is_not_granted() -> None:
    ref = BrokerConnectionRef(ACCOUNT, CONNECTION, BROKER_ID, "NSE")
    registered = RegisteredConnection(ref, _RaisingAdapter(ref))
    catalog = live_risk_evidence_catalog_for(registered)
    assert catalog is not None

    assert catalog.grant(registered) is None


def test_a_plain_registration_exposes_no_construction_path() -> None:
    registered = registered_connection(account_id=ACCOUNT, connection_id=CONNECTION)

    assert not isinstance(registered.adapter, live_risk_sources.LiveRiskEvidenceSourceProvider)
    assert live_risk_evidence_catalog_for(registered) is None


def test_a_disabled_connection_exposes_no_construction_path() -> None:
    registered = registered_connection(
        account_id=ACCOUNT,
        connection_id=CONNECTION,
        enabled=False,
        source=_source(),
    )

    assert live_risk_evidence_catalog_for(registered) is None


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

        with pytest.raises(
            LiveExecutionCompositionError,
            match="account and broker connection this process registered",
        ):
            build_live_execution(_runtime(database), _config())

        assert SqliteTradingGateStateStore(database).load() is None
        _assert_no_side_effects(database, broker)
    finally:
        database.close()


def test_a_connection_without_a_construction_path_is_rejected_before_side_effects(
    tmp_path,
) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        broker = FakeBroker()

        with pytest.raises(
            LiveExecutionCompositionError,
            match="construction path on the registered broker adapter",
        ):
            build_live_execution(_live_runtime(database), _config())

        assert SqliteTradingGateStateStore(database).load() is None
        _assert_no_side_effects(database, broker)
    finally:
        database.close()


def test_a_foreign_identity_binding_is_rejected_before_any_durable_write(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        broker = FakeBroker()
        registered = registered_connection(
            account_id=ACCOUNT,
            connection_id=CONNECTION,
            binding=TrustedLiveRiskEvidenceBinding(
                source=_source(),
                account_id=AccountId("acct-foreign"),
                broker_connection_id=CONNECTION,
                broker_client_id=CLIENT,
                transport=TRANSPORT,
            ),
        )
        runtime = _runtime(database)
        runtime.registry.register(registered)

        with pytest.raises(
            LiveExecutionCompositionError,
            match="construction path on the registered broker adapter",
        ):
            build_live_execution(runtime, _config())

        assert SqliteTradingGateStateStore(database).load() is None
        _assert_no_side_effects(database, broker)
    finally:
        database.close()


def test_a_rejected_composition_leaves_a_persisted_gate_untouched(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        store = SqliteTradingGateStateStore(database)
        store.save(TradingGateState(enabled=True))

        with pytest.raises(LiveExecutionCompositionError):
            build_live_execution(_live_runtime(database), _config())

        assert store.load() == TradingGateState(enabled=True)
    finally:
        database.close()


# The sanctioned mechanism still works: the registered adapter's own path.


def test_a_registered_adapter_path_can_exercise_the_sanctioned_stack(tmp_path) -> None:
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        source = _source()
        stack, broker = _live_stack(database, source=source)
        stack.gate.enable()
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


def test_a_distinct_broker_with_matching_identifiers_is_rejected(tmp_path) -> None:
    """Matching ids are not trust: the submitting object must be the registered one.

    The registered adapter owns the evidence construction path. A second object
    that reports the same account and connection would otherwise receive an
    order authorized by evidence collected from a different adapter.
    """
    database = SqliteDatabase(tmp_path / "quantx.db")
    try:
        source = _source()
        stack, registered = _live_stack(database, source=source)
        stack.gate.enable()
        impostor = FakeBroker(account_id=ACCOUNT, connection_id=CONNECTION)

        assert impostor is not registered
        assert impostor.connection.account_id == registered.connection.account_id
        assert impostor.connection.connection_id == registered.connection.connection_id

        request = _request()
        result = stack.orchestrator.execute(request, broker=impostor)

        assert result.status is ExecutionDispatchStatus.BLOCKED
        assert "registered broker adapter" in result.reason
        assert result.receipt is None
        assert impostor.submit_calls == 0
        assert source.calls == 0
        assert stack.gate.state().enabled is True
        _assert_no_side_effects(database, impostor)
    finally:
        database.close()


def test_the_sanctioned_source_is_the_one_the_registered_adapter_built() -> None:
    source = _source()
    registered = registered_connection(
        account_id=ACCOUNT,
        connection_id=CONNECTION,
        source=source,
        transport=TRANSPORT,
    )
    catalog = catalog_for(registered)
    grant = catalog.grant(registered)
    assert grant is not None

    assert grant.binding.source is source
    assert grant.binding.transport is TRANSPORT
    assert grant.broker_id == BROKER_ID
    assert grant.builder_module == "tests.unit.application._live_risk_trust"
    assert grant.builder_qualname == "EvidenceAdapter.build_live_risk_evidence_binding"
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

    registered = registered_connection(
        account_id=ACCOUNT, connection_id=CONNECTION, source=_source()
    )
    forged = _blob()
    assert forged.binding.source.collect(_request()).observations.keys() == (
        evidence.observations.keys()
    )
    assert catalog_for(registered).verify(forged) is False
    assert catalog_for(registered).grant(registered) is not None
