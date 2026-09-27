"""Dhan broker evidence feeds canonical reconciliation and preconditions."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.enums import AssetClass
from quantx.domain.instruments import (
    Instrument,
    InstrumentId,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.execution.preconditions.evaluator import execution_ready_from_evidence
from quantx.integrations.brokers import BrokerConnectionRef
from quantx.integrations.reconciliation import (
    AccountFinancialState,
    AccountReconciler,
    AccountReconciliationStatus,
    PositionReconciler,
    PositionState,
    ReconciliationPolicy,
    ReconciliationStatus,
    StateSource,
)
from quantx.plugins.dhan import (
    DhanBrokerAdapter,
    DhanInstrumentRef,
    InMemoryDhanTransport,
)
from quantx.plugins.dhan.models import DhanPositionSnapshot


def _adapter(transport: InMemoryDhanTransport) -> DhanBrokerAdapter:
    instrument = Instrument(
        instrument_id=InstrumentId("NSE", "TCS"),
        symbol="TCS",
        asset_class=AssetClass.EQUITY,
        market=MarketContext(MarketRegion.INDIA, MarketFamily.EQUITY, "NSE", "IN"),
        currency="INR",
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
    )
    return DhanBrokerAdapter(
        _connection=BrokerConnectionRef(
            AccountId("acct-1"),
            BrokerConnectionId("conn-1"),
            "dhan",
            "NSE_EQ",
        ),
        _instruments={
            instrument.instrument_id: (
                instrument,
                DhanInstrumentRef("1333", "NSE_EQ", "TCS", "CNC"),
            )
        },
        _transport=transport,
    )


def _transport() -> InMemoryDhanTransport:
    return InMemoryDhanTransport(
        funds_available_balance=Decimal("5000"),
        funds_utilized_amount=Decimal("1200"),
        position_snapshots=(DhanPositionSnapshot("1333", "NSE_EQ", Decimal("10"), Decimal("100")),),
    )


def test_dhan_account_observation_reconciles_against_local_state() -> None:
    observed = _adapter(_transport()).account_state()
    checked_at = observed.observed_at
    local = AccountFinancialState(
        account_id=AccountId("acct-1"),
        connection_id=BrokerConnectionId("conn-1"),
        observed_at=checked_at,
        source=StateSource.PAPER,
        currency="INR",
        available_cash=Decimal("5000"),
        margin_used=Decimal("1200"),
    )

    report = AccountReconciler().compare(
        local,
        observed,
        checked_at=checked_at,
        max_state_age=timedelta(seconds=30),
    )

    assert report.status is AccountReconciliationStatus.MATCHED


def test_dhan_position_observation_yields_execution_ready_evidence() -> None:
    observed = _adapter(_transport()).position_states()
    checked_at = observed[0].observed_at
    local = PositionState(
        AccountId("acct-1"),
        BrokerConnectionId("conn-1"),
        "NSE:TCS",
        Decimal("10"),
        Decimal("100"),
        checked_at,
        StateSource.PAPER,
    )

    result = PositionReconciler().reconcile(
        local,
        observed[0],
        checked_at=checked_at,
        policy=ReconciliationPolicy(timedelta(seconds=30)),
    )
    assert result.status is ReconciliationStatus.MATCHED
    precondition = execution_ready_from_evidence(
        account_state_status="MATCHED",
        position_state_status=result.status.value,
        connection_health="HEALTHY",
        required_capabilities_ok=True,
    )
    assert precondition.can_execute


def test_unknown_evidence_never_produces_execution_ready() -> None:
    precondition = execution_ready_from_evidence(
        account_state_status=None,
        position_state_status=None,
        connection_health=None,
        required_capabilities_ok=None,
    )

    assert not precondition.can_execute
