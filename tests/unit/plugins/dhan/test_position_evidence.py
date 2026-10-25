"""Fail-closed tests for Dhan whole-account position evidence (Slice C2b)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from quantx.domain.enums import AssetClass
from quantx.domain.instruments import (
    Instrument,
    MarketContext,
    MarketFamily,
    MarketRegion,
)
from quantx.domain.risk_evidence import EvidenceStatus, PositionSurface
from quantx.domain.value_objects import (
    AccountId,
    BrokerConnectionId,
    InstrumentId,
)
from quantx.plugins.dhan.models import (
    DhanHoldingSnapshot,
    DhanInstrumentRef,
    DhanPositionSnapshot,
)
from quantx.plugins.dhan.position_evidence import (
    DhanWholeAccountPositionBlocker as B,
)
from quantx.plugins.dhan.position_evidence import (
    DhanWholeAccountPositionSource,
)
from quantx.plugins.dhan.transport import (
    DEFAULT_READ_TIMEOUT_SECONDS,
    DhanTransport,
    InMemoryDhanTransport,
)

ACCOUNT = AccountId("acct-1")
CONNECTION = BrokerConnectionId("conn-1")
OBSERVED_AT = datetime(2026, 1, 1, tzinfo=UTC)
TCS = InstrumentId("NSE", "TCS")
PRODUCT_MAP = {"CNC": "CNC", "MIS": "INTRADAY", "NRML": "MARGIN"}
STATIC_BLOCKERS = (
    B.POSITIONS_TIMESTAMP.value,
    B.POSITIONS_SCOPE.value,
    B.HOLDINGS_TIMESTAMP.value,
    B.HOLDINGS_SCOPE.value,
    B.HOLDINGS_PRODUCT_IDENTITY.value,
    B.HOLDINGS_EXPOSURE_QUANTITY.value,
    B.CROSS_SURFACE_OVERLAP_POLICY.value,
    B.MARK_AUTHORITY.value,
    B.MARK_TIMESTAMP.value,
)


@dataclass(slots=True)
class _RecordingTransport:
    """Record reads and delegate everything else to a deterministic transport."""

    inner: InMemoryDhanTransport = field(default_factory=InMemoryDhanTransport)
    position_error: Exception | None = None
    holding_error: Exception | None = None
    quote_reads: int = 0
    seen_timeouts: list[float] = field(default_factory=list)

    def positions(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> Any:
        self.seen_timeouts.append(timeout)
        if self.position_error is not None:
            raise self.position_error
        return self.inner.positions(timeout=timeout)

    def holdings(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> Any:
        self.seen_timeouts.append(timeout)
        if self.holding_error is not None:
            raise self.holding_error
        return self.inner.holdings(timeout=timeout)

    def quote_snapshot(
        self,
        security_id: str,
        exchange_segment: str,
        *,
        timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> Any:
        self.quote_reads += 1
        return self.inner.quote_snapshot(
            security_id,
            exchange_segment,
            timeout=timeout,
        )

    def health(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> Any:
        return self.inner.health(timeout=timeout)

    def submit(self, request: Any, *, timeout: float) -> Any:
        return self.inner.submit(request, timeout=timeout)

    def cancel(self, correlation_id: str, *, timeout: float) -> Any:
        return self.inner.cancel(correlation_id, timeout=timeout)

    def reconcile(self, correlation_id: str, *, timeout: float) -> Any:
        return self.inner.reconcile(correlation_id, timeout=timeout)

    def fund_limits(self, *, timeout: float = DEFAULT_READ_TIMEOUT_SECONDS) -> Any:
        return self.inner.fund_limits(timeout=timeout)

    def candles(
        self,
        security_id: str,
        exchange_segment: str,
        *,
        timeframe: str,
        start: datetime,
        end: datetime,
        instrument_type: str = "EQUITY",
        timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
    ) -> Any:
        return self.inner.candles(
            security_id,
            exchange_segment,
            timeframe=timeframe,
            start=start,
            end=end,
            instrument_type=instrument_type,
            timeout=timeout,
        )

    def close(self) -> None:
        self.inner.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def _instrument(
    instrument_id: InstrumentId = TCS,
    *,
    symbol: str = "TCS",
    venue: str = "NSE",
    asset_class: AssetClass = AssetClass.EQUITY,
    family: MarketFamily = MarketFamily.EQUITY,
    currency: str = "INR",
    multiplier: str = "1",
) -> Instrument:
    return Instrument(
        instrument_id=instrument_id,
        symbol=symbol,
        asset_class=asset_class,
        market=MarketContext(MarketRegion.INDIA, family, venue, "IN"),
        currency=currency,
        tick_size=Decimal("0.05"),
        lot_size=Decimal("1"),
        multiplier=Decimal(multiplier),
    )


def _ref(
    security_id: str = "1333",
    exchange_segment: str = "NSE_EQ",
    trading_symbol: str = "TCS",
) -> DhanInstrumentRef:
    return DhanInstrumentRef(
        security_id=security_id,
        exchange_segment=exchange_segment,
        trading_symbol=trading_symbol,
    )


def _instruments(
    *entries: tuple[Instrument, DhanInstrumentRef],
) -> dict[InstrumentId, tuple[Instrument, DhanInstrumentRef]]:
    return {instrument.instrument_id: (instrument, reference) for instrument, reference in entries}


def _source(
    transport: DhanTransport | None,
    *,
    instruments: Mapping[InstrumentId, tuple[Instrument, DhanInstrumentRef]] | None = None,
    product_map: Mapping[str, str] | None = PRODUCT_MAP,
    read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
) -> DhanWholeAccountPositionSource:
    return DhanWholeAccountPositionSource(
        account_id=ACCOUNT,
        connection_id=CONNECTION,
        instruments=instruments or _instruments((_instrument(), _ref())),
        transport=transport,
        product_map=product_map,
        read_timeout=read_timeout,
    )


def _position(**overrides: object) -> DhanPositionSnapshot:
    values: dict[str, object] = {
        "security_id": "1333",
        "exchange_segment": "NSE_EQ",
        "trading_symbol": "TCS",
        "net_quantity": Decimal("10"),
        "average_price": Decimal("100"),
        "product_type": "CNC",
        "position_type": "LONG",
        "multiplier": Decimal("1"),
    }
    values.update(overrides)
    return DhanPositionSnapshot(**values)  # type: ignore[arg-type]


def _holding(**overrides: object) -> DhanHoldingSnapshot:
    values: dict[str, object] = {
        "security_id": "1333",
        "exchange": "ALL",
        "trading_symbol": "TCS",
        "total_quantity": Decimal("10"),
        "average_cost_price": Decimal("100"),
    }
    values.update(overrides)
    return DhanHoldingSnapshot(**values)  # type: ignore[arg-type]


def _transport(
    *,
    positions: tuple[DhanPositionSnapshot, ...] = (),
    holdings: tuple[DhanHoldingSnapshot, ...] = (),
) -> InMemoryDhanTransport:
    return InMemoryDhanTransport(
        position_snapshots=positions,
        holding_snapshots=holdings,
    )


def _surface(evidence: object, surface: PositionSurface) -> object:
    for item in evidence.surfaces:  # type: ignore[attr-defined]
        if item.surface is surface:
            return item
    raise AssertionError(f"missing {surface.value} surface")


def _assert_static_blockers(blockers: tuple[str, ...]) -> None:
    for blocker in STATIC_BLOCKERS:
        assert blocker in blockers


def _has(blockers: tuple[str, ...], blocker: B) -> bool:
    """Match a blocker code with or without its audited detail suffix."""
    return any(item == blocker.value or item.startswith(f"{blocker.value}:") for item in blockers)


def test_source_without_transport_is_explicitly_unavailable() -> None:
    evidence = _source(None).observe_whole_account_positions(observed_at=OBSERVED_AT)

    assert evidence.completeness is EvidenceStatus.UNAVAILABLE
    assert evidence.positions == ()
    assert _surface(evidence, PositionSurface.POSITIONS).status is EvidenceStatus.UNAVAILABLE
    assert _surface(evidence, PositionSurface.HOLDINGS).status is EvidenceStatus.UNAVAILABLE
    assert _surface(evidence, PositionSurface.MARKS).status is EvidenceStatus.UNAVAILABLE
    assert B.TRANSPORT.value in evidence.blockers
    _assert_static_blockers(evidence.blockers)


def test_source_observes_rows_but_never_claims_a_complete_or_marked_book() -> None:
    transport = _RecordingTransport(
        inner=_transport(positions=(_position(),), holdings=(_holding(exchange="NSE"),))
    )

    evidence = _source(transport).observe_whole_account_positions(observed_at=OBSERVED_AT)

    assert evidence.completeness is EvidenceStatus.INCOMPLETE
    assert evidence.completeness is not EvidenceStatus.COMPLETE
    assert evidence.positions == ()
    assert _surface(evidence, PositionSurface.POSITIONS).row_count == 1
    assert _surface(evidence, PositionSurface.HOLDINGS).row_count == 1
    assert _surface(evidence, PositionSurface.MARKS).status is EvidenceStatus.UNAVAILABLE
    assert transport.quote_reads == 0
    assert _has(evidence.blockers, B.CROSS_SURFACE_OVERLAP)
    _assert_static_blockers(evidence.blockers)


def test_empty_available_surfaces_are_not_a_zero_book_claim() -> None:
    transport = _transport()

    evidence = _source(transport).observe_whole_account_positions(observed_at=OBSERVED_AT)

    assert evidence.completeness is EvidenceStatus.INCOMPLETE
    assert evidence.positions == ()
    assert _surface(evidence, PositionSurface.POSITIONS).row_count == 0
    assert _surface(evidence, PositionSurface.HOLDINGS).row_count == 0
    _assert_static_blockers(evidence.blockers)


def test_unavailable_surfaces_name_the_failed_read_as_a_blocker() -> None:
    transport = InMemoryDhanTransport(
        positions_available=False,
        positions_message="denied",
        holdings_available=False,
        holdings_message="denied",
    )

    evidence = _source(transport).observe_whole_account_positions(observed_at=OBSERVED_AT)

    assert evidence.completeness is EvidenceStatus.UNAVAILABLE
    assert _has(evidence.blockers, B.POSITIONS_UNAVAILABLE)
    assert _has(evidence.blockers, B.HOLDINGS_UNAVAILABLE)
    assert _surface(evidence, PositionSurface.POSITIONS).status is EvidenceStatus.UNAVAILABLE
    assert _surface(evidence, PositionSurface.HOLDINGS).status is EvidenceStatus.UNAVAILABLE


def test_transport_failures_are_classified_without_leaking_message_content() -> None:
    transport = _RecordingTransport(
        position_error=RuntimeError("access_token=super-secret"),
        holding_error=RuntimeError("access_token=super-secret"),
    )

    evidence = _source(transport).observe_whole_account_positions(observed_at=OBSERVED_AT)

    assert f"{B.POSITIONS_UNAVAILABLE.value}: RuntimeError" in evidence.blockers
    assert f"{B.HOLDINGS_UNAVAILABLE.value}: RuntimeError" in evidence.blockers
    assert "super-secret" not in " ".join(evidence.blockers)


def test_missing_product_map_is_named_and_does_not_crash() -> None:
    transport = _transport(positions=(_position(),))

    evidence = _source(transport, product_map=None).observe_whole_account_positions(
        observed_at=OBSERVED_AT
    )

    assert B.PRODUCT_MAP.value in evidence.blockers
    assert not _has(evidence.blockers, B.POSITION_PRODUCT_UNMAPPED)
    assert evidence.completeness is EvidenceStatus.INCOMPLETE


def test_ambiguous_product_map_is_rejected_explicitly() -> None:
    transport = _transport(positions=(_position(),))

    evidence = _source(
        transport,
        product_map={"CNC": "CNC", "DELIVERY": "CNC"},
    ).observe_whole_account_positions(observed_at=OBSERVED_AT)

    assert B.PRODUCT_MAP_AMBIGUOUS.value in evidence.blockers
    assert evidence.completeness is EvidenceStatus.INCOMPLETE


def test_explicit_neutral_to_wire_product_mapping_is_used_when_configured() -> None:
    transport = _transport(positions=(_position(product_type="INTRADAY"),))

    evidence = _source(transport, product_map={"MIS": "INTRADAY"}).observe_whole_account_positions(
        observed_at=OBSERVED_AT
    )

    assert not _has(evidence.blockers, B.POSITION_PRODUCT_MISSING)
    assert not _has(evidence.blockers, B.POSITION_PRODUCT_UNMAPPED)
    assert evidence.completeness is not EvidenceStatus.COMPLETE


@pytest.mark.parametrize(
    ("overrides", "blocker"),
    [
        ({"security_id": "9999"}, B.POSITION_UNMAPPED),
        ({"product_type": None}, B.POSITION_PRODUCT_MISSING),
        ({"product_type": "MTF"}, B.POSITION_PRODUCT_UNMAPPED),
        ({"position_type": None}, B.POSITION_TYPE),
        ({"position_type": "SIDEWAYS"}, B.POSITION_TYPE),
        ({"position_type": "SHORT"}, B.POSITION_SIGN),
        ({"position_type": "CLOSED"}, B.POSITION_SIGN),
        ({"net_quantity": Decimal("0")}, B.POSITION_SIGN),
        ({"average_price": None}, B.POSITION_COST_BASIS),
        ({"average_price": Decimal("0")}, B.POSITION_COST_BASIS),
        ({"multiplier": Decimal("2")}, B.POSITION_MULTIPLIER),
        ({"cross_currency": True}, B.POSITION_CROSS_CURRENCY),
    ],
)
def test_position_row_inconsistencies_are_named(
    overrides: dict[str, object],
    blocker: B,
) -> None:
    transport = _transport(positions=(_position(**overrides),))

    evidence = _source(transport).observe_whole_account_positions(observed_at=OBSERVED_AT)

    assert _has(evidence.blockers, blocker)
    assert evidence.positions == ()


@pytest.mark.parametrize(
    ("overrides", "blocker"),
    [
        ({"total_quantity": None}, B.HOLDING_QUANTITY),
        ({"total_quantity": Decimal("0")}, B.HOLDING_QUANTITY),
        ({"average_cost_price": None}, B.HOLDING_COST_BASIS),
        ({"average_cost_price": Decimal("0")}, B.HOLDING_COST_BASIS),
        ({"t1_quantity": Decimal("1")}, B.HOLDING_T1),
        ({"collateral_quantity": Decimal("1")}, B.HOLDING_COLLATERAL),
        ({"exchange": "NSE_FNO"}, B.HOLDING_EXCHANGE),
        ({"security_id": "9999"}, B.HOLDING_UNMAPPED),
    ],
)
def test_holding_row_inconsistencies_are_named(
    overrides: dict[str, object],
    blocker: B,
) -> None:
    transport = _transport(holdings=(_holding(**overrides),))

    evidence = _source(transport).observe_whole_account_positions(observed_at=OBSERVED_AT)

    assert _has(evidence.blockers, blocker)
    assert evidence.positions == ()


def test_holding_exchange_filter_uses_the_canonical_segment_when_supplied() -> None:
    transport = _transport(holdings=(_holding(exchange="NSE"),))

    evidence = _source(transport).observe_whole_account_positions(observed_at=OBSERVED_AT)

    assert not _has(evidence.blockers, B.HOLDING_UNMAPPED)
    assert not _has(evidence.blockers, B.HOLDING_EXCHANGE)
    assert not _has(evidence.blockers, B.HOLDING_VENUE_IDENTITY)


def test_exchange_all_holding_never_proves_venue_identity() -> None:
    transport = _transport(
        positions=(_position(),),
        holdings=(_holding(exchange="ALL"),),
    )

    evidence = _source(transport).observe_whole_account_positions(observed_at=OBSERVED_AT)

    assert _has(evidence.blockers, B.HOLDING_VENUE_IDENTITY)
    assert not _has(evidence.blockers, B.HOLDING_AMBIGUOUS)
    assert not any(
        blocker.startswith(f"{B.CROSS_SURFACE_OVERLAP.value}:") for blocker in evidence.blockers
    )
    assert evidence.positions == ()


def test_holding_row_ambiguous_across_segments_is_rejected() -> None:
    instruments = _instruments(
        (_instrument(TCS, symbol="TCS", venue="NSE"), _ref("1333", "NSE_EQ")),
        (
            _instrument(InstrumentId("BSE", "TCS"), symbol="TCS", venue="BSE"),
            _ref("1333", "BSE_EQ"),
        ),
    )
    transport = _transport(holdings=(_holding(exchange="ALL"),))

    evidence = _source(transport, instruments=instruments).observe_whole_account_positions(
        observed_at=OBSERVED_AT
    )

    assert _has(evidence.blockers, B.HOLDING_AMBIGUOUS)
    assert _has(evidence.blockers, B.HOLDING_VENUE_IDENTITY)
    assert evidence.positions == ()


def test_duplicate_position_rows_are_named_not_summed() -> None:
    transport = _transport(positions=(_position(), _position()))

    evidence = _source(transport).observe_whole_account_positions(observed_at=OBSERVED_AT)

    assert _has(evidence.blockers, B.POSITION_DUPLICATE)
    assert evidence.positions == ()


def test_duplicate_holding_rows_are_named_not_summed() -> None:
    transport = _transport(holdings=(_holding(), _holding()))

    evidence = _source(transport).observe_whole_account_positions(observed_at=OBSERVED_AT)

    assert _has(evidence.blockers, B.HOLDING_DUPLICATE)
    assert evidence.positions == ()


def test_derivative_contract_quantity_basis_is_named() -> None:
    future = _instrument(
        InstrumentId("NSE", "FUT"),
        symbol="FUT",
        venue="NSE",
        asset_class=AssetClass.FUTURE,
        family=MarketFamily.DERIVATIVES,
        multiplier="50",
    )
    instruments = _instruments((future, _ref("5000", "NSE_FNO", "FUT")))
    transport = _transport(
        positions=(
            _position(
                security_id="5000",
                exchange_segment="NSE_FNO",
                trading_symbol="FUT",
                product_type="NRML",
                multiplier=Decimal("50"),
            ),
        )
    )

    evidence = _source(transport, instruments=instruments).observe_whole_account_positions(
        observed_at=OBSERVED_AT
    )

    assert _has(evidence.blockers, B.DERIVATIVE_QUANTITY)
    assert evidence.positions == ()


def test_surface_skew_and_future_observations_are_named() -> None:
    transport = _transport(positions=(_position(),), holdings=(_holding(),))

    stale = _source(transport).observe_whole_account_positions(
        observed_at=OBSERVED_AT + timedelta(seconds=31)
    )
    future = _source(transport).observe_whole_account_positions(
        observed_at=OBSERVED_AT - timedelta(seconds=6)
    )

    assert _has(stale.blockers, B.SURFACE_SKEW)
    assert _has(future.blockers, B.SURFACE_FUTURE)


def test_source_threads_the_configured_read_timeout_to_both_portfolio_reads() -> None:
    transport = _RecordingTransport(inner=_transport())

    _source(transport, read_timeout=2.5).observe_whole_account_positions(observed_at=OBSERVED_AT)

    assert transport.seen_timeouts == [2.5, 2.5]


def test_source_rejects_naive_observation_instant() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _source(_transport()).observe_whole_account_positions(
            observed_at=datetime(2026, 1, 1, 0, 0)
        )


@pytest.mark.parametrize(
    "timeout",
    [0, -1.0, True, "5", float("nan"), float("inf"), float("-inf")],
)
def test_source_rejects_invalid_read_timeout(timeout: object) -> None:
    with pytest.raises(ValueError, match="read_timeout"):
        _source(_transport(), read_timeout=timeout)  # type: ignore[arg-type]


def test_source_rejects_a_non_dhan_broker_identity() -> None:
    with pytest.raises(ValueError, match="broker_id"):
        DhanWholeAccountPositionSource(
            account_id=ACCOUNT,
            connection_id=CONNECTION,
            instruments=_instruments((_instrument(), _ref())),
            broker_id="not-dhan",
        )


def test_source_rejects_a_transport_that_does_not_implement_the_boundary() -> None:
    with pytest.raises(ValueError, match="implement DhanTransport"):
        _source(object())  # type: ignore[arg-type]


def test_source_rejects_duplicate_broker_identity_before_auditing() -> None:
    instruments = _instruments(
        (_instrument(TCS, symbol="TCS", venue="NSE"), _ref()),
        (
            _instrument(InstrumentId("NSE", "TCS_ALT"), symbol="TCS_ALT", venue="NSE"),
            _ref(),
        ),
    )

    with pytest.raises(ValueError, match="duplicate broker identity"):
        _source(_transport(), instruments=instruments)


def test_source_rejects_empty_product_map_configuration() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        _source(_transport(), product_map={})
