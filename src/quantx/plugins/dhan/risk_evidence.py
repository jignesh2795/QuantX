"""Dhan-backed LIVE risk evidence source.

The source maps four authenticated Dhan observations (profile, funds, positions
and holdings) onto the existing ``RiskContext``/``RiskSnapshot`` contracts. It is
deliberately conservative: missing, malformed, foreign, unavailable or
contradictory data stays unavailable and is never converted to zero, an empty
book, or a fabricated complete account.

The source is not an authority. Only
``quantx.application.live_risk.LiveRiskEvidenceAuthority`` binds these
observations to the configured account, connection, broker client and exact
transport, stamps the trusted capture instant, and mints admission. Dhan cannot
provide daily P&L, complete equity, a reliable high-water mark, or a
mark-to-market portfolio valuation from these endpoints, so the source declares
those fields unsupported and sanctioned LIVE admission remains unavailable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from quantx.application.live_risk import (
    LiveRiskEvidence,
    LiveRiskEvidenceField,
    LiveRiskEvidenceObservation,
)
from quantx.domain.accounts import AccountId, BrokerConnectionId
from quantx.domain.enums import OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instruments import Instrument
from quantx.domain.risk import RiskContext, RiskSnapshot
from quantx.domain.value_objects import Money

from .models import (
    DhanFundsSnapshot,
    DhanHoldingSnapshot,
    DhanHoldingsSnapshot,
    DhanInstrumentRef,
    DhanPositionSnapshot,
    DhanPositionsSnapshot,
    DhanProfileSnapshot,
)
from .transport import DEFAULT_READ_TIMEOUT_SECONDS, DhanTransport

_SOURCE_ID = "dhan-risk-evidence-v1"

_FINANCIAL_FIELDS: tuple[LiveRiskEvidenceField, ...] = (
    LiveRiskEvidenceField.CASH_BALANCE,
    LiveRiskEvidenceField.AVAILABLE_CASH,
    LiveRiskEvidenceField.BLOCKED_CASH,
    LiveRiskEvidenceField.MARGIN_USED,
    LiveRiskEvidenceField.MARGIN_AVAILABLE,
    LiveRiskEvidenceField.BUYING_POWER,
)

_EXPOSURE_FIELDS: tuple[LiveRiskEvidenceField, ...] = (
    LiveRiskEvidenceField.CURRENT_POSITION_EXPOSURE,
    LiveRiskEvidenceField.CURRENT_INSTRUMENT_EXPOSURE,
    LiveRiskEvidenceField.CURRENT_PORTFOLIO_EXPOSURE,
)

_UNSUPPORTED_FIELDS: tuple[LiveRiskEvidenceField, ...] = (
    LiveRiskEvidenceField.DAILY_PNL,
    LiveRiskEvidenceField.EQUITY,
    LiveRiskEvidenceField.HIGH_WATER_MARK,
)

_SUPPORTED_FIELDS: frozenset[LiveRiskEvidenceField] = frozenset(
    (*_FINANCIAL_FIELDS, *_EXPOSURE_FIELDS)
)

_ALL_FIELDS: tuple[LiveRiskEvidenceField, ...] = tuple(LiveRiskEvidenceField)


@dataclass(frozen=True, slots=True)
class DhanRiskEvidenceSource:
    """Collect one Dhan risk-evidence candidate for an approved request.

    ``instruments`` carries the exact canonical instrument and broker reference
    pairs the deployment registered. The source refuses an ambiguous mapping:
    two instruments sharing a position key or a holding security id cannot be
    distinguished from a holdings row, so the source is not built at all.
    """

    transport: DhanTransport
    account_id: AccountId
    broker_connection_id: BrokerConnectionId
    broker_client_id: str
    instruments: tuple[tuple[Instrument, DhanInstrumentRef], ...]
    read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if not isinstance(self.transport, DhanTransport):
            raise ValueError("Dhan risk evidence requires a DhanTransport")
        if type(self.account_id) is not AccountId:
            raise ValueError("Dhan risk evidence requires an AccountId")
        if type(self.broker_connection_id) is not BrokerConnectionId:
            raise ValueError("Dhan risk evidence requires a BrokerConnectionId")
        if type(self.broker_client_id) is not str or not self.broker_client_id.strip():
            raise ValueError("Dhan risk evidence requires a non-empty broker client id")
        object.__setattr__(self, "broker_client_id", self.broker_client_id.strip())
        if not self.instruments:
            raise ValueError("Dhan risk evidence requires at least one instrument")
        if isinstance(self.read_timeout, bool) or not isinstance(self.read_timeout, (int, float)):
            raise ValueError("Dhan risk evidence read timeout must be a positive number")
        if self.read_timeout <= 0:
            raise ValueError("Dhan risk evidence read timeout must be a positive number")

        instrument_ids: set[object] = set()
        position_keys: set[tuple[str, str]] = set()
        holding_security_ids: set[str] = set()
        for pair in self.instruments:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError("Dhan risk evidence instruments must be (Instrument, ref) pairs")
            instrument, instrument_ref = pair
            if type(instrument) is not Instrument:
                raise ValueError("Dhan risk evidence instruments must be canonical instruments")
            if type(instrument_ref) is not DhanInstrumentRef:
                raise ValueError("Dhan risk evidence instruments require Dhan references")
            if instrument.instrument_id in instrument_ids:
                raise ValueError("Dhan risk evidence instruments contain a duplicate id")
            instrument_ids.add(instrument.instrument_id)
            position_key = (instrument_ref.security_id, instrument_ref.exchange_segment)
            if position_key in position_keys:
                raise ValueError("Dhan risk evidence instruments contain an ambiguous position")
            position_keys.add(position_key)
            if instrument_ref.security_id in holding_security_ids:
                raise ValueError("Dhan risk evidence instruments contain an ambiguous holding")
            holding_security_ids.add(instrument_ref.security_id)

    @property
    def source_id(self) -> str:
        return _SOURCE_ID

    @property
    def supported_fields(self) -> frozenset[LiveRiskEvidenceField]:
        return _SUPPORTED_FIELDS

    def collect(self, request: ApprovedExecutionRequest) -> LiveRiskEvidence:
        """Collect and map evidence; every failure path stays unavailable."""
        profile = self._read_profile()
        if profile is None or not profile.available or profile.client_id is None:
            return self._unavailable_evidence(
                identity_observed_at=profile.observed_at if profile is not None else None,
                message="Dhan profile identity is unavailable",
            )
        if profile.client_id != self.broker_client_id:
            return self._unavailable_evidence(
                identity_observed_at=profile.observed_at,
                broker_client_id=profile.client_id,
                message="Dhan profile identity does not match the configured client",
            )

        instrument = self._instrument_for(request)
        if instrument is None:
            return self._unavailable_evidence(
                identity_observed_at=profile.observed_at,
                broker_client_id=profile.client_id,
                message="request instrument has no configured Dhan reference",
            )

        funds = self._read_funds()
        positions = self._read_positions()
        holdings = self._read_holdings()

        observations: dict[LiveRiskEvidenceField, LiveRiskEvidenceObservation] = {}
        unavailable: set[LiveRiskEvidenceField] = set(_UNSUPPORTED_FIELDS)
        contradictions: list[str] = []

        financial_state = self._financial_state(funds, observations, unavailable, contradictions)
        exposure = self._exposures(
            request,
            instrument,
            positions,
            holdings,
            observations,
            unavailable,
            contradictions,
        )

        context = None
        if financial_state is not None:
            context = RiskContext(
                instrument=instrument,
                financial_state=financial_state,
                reference_price=_reference_price(request),
                product=request.product,
                effective_position_effect=request.effective_position_effect,
                market_pack_id=request.execution_context.market_pack_id,
                rule_version=request.execution_context.rule_version,
                instrument_resolution=request.instrument_resolution,
                account_id=self.account_id,
                portfolio_id=request.execution_context.portfolio_id,
                broker_connection_id=self.broker_connection_id,
            )

        snapshot = None
        if context is not None:
            snapshot = RiskSnapshot(
                observed_at=_oldest_instant(observations, profile.observed_at),
                current_position_exposure=exposure.position,
                current_instrument_exposure=exposure.instrument,
                current_portfolio_exposure=exposure.portfolio,
                available_margin=context.financial_state.margin_available.amount,
                required_margin=request.required_margin,
                daily_pnl=None,
                equity=None,
                high_water_mark=None,
                account_id=self.account_id,
                portfolio_id=request.execution_context.portfolio_id,
                broker_connection_id=self.broker_connection_id,
            )

        return LiveRiskEvidence(
            source_id=_SOURCE_ID,
            broker_client_id=profile.client_id,
            account_id=self.account_id,
            broker_connection_id=self.broker_connection_id,
            transport=self.transport,
            identity_observed_at=profile.observed_at,
            context=context,
            snapshot=snapshot,
            observations=observations,
            reference_price=_reference_price(request),
            unavailable_fields=tuple(field for field in _ALL_FIELDS if field in unavailable),
            contradictions=tuple(contradictions),
            message="Dhan risk evidence collected",
        )

    def _read_profile(self) -> DhanProfileSnapshot | None:
        try:
            return self.transport.profile(timeout=self.read_timeout)
        except Exception:
            return None

    def _read_funds(self) -> DhanFundsSnapshot | None:
        try:
            return self.transport.fund_limits(timeout=self.read_timeout)
        except Exception:
            return None

    def _read_positions(self) -> DhanPositionsSnapshot | None:
        try:
            return self.transport.positions(timeout=self.read_timeout)
        except Exception:
            return None

    def _read_holdings(self) -> DhanHoldingsSnapshot | None:
        try:
            return self.transport.holdings(timeout=self.read_timeout)
        except Exception:
            return None

    def _instrument_for(self, request: ApprovedExecutionRequest) -> Instrument | None:
        for instrument, _ in self.instruments:
            if instrument.instrument_id == request.order.instrument:
                return instrument
        return None

    def _financial_state(
        self,
        funds: DhanFundsSnapshot | None,
        observations: dict[LiveRiskEvidenceField, LiveRiskEvidenceObservation],
        unavailable: set[LiveRiskEvidenceField],
        contradictions: list[str],
    ) -> AccountFinancialState | None:
        if funds is None or not funds.available:
            unavailable.update(_FINANCIAL_FIELDS)
            return None
        if funds.client_id is not None and funds.client_id != self.broker_client_id:
            contradictions.append("funds client identity mismatch")
            unavailable.update(_FINANCIAL_FIELDS)
            return None

        values: dict[LiveRiskEvidenceField, Decimal | None] = {
            LiveRiskEvidenceField.CASH_BALANCE: funds.sod_limit,
            LiveRiskEvidenceField.AVAILABLE_CASH: funds.available_balance,
            LiveRiskEvidenceField.BLOCKED_CASH: funds.blocked_payout_amount,
            LiveRiskEvidenceField.MARGIN_USED: funds.utilized_amount,
            LiveRiskEvidenceField.MARGIN_AVAILABLE: funds.available_balance,
            LiveRiskEvidenceField.BUYING_POWER: funds.available_balance,
        }
        for evidence_field, value in values.items():
            if value is None or not _usable_money(value):
                unavailable.add(evidence_field)
            else:
                observations[evidence_field] = LiveRiskEvidenceObservation(value, funds.observed_at)
        if any(evidence_field in unavailable for evidence_field in _FINANCIAL_FIELDS):
            # ``AccountFinancialState`` needs all six values. Partial fund
            # observations are not an account state, so none of them is
            # retained as usable evidence.
            for evidence_field in _FINANCIAL_FIELDS:
                observations.pop(evidence_field, None)
                unavailable.add(evidence_field)
            return None

        currency = "INR"
        return AccountFinancialState(
            capital_source=CapitalSourceType.LIVE_BROKER,
            cash_balance=_money(funds.sod_limit, currency),
            available_cash=_money(funds.available_balance, currency),
            blocked_cash=_money(funds.blocked_payout_amount, currency),
            margin_used=_money(funds.utilized_amount, currency),
            margin_available=_money(funds.available_balance, currency),
            buying_power=_money(funds.available_balance, currency),
        )

    def _exposures(
        self,
        request: ApprovedExecutionRequest,
        instrument: Instrument,
        positions: DhanPositionsSnapshot | None,
        holdings: DhanHoldingsSnapshot | None,
        observations: dict[LiveRiskEvidenceField, LiveRiskEvidenceObservation],
        unavailable: set[LiveRiskEvidenceField],
        contradictions: list[str],
    ) -> _Exposures:
        if positions is None or not positions.available:
            unavailable.update(_EXPOSURE_FIELDS)
            return _Exposures(None, None, None)
        if holdings is None or not holdings.available:
            unavailable.update(_EXPOSURE_FIELDS)
            return _Exposures(None, None, None)

        position_map, holding_map = self._reverse_maps()
        for position in positions.positions:
            if position.client_id is not None and position.client_id != self.broker_client_id:
                contradictions.append("position client identity mismatch")
            if (
                position.buy_quantity is not None
                and position.sell_quantity is not None
                and position.net_quantity != position.buy_quantity - position.sell_quantity
            ):
                contradictions.append("position quantity contradiction")
        for holding in holdings.holdings:
            if (
                holding.dp_quantity is not None
                and holding.t1_quantity is not None
                and holding.total_quantity != holding.dp_quantity + holding.t1_quantity
            ):
                contradictions.append("holding quantity contradiction")
            if (
                holding.available_quantity is not None
                and holding.available_quantity > holding.total_quantity
            ):
                contradictions.append("holding available quantity contradiction")
            if (
                holding.collateral_quantity is not None
                and holding.collateral_quantity > holding.total_quantity
            ):
                contradictions.append("holding collateral quantity contradiction")

        requested = self._requested_exposure(
            instrument, positions, holdings, position_map, holding_map
        )
        portfolio = self._portfolio_exposure(positions, holdings, position_map, holding_map)
        observed_at = min(positions.observed_at, holdings.observed_at)
        if requested is None:
            unavailable.add(LiveRiskEvidenceField.CURRENT_POSITION_EXPOSURE)
            unavailable.add(LiveRiskEvidenceField.CURRENT_INSTRUMENT_EXPOSURE)
        else:
            observations[LiveRiskEvidenceField.CURRENT_POSITION_EXPOSURE] = (
                LiveRiskEvidenceObservation(requested, observed_at)
            )
            observations[LiveRiskEvidenceField.CURRENT_INSTRUMENT_EXPOSURE] = (
                LiveRiskEvidenceObservation(requested, observed_at)
            )
        if portfolio is None:
            unavailable.add(LiveRiskEvidenceField.CURRENT_PORTFOLIO_EXPOSURE)
        else:
            observations[LiveRiskEvidenceField.CURRENT_PORTFOLIO_EXPOSURE] = (
                LiveRiskEvidenceObservation(portfolio, observed_at)
            )
        return _Exposures(requested, requested, portfolio)

    def _reverse_maps(
        self,
    ) -> tuple[dict[tuple[str, str], Instrument], dict[str, Instrument]]:
        position_map: dict[tuple[str, str], Instrument] = {}
        holding_map: dict[str, Instrument] = {}
        for instrument, instrument_ref in self.instruments:
            position_map[(instrument_ref.security_id, instrument_ref.exchange_segment)] = instrument
            holding_map[instrument_ref.security_id] = instrument
        return position_map, holding_map

    def _requested_exposure(
        self,
        instrument: Instrument,
        positions: DhanPositionsSnapshot,
        holdings: DhanHoldingsSnapshot,
        position_map: Mapping[tuple[str, str], Instrument],
        holding_map: Mapping[str, Instrument],
    ) -> Decimal | None:
        position_value = Decimal("0")
        for position in positions.positions:
            if position_map.get((position.security_id, position.exchange_segment)) != instrument:
                continue
            value = _position_value(position, instrument)
            if value is None:
                return None
            position_value += value
        holding_value = Decimal("0")
        for holding in holdings.holdings:
            if holding_map.get(holding.security_id) != instrument:
                continue
            value = _holding_value(holding, instrument)
            if value is None:
                return None
            holding_value += value
        return position_value + holding_value

    def _portfolio_exposure(
        self,
        positions: DhanPositionsSnapshot,
        holdings: DhanHoldingsSnapshot,
        position_map: Mapping[tuple[str, str], Instrument],
        holding_map: Mapping[str, Instrument],
    ) -> Decimal | None:
        total = Decimal("0")
        for position in positions.positions:
            mapped = position_map.get((position.security_id, position.exchange_segment))
            if mapped is None:
                if position.net_quantity != 0:
                    return None
                continue
            value = _position_value(position, mapped)
            if value is None:
                return None
            total += value
        for holding in holdings.holdings:
            mapped = holding_map.get(holding.security_id)
            if mapped is None:
                if holding.total_quantity != 0:
                    return None
                continue
            value = _holding_value(holding, mapped)
            if value is None:
                return None
            total += value
        return total

    def _unavailable_evidence(
        self,
        *,
        identity_observed_at: datetime | None,
        broker_client_id: str | None = None,
        message: str,
    ) -> LiveRiskEvidence:
        return LiveRiskEvidence(
            source_id=_SOURCE_ID,
            broker_client_id=broker_client_id,
            account_id=self.account_id,
            broker_connection_id=self.broker_connection_id,
            transport=self.transport,
            identity_observed_at=identity_observed_at,
            context=None,
            snapshot=None,
            observations={},
            unavailable_fields=_ALL_FIELDS,
            message=message,
        )


@dataclass(frozen=True, slots=True)
class _Exposures:
    position: Decimal | None
    instrument: Decimal | None
    portfolio: Decimal | None


def _reference_price(request: ApprovedExecutionRequest) -> Decimal | None:
    order = request.order
    if order.order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT}:
        return order.limit_price
    return None


def _usable_money(value: Decimal | None) -> bool:
    return type(value) is Decimal and value.is_finite() and value >= 0


def _money(value: Decimal | None, currency: str) -> Money:
    if value is None:  # pragma: no cover - guarded by the caller's completeness check
        raise ValueError("money value is unavailable")
    return Money(value, currency)


def _position_value(position: DhanPositionSnapshot, instrument: Instrument) -> Decimal | None:
    if position.net_quantity == 0:
        return Decimal("0")
    average_price = position.average_price
    if average_price is None or not _usable_money(average_price):
        return None
    multiplier = position.multiplier if position.multiplier is not None else instrument.multiplier
    if multiplier is None or not _usable_money(multiplier) or multiplier == 0:
        return None
    return position.net_quantity * average_price * multiplier


def _holding_value(holding: DhanHoldingSnapshot, instrument: Instrument) -> Decimal | None:
    if holding.total_quantity == 0:
        return Decimal("0")
    average_cost_price = holding.average_cost_price
    if average_cost_price is None or not _usable_money(average_cost_price):
        return None
    return holding.total_quantity * average_cost_price * instrument.multiplier


def _oldest_instant(
    observations: Mapping[LiveRiskEvidenceField, LiveRiskEvidenceObservation],
    identity_observed_at: datetime,
) -> datetime:
    instants = [observation.observed_at for observation in observations.values()]
    instants.append(identity_observed_at)
    return min(instants)


def build_dhan_risk_evidence_source(
    *,
    transport: DhanTransport,
    account_id: AccountId,
    broker_connection_id: BrokerConnectionId,
    broker_client_id: str,
    instruments: tuple[tuple[Instrument, DhanInstrumentRef], ...],
    read_timeout: float = DEFAULT_READ_TIMEOUT_SECONDS,
) -> DhanRiskEvidenceSource:
    """Build the Dhan source from explicit deployment identity inputs."""
    return DhanRiskEvidenceSource(
        transport=transport,
        account_id=account_id,
        broker_connection_id=broker_connection_id,
        broker_client_id=broker_client_id,
        instruments=instruments,
        read_timeout=read_timeout,
    )


__all__ = ["DhanRiskEvidenceSource", "build_dhan_risk_evidence_source"]
