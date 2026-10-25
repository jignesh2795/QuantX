"""Fail-closed Dhan whole-account position evidence (Slice C2b).

The C2b contract requires three complete surfaces (``POSITIONS``,
``HOLDINGS``, ``MARKS``), canonical instrument and product identity, signed
quantities, cost basis, usable marks, and an explicit cross-surface merge
policy. The verified DhanHQ v2 provider contracts do not establish those facts:

* ``/positions`` is documented as the day's open-position list including F&O
  carry-forward, but it carries no account/book timestamp, row count, or
  completeness marker;
* ``/holdings`` is documented as previous-session, T1 and delivered demat
  quantity without a product type, an observation timestamp, or a defined
  exposure-quantity basis (``totalQty`` versus ``availableQty`` versus
  ``collateralQty``);
* neither surface, and neither union, is documented as a complete
  whole-account exposure book for the requested trading day;
* the provider does not document whether a CNC position row and a holding row
  for the same instrument are independent exposures, the same exposure, or
  mutually exclusive settlement states;
* market quotes require a separately purchased Data API subscription and carry
  no server observation timestamp; the documented ``last_trade_time`` example
  is a 1980 sentinel and the field format is not defined.

The source therefore observes the two portfolio surfaces (read-only) to build
an auditable refusal, but it never emits unmarked canonical positions and never
returns ``COMPLETE``. It does not invent a product for holdings, a quantity
basis, a cross-surface merge, or a mark. Every reason is named in the book's
``blockers`` tuple so the C1 builder and operators can see exactly what is
missing. Querying a mark is deliberately out of scope: no entitlement is
assumed, and a synthetic mark cannot establish provider authority.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from quantx.domain.instruments import (
    DERIVATIVE_ASSET_CLASSES,
    Instrument,
)
from quantx.domain.risk_evidence import (
    EvidenceStatus,
    PositionSurface,
    PositionSurfaceEvidence,
    WholeAccountPositionEvidence,
)
from quantx.domain.value_objects import (
    AccountId,
    BrokerConnectionId,
    InstrumentId,
    ProductCode,
)

from .mapping import invert_dhan_product_map, normalize_dhan_product_map
from .models import (
    DhanHoldingSnapshot,
    DhanHoldingsSnapshot,
    DhanInstrumentRef,
    DhanPositionSnapshot,
    DhanPositionsSnapshot,
)
from .transport import DEFAULT_READ_TIMEOUT_SECONDS, DhanTransport

_SOURCE_VERSION = "dhan-whole-account-position-c2b-v1"
_SOURCE_PROVENANCE = "dhan-v2-portfolio-and-market-quote-contract-audit"
_POSITIONS_VERSION = "dhan-positions-v2"
_HOLDINGS_VERSION = "dhan-holdings-v2"
_MARKS_VERSION = "dhan-marketfeed-quote-v2"
_MERGE_POLICY = "dhan-no-cross-surface-merge-fail-closed-v1"
_MAX_SURFACE_SKEW = timedelta(seconds=30)
_MAX_FUTURE_SKEW = timedelta(seconds=5)
_BASE_CURRENCY = "INR"
_SUPPORTED_SEGMENTS = frozenset({"NSE_EQ", "BSE_EQ", "NSE_FNO", "BSE_FNO", "MCX_COMM"})
_SUPPORTED_HOLDING_EXCHANGES = frozenset({"ALL", "NSE", "BSE", "MCX"})


class DhanWholeAccountPositionBlocker(StrEnum):
    """Exact provider-semantic reasons a Dhan book cannot be complete."""

    POSITIONS_TIMESTAMP = "DHAN_POSITIONS_PROVIDER_TIMESTAMP_UNAVAILABLE"
    POSITIONS_SCOPE = "DHAN_POSITIONS_SCOPE_UNPROVEN"
    HOLDINGS_TIMESTAMP = "DHAN_HOLDINGS_PROVIDER_TIMESTAMP_UNAVAILABLE"
    HOLDINGS_SCOPE = "DHAN_HOLDINGS_SCOPE_UNPROVEN"
    HOLDINGS_PRODUCT_IDENTITY = "DHAN_HOLDINGS_PRODUCT_IDENTITY_UNPROVEN"
    HOLDINGS_EXPOSURE_QUANTITY = "DHAN_HOLDINGS_EXPOSURE_QUANTITY_UNPROVEN"
    CROSS_SURFACE_OVERLAP_POLICY = "DHAN_CROSS_SURFACE_OVERLAP_POLICY_UNPROVEN"
    MARK_AUTHORITY = "DHAN_MARK_AUTHORITY_UNAVAILABLE"
    MARK_TIMESTAMP = "DHAN_MARK_TRADE_TIMESTAMP_UNVERIFIED"
    TRANSPORT = "DHAN_TRANSPORT_NOT_CONFIGURED"
    PRODUCT_MAP = "DHAN_POSITION_PRODUCT_MAP_UNAVAILABLE"
    PRODUCT_MAP_AMBIGUOUS = "DHAN_POSITION_PRODUCT_MAP_AMBIGUOUS"
    POSITIONS_UNAVAILABLE = "DHAN_POSITIONS_UNAVAILABLE"
    HOLDINGS_UNAVAILABLE = "DHAN_HOLDINGS_UNAVAILABLE"
    POSITION_UNMAPPED = "DHAN_POSITION_INSTRUMENT_UNMAPPED"
    HOLDING_UNMAPPED = "DHAN_HOLDING_INSTRUMENT_UNMAPPED"
    HOLDING_AMBIGUOUS = "DHAN_HOLDING_INSTRUMENT_AMBIGUOUS"
    HOLDING_VENUE_IDENTITY = "DHAN_HOLDINGS_VENUE_IDENTITY_UNPROVEN"
    HOLDING_EXCHANGE = "DHAN_HOLDING_EXCHANGE_UNSUPPORTED"
    POSITION_DUPLICATE = "DHAN_POSITION_DUPLICATE_ROW"
    HOLDING_DUPLICATE = "DHAN_HOLDING_DUPLICATE_ROW"
    POSITION_PRODUCT_MISSING = "DHAN_POSITION_PRODUCT_MISSING"
    POSITION_PRODUCT_UNMAPPED = "DHAN_POSITION_PRODUCT_UNMAPPED"
    POSITION_TYPE = "DHAN_POSITION_TYPE_UNPROVEN"
    POSITION_SIGN = "DHAN_POSITION_TYPE_QUANTITY_INCONSISTENT"
    POSITION_COST_BASIS = "DHAN_POSITION_COST_BASIS_UNAVAILABLE"
    POSITION_MULTIPLIER = "DHAN_POSITION_MULTIPLIER_INCONSISTENT"
    POSITION_CURRENCY = "DHAN_POSITION_CURRENCY_UNSUPPORTED"
    POSITION_SEGMENT = "DHAN_POSITION_SEGMENT_UNSUPPORTED"
    POSITION_CROSS_CURRENCY = "DHAN_POSITION_CROSS_CURRENCY_UNSUPPORTED"
    DERIVATIVE_QUANTITY = "DHAN_DERIVATIVE_QUANTITY_BASIS_UNPROVEN"
    HOLDING_QUANTITY = "DHAN_HOLDING_QUANTITY_UNAVAILABLE"
    HOLDING_COST_BASIS = "DHAN_HOLDING_COST_BASIS_UNAVAILABLE"
    HOLDING_CURRENCY = "DHAN_HOLDING_CURRENCY_UNSUPPORTED"
    HOLDING_COLLATERAL = "DHAN_HOLDING_COLLATERAL_SEMANTICS_UNPROVEN"
    HOLDING_T1 = "DHAN_HOLDING_T1_SETTLEMENT_SEMANTICS_UNPROVEN"
    SURFACE_FUTURE = "DHAN_SURFACE_OBSERVATION_FUTURE_DATED"
    SURFACE_SKEW = "DHAN_SURFACE_OBSERVATION_SKEW_EXCEEDED"
    CROSS_SURFACE_OVERLAP = "DHAN_CROSS_SURFACE_OVERLAP"


_STATIC_BLOCKERS: tuple[DhanWholeAccountPositionBlocker, ...] = (
    DhanWholeAccountPositionBlocker.POSITIONS_TIMESTAMP,
    DhanWholeAccountPositionBlocker.POSITIONS_SCOPE,
    DhanWholeAccountPositionBlocker.HOLDINGS_TIMESTAMP,
    DhanWholeAccountPositionBlocker.HOLDINGS_SCOPE,
    DhanWholeAccountPositionBlocker.HOLDINGS_PRODUCT_IDENTITY,
    DhanWholeAccountPositionBlocker.HOLDINGS_EXPOSURE_QUANTITY,
    DhanWholeAccountPositionBlocker.CROSS_SURFACE_OVERLAP_POLICY,
    DhanWholeAccountPositionBlocker.MARK_AUTHORITY,
    DhanWholeAccountPositionBlocker.MARK_TIMESTAMP,
)


@dataclass(frozen=True, slots=True)
class DhanWholeAccountPositionSource:
    """Dhan-scoped source that can never claim a complete whole-account book.

    The source is account/connection bound and reuses the adapter's canonical
    instrument mapping. A configured ``product_map`` is an explicit
    neutral-to-Dhan map; the source inverts it to wire-to-neutral product
    identity for the position surface. It does not make the provider's
    holdings product, overlap, quantity, timestamp, or mark semantics complete,
    so the book still cannot be ``COMPLETE``.
    """

    account_id: AccountId
    connection_id: BrokerConnectionId
    instruments: Mapping[InstrumentId, tuple[Instrument, DhanInstrumentRef]]
    transport: DhanTransport | None = None
    product_map: Mapping[str, str] | None = None
    broker_id: str = "dhan"
    read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS
    version: str = _SOURCE_VERSION
    provenance: str = _SOURCE_PROVENANCE

    def __post_init__(self) -> None:
        if type(self.account_id) is not AccountId:
            raise ValueError("Dhan position source account_id must be AccountId")
        if type(self.connection_id) is not BrokerConnectionId:
            raise ValueError("Dhan position source connection_id must be BrokerConnectionId")
        if type(self.broker_id) is not str or self.broker_id != "dhan":
            raise ValueError("Dhan position source broker_id must be 'dhan'")
        if not isinstance(self.instruments, Mapping):
            raise ValueError("Dhan position source instruments must be a mapping")
        seen_references: set[tuple[str, str]] = set()
        for instrument_id, item in self.instruments.items():
            if type(instrument_id) is not InstrumentId:
                raise ValueError("Dhan position source keys must be InstrumentId values")
            if type(item) is not tuple or len(item) != 2:
                raise ValueError("Dhan position source instrument entries must be tuples")
            instrument, reference = item
            if type(instrument) is not Instrument or type(reference) is not DhanInstrumentRef:
                raise ValueError("Dhan position source instrument entries are malformed")
            broker_key = (reference.security_id, reference.exchange_segment)
            if broker_key in seen_references:
                raise ValueError(
                    "Dhan position source instrument map has duplicate broker identity"
                )
            seen_references.add(broker_key)
        if self.transport is not None and not isinstance(self.transport, DhanTransport):
            raise ValueError("Dhan position source transport must implement DhanTransport")
        if self.product_map is not None:
            object.__setattr__(self, "product_map", normalize_dhan_product_map(self.product_map))
        if (
            isinstance(self.read_timeout, bool)
            or not isinstance(self.read_timeout, (int, float))
            or not math.isfinite(self.read_timeout)
            or self.read_timeout <= 0
        ):
            raise ValueError("Dhan position source read_timeout must be a positive number")
        if type(self.version) is not str or not self.version.strip():
            raise ValueError("Dhan position source version is required")
        if type(self.provenance) is not str or not self.provenance.strip():
            raise ValueError("Dhan position source provenance is required")

    def observe_whole_account_positions(
        self,
        *,
        observed_at: datetime,
    ) -> WholeAccountPositionEvidence:
        """Observe portfolio surfaces and return an explicit refusal.

        No canonical ``LivePositionEvidence`` row is emitted because no
        authorized mark surface is consumed. Surface row counts still expose
        what the provider returned, and every unresolved semantic is named in
        ``blockers``.
        """
        _require_aware(observed_at, "Dhan position observation instant")
        blockers: list[str] = [blocker.value for blocker in _STATIC_BLOCKERS]
        if self.transport is None:
            blockers.append(DhanWholeAccountPositionBlocker.TRANSPORT.value)
        if self.product_map is None:
            blockers.append(DhanWholeAccountPositionBlocker.PRODUCT_MAP.value)

        positions_snapshot = self._read_positions(blockers)
        holdings_snapshot = self._read_holdings(blockers)
        if positions_snapshot is not None and not positions_snapshot.available:
            blockers.append(DhanWholeAccountPositionBlocker.POSITIONS_UNAVAILABLE.value)
        if holdings_snapshot is not None and not holdings_snapshot.available:
            blockers.append(DhanWholeAccountPositionBlocker.HOLDINGS_UNAVAILABLE.value)
        positions_available = positions_snapshot is not None and positions_snapshot.available
        holdings_available = holdings_snapshot is not None and holdings_snapshot.available

        inverse_products = self._inverse_products(blockers)
        positions_surface = self._positions_surface(
            positions_snapshot,
            observed_at=observed_at,
            available=positions_available,
        )
        holdings_surface = self._holdings_surface(
            holdings_snapshot,
            observed_at=observed_at,
            available=holdings_available,
        )
        marks_surface = PositionSurfaceEvidence(
            surface=PositionSurface.MARKS,
            status=EvidenceStatus.UNAVAILABLE,
            observed_at=observed_at,
            version=_MARKS_VERSION,
            provenance=(
                "no authorized Dhan mark observation in C2b; Data API "
                "subscription entitlement and provider trade-time format unverified"
            ),
            row_count=0,
        )

        active_instruments: set[str] = set()
        if positions_available and positions_snapshot is not None:
            active_instruments = self._audit_positions(
                positions_snapshot.positions,
                inverse_products=inverse_products,
                blockers=blockers,
            )
        holding_instruments: set[str] = set()
        if holdings_available and holdings_snapshot is not None:
            holding_instruments = self._audit_holdings(
                holdings_snapshot.holdings,
                blockers=blockers,
            )
        for instrument_id in sorted(active_instruments & holding_instruments):
            blockers.append(
                f"{DhanWholeAccountPositionBlocker.CROSS_SURFACE_OVERLAP.value}: {instrument_id}"
            )

        _require_surface_coherence(
            positions_surface,
            holdings_surface,
            observed_at=observed_at,
            blockers=blockers,
        )
        completeness = (
            EvidenceStatus.INCOMPLETE
            if positions_available or holdings_available
            else EvidenceStatus.UNAVAILABLE
        )
        return WholeAccountPositionEvidence(
            account_id=self.account_id,
            connection_id=self.connection_id,
            surfaces=(positions_surface, holdings_surface, marks_surface),
            positions=(),
            completeness=completeness,
            merge_policy=_MERGE_POLICY,
            observed_at=observed_at,
            version=self.version,
            provenance=self.provenance,
            blockers=_unique(blockers),
        )

    def _read_positions(
        self,
        blockers: list[str],
    ) -> DhanPositionsSnapshot | None:
        if self.transport is None:
            return None
        try:
            return self.transport.positions(timeout=self.read_timeout)
        except Exception as exc:  # noqa: BLE001 - classified below, no secret detail
            blockers.append(
                f"{DhanWholeAccountPositionBlocker.POSITIONS_UNAVAILABLE.value}: "
                f"{type(exc).__name__}"
            )
            return None

    def _read_holdings(
        self,
        blockers: list[str],
    ) -> DhanHoldingsSnapshot | None:
        if self.transport is None:
            return None
        try:
            return self.transport.holdings(timeout=self.read_timeout)
        except Exception as exc:  # noqa: BLE001 - classified below, no secret detail
            blockers.append(
                f"{DhanWholeAccountPositionBlocker.HOLDINGS_UNAVAILABLE.value}: "
                f"{type(exc).__name__}"
            )
            return None

    def _inverse_products(self, blockers: list[str]) -> Mapping[str, str] | None:
        if self.product_map is None:
            return None
        try:
            return invert_dhan_product_map(self.product_map)
        except ValueError:
            blockers.append(DhanWholeAccountPositionBlocker.PRODUCT_MAP_AMBIGUOUS.value)
            return None

    @staticmethod
    def _positions_surface(
        snapshot: DhanPositionsSnapshot | None,
        *,
        observed_at: datetime,
        available: bool,
    ) -> PositionSurfaceEvidence:
        if snapshot is None:
            return PositionSurfaceEvidence(
                surface=PositionSurface.POSITIONS,
                status=EvidenceStatus.UNAVAILABLE,
                observed_at=observed_at,
                version=_POSITIONS_VERSION,
                provenance="Dhan positions were not observed (no transport or read failure)",
                row_count=0,
            )
        if not available:
            return PositionSurfaceEvidence(
                surface=PositionSurface.POSITIONS,
                status=EvidenceStatus.UNAVAILABLE,
                observed_at=snapshot.observed_at,
                version=_POSITIONS_VERSION,
                provenance="Dhan positions response was unavailable or malformed",
                row_count=0,
            )
        return PositionSurfaceEvidence(
            surface=PositionSurface.POSITIONS,
            status=EvidenceStatus.INCOMPLETE,
            observed_at=snapshot.observed_at,
            version=_POSITIONS_VERSION,
            provenance=(
                "Dhan /positions parsed; provider supplies no book timestamp, row count, "
                "or completeness marker; local read instant only"
            ),
            row_count=len(snapshot.positions),
        )

    @staticmethod
    def _holdings_surface(
        snapshot: DhanHoldingsSnapshot | None,
        *,
        observed_at: datetime,
        available: bool,
    ) -> PositionSurfaceEvidence:
        if snapshot is None:
            return PositionSurfaceEvidence(
                surface=PositionSurface.HOLDINGS,
                status=EvidenceStatus.UNAVAILABLE,
                observed_at=observed_at,
                version=_HOLDINGS_VERSION,
                provenance="Dhan holdings were not observed (no transport or read failure)",
                row_count=0,
            )
        if not available:
            return PositionSurfaceEvidence(
                surface=PositionSurface.HOLDINGS,
                status=EvidenceStatus.UNAVAILABLE,
                observed_at=snapshot.observed_at,
                version=_HOLDINGS_VERSION,
                provenance="Dhan holdings response was unavailable or malformed",
                row_count=0,
            )
        return PositionSurfaceEvidence(
            surface=PositionSurface.HOLDINGS,
            status=EvidenceStatus.INCOMPLETE,
            observed_at=snapshot.observed_at,
            version=_HOLDINGS_VERSION,
            provenance=(
                "Dhan /holdings parsed; provider supplies no product, timestamp, "
                "or exposure-quantity basis; local read instant only"
            ),
            row_count=len(snapshot.holdings),
        )

    def _audit_positions(
        self,
        rows: tuple[DhanPositionSnapshot, ...],
        *,
        inverse_products: Mapping[str, str] | None,
        blockers: list[str],
    ) -> set[str]:
        reverse = self._reverse_instruments()
        seen: set[tuple[InstrumentId, ProductCode]] = set()
        active_instruments: set[str] = set()
        for row in rows:
            mapped = reverse.get((row.security_id, row.exchange_segment))
            if mapped is None:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.POSITION_UNMAPPED.value}: "
                    f"{row.security_id}/{row.exchange_segment}"
                )
                continue
            instrument_id, instrument = mapped
            if row.exchange_segment not in _SUPPORTED_SEGMENTS:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.POSITION_SEGMENT.value}: "
                    f"{row.exchange_segment}"
                )
            if instrument.currency != _BASE_CURRENCY:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.POSITION_CURRENCY.value}: {instrument_id}"
                )
            if row.cross_currency is True:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.POSITION_CROSS_CURRENCY.value}: "
                    f"{instrument_id}"
                )
            position_type = _position_type(row, instrument_id, blockers)
            if row.net_quantity == 0:
                if position_type in {"LONG", "SHORT"}:
                    blockers.append(
                        f"{DhanWholeAccountPositionBlocker.POSITION_SIGN.value}: "
                        f"{instrument_id} {position_type} has zero net quantity"
                    )
                continue
            if position_type == "CLOSED":
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.POSITION_SIGN.value}: "
                    f"{instrument_id} CLOSED has non-zero net quantity"
                )
            if position_type == "LONG" and row.net_quantity < 0:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.POSITION_SIGN.value}: "
                    f"{instrument_id} LONG has negative net quantity"
                )
            if position_type == "SHORT" and row.net_quantity > 0:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.POSITION_SIGN.value}: "
                    f"{instrument_id} SHORT has positive net quantity"
                )
            if row.average_price is None or row.average_price <= 0:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.POSITION_COST_BASIS.value}: {instrument_id}"
                )
            if row.multiplier is not None and row.multiplier != instrument.multiplier:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.POSITION_MULTIPLIER.value}: {instrument_id}"
                )
            if instrument.asset_class in DERIVATIVE_ASSET_CLASSES:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.DERIVATIVE_QUANTITY.value}: {instrument_id}"
                )
            active_instruments.add(instrument_id)
            product = self._position_product(row, instrument_id, inverse_products, blockers)
            if product is None:
                continue
            key = (instrument.instrument_id, product)
            if key in seen:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.POSITION_DUPLICATE.value}: "
                    f"{instrument_id}/{product.value}"
                )
            seen.add(key)
        return active_instruments

    def _audit_holdings(
        self,
        rows: tuple[DhanHoldingSnapshot, ...],
        *,
        blockers: list[str],
    ) -> set[str]:
        candidates = self._holding_candidates()
        seen: set[str] = set()
        holding_instruments: set[str] = set()
        for row in rows:
            exchange = row.exchange.strip().upper()
            if exchange not in _SUPPORTED_HOLDING_EXCHANGES:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.HOLDING_EXCHANGE.value}: {row.exchange}"
                )
                continue
            matching = candidates.get(row.security_id, ())
            if exchange == "ALL":
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.HOLDING_VENUE_IDENTITY.value}: "
                    f"{row.security_id}/{row.exchange}"
                )
            else:
                matching = tuple(
                    item for item in matching if item[2].exchange_segment.startswith(f"{exchange}_")
                )
            if not matching:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.HOLDING_UNMAPPED.value}: "
                    f"{row.security_id}/{row.exchange}"
                )
                continue
            if len(matching) != 1:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.HOLDING_AMBIGUOUS.value}: "
                    f"{row.security_id}/{row.exchange}"
                )
                continue
            instrument_id, instrument, _ = matching[0]
            if exchange != "ALL":
                holding_instruments.add(instrument_id)
            if instrument_id in seen:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.HOLDING_DUPLICATE.value}: "
                    f"{row.security_id}/{row.exchange}"
                )
            seen.add(instrument_id)
            if row.total_quantity is None or row.total_quantity <= 0:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.HOLDING_QUANTITY.value}: {instrument_id}"
                )
            if row.average_cost_price is None or row.average_cost_price <= 0:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.HOLDING_COST_BASIS.value}: {instrument_id}"
                )
            if instrument.currency != _BASE_CURRENCY:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.HOLDING_CURRENCY.value}: {instrument_id}"
                )
            if row.collateral_quantity is not None and row.collateral_quantity > 0:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.HOLDING_COLLATERAL.value}: {instrument_id}"
                )
            if row.t1_quantity is not None and row.t1_quantity > 0:
                blockers.append(
                    f"{DhanWholeAccountPositionBlocker.HOLDING_T1.value}: {instrument_id}"
                )
        return holding_instruments

    def _position_product(
        self,
        row: DhanPositionSnapshot,
        instrument_id: str,
        inverse_products: Mapping[str, str] | None,
        blockers: list[str],
    ) -> ProductCode | None:
        if row.product_type is None or not row.product_type.strip():
            blockers.append(
                f"{DhanWholeAccountPositionBlocker.POSITION_PRODUCT_MISSING.value}: {instrument_id}"
            )
            return None
        wire = row.product_type.strip().upper()
        if inverse_products is None:
            return None
        neutral = inverse_products.get(wire)
        if neutral is None:
            blockers.append(
                f"{DhanWholeAccountPositionBlocker.POSITION_PRODUCT_UNMAPPED.value}: "
                f"{instrument_id}/{wire}"
            )
            return None
        return ProductCode(neutral)

    def _reverse_instruments(
        self,
    ) -> dict[tuple[str, str], tuple[str, Instrument]]:
        return {
            (reference.security_id, reference.exchange_segment): (str(instrument_id), instrument)
            for instrument_id, (instrument, reference) in self.instruments.items()
        }

    def _holding_candidates(
        self,
    ) -> dict[str, tuple[tuple[str, Instrument, DhanInstrumentRef], ...]]:
        candidates: dict[str, list[tuple[str, Instrument, DhanInstrumentRef]]] = {}
        for instrument_id, (instrument, reference) in self.instruments.items():
            candidates.setdefault(reference.security_id, []).append(
                (str(instrument_id), instrument, reference)
            )
        return {key: tuple(value) for key, value in candidates.items()}


def _position_type(
    row: DhanPositionSnapshot,
    instrument_id: str,
    blockers: list[str],
) -> str | None:
    if row.position_type is None or not row.position_type.strip():
        blockers.append(f"{DhanWholeAccountPositionBlocker.POSITION_TYPE.value}: {instrument_id}")
        return None
    position_type = row.position_type.strip().upper()
    if position_type not in {"LONG", "SHORT", "CLOSED"}:
        blockers.append(
            f"{DhanWholeAccountPositionBlocker.POSITION_TYPE.value}: "
            f"{instrument_id}/{position_type}"
        )
        return None
    return position_type


def _require_surface_coherence(
    positions: PositionSurfaceEvidence,
    holdings: PositionSurfaceEvidence,
    *,
    observed_at: datetime,
    blockers: list[str],
) -> None:
    for surface in (positions, holdings):
        delta = surface.observed_at - observed_at
        if delta > _MAX_FUTURE_SKEW:
            blockers.append(
                f"{DhanWholeAccountPositionBlocker.SURFACE_FUTURE.value}: {surface.surface.value}"
            )
        elif abs(delta) > _MAX_SURFACE_SKEW:
            blockers.append(
                f"{DhanWholeAccountPositionBlocker.SURFACE_SKEW.value}: {surface.surface.value}"
            )


def _unique(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def _require_aware(value: datetime, name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime")


__all__ = [
    "DhanWholeAccountPositionBlocker",
    "DhanWholeAccountPositionSource",
]
