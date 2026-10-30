"""Pre-trade risk evaluation for TradeIntent objects.

The first implementation deliberately evaluates only deterministic domain
constraints. Execution-time and post-trade risk can be layered on later.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from .accounts import AccountId, BrokerConnectionId
from .constraints import (
    ConstraintDecision,
    ConstraintResult,
    TradeConstraintInput,
    evaluate_broker_constraint,
    evaluate_capital,
)
from .deployment import PortfolioId
from .enums import OrderSide, PositionEffect
from .errors import ValidationError
from .finance import AccountFinancialState, BrokerConstraint
from .instrument_registry import InstrumentResolution
from .instruments import DERIVATIVE_ASSET_CLASSES, Contract, Instrument
from .order_intents import TradeIntent
from .value_objects import Money, ProductCode, Quantity


class RiskDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    APPROVAL_REQUIRED = "approval_required"


class LiveRiskLimitsError(ValidationError):
    """Raised when LIVE risk limits omit or misdeclare a mandatory field."""


@dataclass(frozen=True, slots=True)
class RiskContext:
    """Inputs one risk evaluation may depend on.

    ``product``, ``effective_position_effect``, ``market_pack_id`` and
    ``rule_version`` carry the *already resolved* pre-approval semantics. Risk
    never resolves them itself and never falls back to instrument identity;
    it validates that the supplied resolution is internally coherent.

    ``instrument_resolution`` is the one point-in-time claim that binds the
    instrument facts, the derivative contract, the selected instrument-rule
    version and the contract metadata version/provenance. Risk consumes that
    claim as a whole instead of a bare contract value, so the identity it
    approved is exactly the identity the approved request and its fingerprint
    retain. A derivative evaluation requires it; a non-derivative evaluation
    may omit it and then never carries contract metadata.
    """

    instrument: Instrument
    financial_state: AccountFinancialState
    broker_constraints: tuple[BrokerConstraint, ...] = ()
    reference_price: Decimal | None = None
    product: ProductCode | None = None
    effective_position_effect: PositionEffect | None = None
    market_pack_id: str | None = None
    rule_version: str | None = None
    instrument_resolution: InstrumentResolution | None = None
    account_id: AccountId | None = None
    portfolio_id: PortfolioId | None = None
    broker_connection_id: BrokerConnectionId | None = None

    def __post_init__(self) -> None:
        if self.instrument_resolution is not None and not isinstance(
            self.instrument_resolution, InstrumentResolution
        ):
            raise ValueError("risk context resolution must be a canonical instrument resolution")

    @property
    def contract(self) -> Contract | None:
        """The resolved derivative contract, read-only from the resolution.

        Derived, never independently writable: the resolution stays the single
        source of truth for the selected contract and its version.
        """
        if self.instrument_resolution is None:
            return None
        return self.instrument_resolution.contract


@dataclass(frozen=True, slots=True)
class RiskResult:
    """One risk outcome, bound to the resolution it evaluated.

    ``instrument_resolution`` is the exact resolution the engine consumed, so
    an approved request can prove it retains the semantics that were risk
    approved instead of merely an equal-looking contract value.
    """

    decision: RiskDecision
    reason: str
    constraints: tuple[ConstraintDecision, ...] = ()
    instrument_resolution: InstrumentResolution | None = None

    def __post_init__(self) -> None:
        if self.instrument_resolution is not None and not isinstance(
            self.instrument_resolution, InstrumentResolution
        ):
            raise ValueError("risk result resolution must be a canonical instrument resolution")


def _risk_result(
    context: RiskContext,
    decision: RiskDecision,
    reason: str,
    constraints: tuple[ConstraintDecision, ...] = (),
) -> RiskResult:
    """Return a result carrying the exact resolution this evaluation consumed."""
    return RiskResult(decision, reason, constraints, context.instrument_resolution)


def _risk_number(value: object) -> Decimal | None:
    """Return a finite Decimal for explicit numeric config/state, else None.

    Booleans, floats, strings, and non-finite Decimals are never valid risk
    numbers: callers fail closed instead of coercing them.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, int):
        return Decimal(value)
    return None


@dataclass(frozen=True, slots=True)
class RiskLimits:
    """Explicit immutable LIVE risk ceilings; ``None`` disables one check.

    All limits are non-negative Decimals (ints accepted). Ratio limits live
    in ``[0, 1]``. ``max_snapshot_age`` bounds snapshot freshness when set.
    """

    max_order_notional: Decimal | None = None
    max_position_notional: Decimal | None = None
    max_portfolio_exposure: Decimal | None = None
    max_instrument_concentration: Decimal | None = None
    max_daily_loss: Decimal | None = None
    max_drawdown: Decimal | None = None
    max_snapshot_age: timedelta | None = None

    def __post_init__(self) -> None:
        for name in (
            "max_order_notional",
            "max_position_notional",
            "max_portfolio_exposure",
            "max_daily_loss",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            number = _risk_number(value)
            if number is None or number < 0:
                raise ValueError(f"{name} must be a non-negative number")
        for name in ("max_instrument_concentration", "max_drawdown"):
            value = getattr(self, name)
            if value is None:
                continue
            number = _risk_number(value)
            if number is None or number < 0 or number > 1:
                raise ValueError(f"{name} must be a ratio in [0, 1]")
        if self.max_snapshot_age is not None and self.max_snapshot_age < timedelta(0):
            raise ValueError("max_snapshot_age must not be negative")


_LIVE_REQUIRED_MONEY_FIELDS = (
    "max_order_notional",
    "max_position_notional",
    "max_daily_loss",
)


def require_live_risk_limits(limits: RiskLimits) -> RiskLimits:
    """Return a validated copy of limits for LIVE use.

    LIVE requires explicit, strictly positive values for order notional,
    position notional, daily loss and snapshot age. Validation is exact:
    booleans, ints, floats, strings, subclasses and non-finite Decimals are
    rejected without coercion. The returned copy isolates the caller from
    later mutation of the source object.
    """
    if type(limits) is not RiskLimits:
        raise LiveRiskLimitsError("LIVE risk limits must be a RiskLimits")
    invalid: list[str] = []
    for name in _LIVE_REQUIRED_MONEY_FIELDS:
        value = getattr(limits, name)
        if type(value) is not Decimal or not value.is_finite() or value <= 0:
            invalid.append(name)
    age = limits.max_snapshot_age
    if type(age) is not timedelta or age <= timedelta(0):
        invalid.append("max_snapshot_age")
    if invalid:
        raise LiveRiskLimitsError(
            "LIVE risk limits require explicit valid values for: " + ", ".join(invalid)
        )
    return replace(limits)


@dataclass(frozen=True, slots=True)
class RiskSnapshot:
    """Explicit immutable risk state supplied by the caller for one evaluation.

    The engine never reads brokers or clocks; freshness is judged against an
    explicit ``evaluated_at``. Exposures are signed net notionals (negative
    means net short). ``None`` means unavailable, which fails closed whenever
    an enabled check needs the field. Non-finite values are rejected by the
    engine rather than normalized.
    """

    observed_at: datetime
    current_position_exposure: Decimal | None = None
    current_instrument_exposure: Decimal | None = None
    current_portfolio_exposure: Decimal | None = None
    available_margin: Decimal | None = None
    required_margin: Decimal | None = None
    daily_pnl: Decimal | None = None
    equity: Decimal | None = None
    high_water_mark: Decimal | None = None
    account_id: AccountId | None = None
    portfolio_id: PortfolioId | None = None
    broker_connection_id: BrokerConnectionId | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")


def _order_value(intent: TradeIntent, context: RiskContext) -> Decimal | None:
    """Deterministic unsigned order notional shared by every risk check."""
    if intent.estimated_order_value is not None:
        return intent.estimated_order_value
    if context.reference_price is None:
        return None
    return intent.quantity * context.reference_price * context.instrument.multiplier


def _resolution_violation(intent: TradeIntent, context: RiskContext) -> str | None:
    """Reject incoherent resolved semantics without inventing a fallback.

    Only supplied resolution is checked. A caller that supplies no product or
    effective effect is not asserting a resolution, so the legacy
    resolution-less risk context is unchanged. An absent position effect may
    only resolve through a documented, versioned market-pack rule: to OPEN,
    with the rule identity
    supplied, or to no effective effect at all.

    The instrument resolution is validated as one identity, not as a contract
    value: the resolved instrument must be both the intent instrument and the
    risk instrument, a derivative must carry a complete canonical contract
    with its metadata version and provenance, a non-derivative must carry no
    contract metadata at all, and a derivative without a resolution fails
    closed.
    """
    if context.instrument.instrument_id != intent.instrument:
        return "risk context instrument does not match the intent instrument"
    resolution = context.instrument_resolution
    if resolution is not None:
        if resolution.instrument.instrument_id != intent.instrument:
            return "resolved instrument does not match the intent instrument"
        if resolution.instrument != context.instrument:
            return "resolved instrument does not match the risk context instrument"
    if context.product is not None:
        if intent.product is not None and intent.product != context.product:
            return "resolved product does not match the intent product"
        if not (context.market_pack_id or "").strip():
            return "a resolved product requires a market-pack id"
        if not (context.rule_version or "").strip():
            return "a resolved product requires a market-pack rule version"
    if context.instrument.asset_class in DERIVATIVE_ASSET_CLASSES:
        if resolution is None:
            return "a derivative instrument requires a resolved instrument resolution"
        contract = resolution.contract
        if contract is None:
            return "a derivative instrument resolution requires canonical contract metadata"
        if contract.instrument_id != context.instrument.instrument_id:
            return "resolved contract instrument does not match the risk instrument"
        if contract.asset_class is not context.instrument.asset_class:
            return "resolved contract asset class does not match the risk instrument"
        if not (resolution.instrument_rule_version or "").strip():
            return "a derivative instrument resolution requires an instrument rule version"
        if resolution.instrument_rule_effective_from > resolution.resolved_at:
            return "the resolved instrument rule is not effective at the resolution instant"
        if not (resolution.contract_metadata_version or "").strip():
            return "a derivative instrument resolution requires a contract metadata version"
        if not (resolution.contract_source or "").strip():
            return "a derivative instrument resolution requires contract metadata provenance"
        if resolution.contract_effective_from is None:
            return "a derivative instrument resolution requires a contract effective instant"
        if resolution.contract_effective_from > resolution.resolved_at:
            return "the resolved contract metadata is not effective at the resolution instant"
    elif resolution is not None:
        if resolution.contract is not None:
            return "a non-derivative instrument cannot carry contract metadata"
        if (
            resolution.contract_metadata_version is not None
            or resolution.contract_source is not None
            or resolution.contract_effective_from is not None
        ):
            return "a non-derivative instrument resolution cannot carry contract provenance"
    if context.effective_position_effect is not None:
        if context.effective_position_effect not in {
            PositionEffect.OPEN,
            PositionEffect.CLOSE,
        }:
            return "a resolved effective position effect must be OPEN or CLOSE"
        if intent.position_effect is PositionEffect.OPEN:
            return "an explicit OPEN request cannot carry a resolved effective effect"
        if intent.position_effect is None:
            if context.effective_position_effect is not PositionEffect.OPEN:
                return "an absent position effect may only resolve to OPEN"
            if not (context.market_pack_id or "").strip():
                return "an absent position effect resolved to OPEN requires a market-pack id"
            if not (context.rule_version or "").strip():
                return (
                    "an absent position effect resolved to OPEN requires a market-pack rule version"
                )
        if (
            intent.position_effect is PositionEffect.CLOSE
            and context.effective_position_effect is not PositionEffect.CLOSE
        ):
            return "CLOSE position effect cannot resolve to OPEN"
    return None


class PreTradeRiskEngine:
    """Evaluate whether a TradeIntent may proceed to order construction."""

    def evaluate(self, intent: TradeIntent, context: RiskContext) -> RiskResult:
        if intent.execution_context is None:
            return _risk_result(context, RiskDecision.REJECT, "execution context is required")

        resolution_violation = _resolution_violation(intent, context)
        if resolution_violation is not None:
            return _risk_result(
                context,
                RiskDecision.REJECT,
                f"RISK_STATE_INCONSISTENT: {resolution_violation}",
            )

        required_margin = Money(
            intent.required_margin,
            context.financial_state.margin_available.currency,
        )
        decisions: list[ConstraintDecision] = [
            evaluate_capital(context.financial_state, required_margin)
        ]
        if decisions[-1].result is ConstraintResult.REJECT:
            return _risk_result(
                context, RiskDecision.REJECT, decisions[-1].reason, tuple(decisions)
            )

        order_value = _order_value(intent, context)
        if order_value is None:
            return _risk_result(
                context,
                RiskDecision.REJECT,
                "order value cannot be determined without estimated value or reference price",
                tuple(decisions),
            )

        money_order_value = Money(order_value, context.financial_state.available_cash.currency)
        trade_input = TradeConstraintInput(
            order_value=money_order_value,
            quantity=Quantity(intent.quantity),
            required_margin=required_margin,
            approval_required=intent.approval_required,
        )

        for constraint in context.broker_constraints:
            decision = evaluate_broker_constraint(constraint, trade_input)
            decisions.append(decision)
            if decision.result is ConstraintResult.REJECT:
                return _risk_result(context, RiskDecision.REJECT, decision.reason, tuple(decisions))

        if intent.approval_required or any(
            decision.result is ConstraintResult.REQUIRES_APPROVAL for decision in decisions
        ):
            return _risk_result(
                context,
                RiskDecision.APPROVAL_REQUIRED,
                "explicit approval is required before execution",
                tuple(decisions),
            )

        return _risk_result(
            context,
            RiskDecision.APPROVE,
            "pre-trade risk checks passed",
            tuple(decisions),
        )

    def evaluate_with_limits(
        self,
        intent: TradeIntent,
        context: RiskContext,
        *,
        limits: RiskLimits,
        snapshot: RiskSnapshot | None,
        evaluated_at: datetime,
    ) -> RiskResult:
        """Authoritative deterministic LIVE evaluation against explicit limits.

        Runs the existing base checks first, then every configured R1-A limit
        in a fixed order, collecting all violations. Any non-APPROVE outcome
        means REJECT: the order must not reach gate/reservation. Reasons carry
        stable ``CODE: detail`` prefixes in evaluation order. No clocks, no
        broker calls, no receipts; the caller supplies snapshot and timestamp.
        """
        if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
            return _risk_result(
                context,
                RiskDecision.REJECT,
                "RISK_VALUE_INVALID: evaluated_at must be timezone-aware",
            )
        if snapshot is None:
            return _risk_result(
                context,
                RiskDecision.REJECT,
                "RISK_SNAPSHOT_MISSING: risk snapshot is required for limit enforcement",
            )

        violations: list[str] = []
        decisions: list[ConstraintDecision] = []

        if limits.max_snapshot_age is not None:
            age = evaluated_at - snapshot.observed_at
            if age < timedelta(0):
                violations.append("RISK_STATE_INCONSISTENT: risk snapshot is future-dated")
            elif age > limits.max_snapshot_age:
                violations.append(
                    f"RISK_SNAPSHOT_STALE: snapshot age {age} exceeds maximum "
                    f"{limits.max_snapshot_age}"
                )
            decisions.append(
                ConstraintDecision(
                    ConstraintResult.PASS if not violations else ConstraintResult.REJECT,
                    "snapshot_freshness",
                    violations[-1] if violations else "snapshot is fresh",
                )
            )

        base = self.evaluate(intent, context)
        decisions.extend(base.constraints)
        if base.decision is not RiskDecision.APPROVE:
            violations.append(base.reason)

        order_value = _order_value(intent, context)
        signed = _signed_notional(intent, order_value)
        if order_value is None or signed is None:
            violations.append("RISK_VALUE_INVALID: order notional cannot be determined")
            decisions.append(
                ConstraintDecision(ConstraintResult.REJECT, "order_notional", violations[-1])
            )
            return _risk_result(
                context, RiskDecision.REJECT, "; ".join(violations), tuple(decisions)
            )

        if limits.max_order_notional is not None:
            self._check_limit(
                decisions,
                violations,
                "order_notional",
                abs(order_value) > limits.max_order_notional,
                f"ORDER_NOTIONAL_LIMIT_EXCEEDED: notional {abs(order_value)} "
                f"exceeds maximum {limits.max_order_notional}",
            )

        if limits.max_position_notional is not None:
            current = _risk_number(snapshot.current_position_exposure)
            if current is None:
                self._reject_value(
                    decisions, violations, "position_exposure", "current_position_exposure"
                )
            else:
                projected = current + signed
                self._check_limit(
                    decisions,
                    violations,
                    "position_exposure",
                    abs(projected) > limits.max_position_notional,
                    f"POSITION_EXPOSURE_LIMIT_EXCEEDED: projected exposure "
                    f"{abs(projected)} exceeds maximum {limits.max_position_notional}",
                )

        if limits.max_portfolio_exposure is not None:
            current = _risk_number(snapshot.current_portfolio_exposure)
            if current is None:
                self._reject_value(
                    decisions, violations, "portfolio_exposure", "current_portfolio_exposure"
                )
            else:
                projected = current + signed
                self._check_limit(
                    decisions,
                    violations,
                    "portfolio_exposure",
                    abs(projected) > limits.max_portfolio_exposure,
                    f"PORTFOLIO_EXPOSURE_LIMIT_EXCEEDED: projected exposure "
                    f"{abs(projected)} exceeds maximum {limits.max_portfolio_exposure}",
                )

        if limits.max_instrument_concentration is not None:
            instrument = _risk_number(snapshot.current_instrument_exposure)
            portfolio = _risk_number(snapshot.current_portfolio_exposure)
            if instrument is None or portfolio is None:
                self._reject_value(
                    decisions,
                    violations,
                    "instrument_concentration",
                    "current_instrument_exposure/current_portfolio_exposure",
                )
            else:
                denominator = abs(portfolio + signed)
                if denominator == 0:
                    violations.append(
                        "RISK_STATE_INCONSISTENT: projected portfolio exposure "
                        "is zero; concentration cannot be determined"
                    )
                    decisions.append(
                        ConstraintDecision(
                            ConstraintResult.REJECT,
                            "instrument_concentration",
                            violations[-1],
                        )
                    )
                else:
                    concentration = abs(instrument + signed) / denominator
                    self._check_limit(
                        decisions,
                        violations,
                        "instrument_concentration",
                        concentration > limits.max_instrument_concentration,
                        f"INSTRUMENT_CONCENTRATION_LIMIT_EXCEEDED: concentration "
                        f"{concentration} exceeds maximum "
                        f"{limits.max_instrument_concentration}",
                    )

        if limits.max_daily_loss is not None:
            pnl = _risk_number(snapshot.daily_pnl)
            if pnl is None:
                self._reject_value(decisions, violations, "daily_loss", "daily_pnl")
            else:
                # Only already-realized daily P&L counts; the proposed order
                # is never treated as realized loss.
                self._check_limit(
                    decisions,
                    violations,
                    "daily_loss",
                    -pnl > limits.max_daily_loss,
                    f"DAILY_LOSS_LIMIT_EXCEEDED: daily loss {-pnl} exceeds maximum "
                    f"{limits.max_daily_loss}",
                )

        if limits.max_drawdown is not None:
            equity = _risk_number(snapshot.equity)
            high_water_mark = _risk_number(snapshot.high_water_mark)
            if equity is None or high_water_mark is None or equity < 0 or high_water_mark <= 0:
                self._reject_value(decisions, violations, "drawdown", "equity/high_water_mark")
            else:
                drawdown = (high_water_mark - equity) / high_water_mark
                self._check_limit(
                    decisions,
                    violations,
                    "drawdown",
                    drawdown > limits.max_drawdown,
                    f"DRAWDOWN_LIMIT_EXCEEDED: drawdown {drawdown} exceeds maximum "
                    f"{limits.max_drawdown}",
                )

        self._check_margin(decisions, violations, snapshot)

        if violations:
            return _risk_result(
                context, RiskDecision.REJECT, "; ".join(violations), tuple(decisions)
            )
        return _risk_result(
            context,
            RiskDecision.APPROVE,
            "pre-trade risk checks passed",
            tuple(decisions),
        )

    @staticmethod
    def _check_limit(
        decisions: list[ConstraintDecision],
        violations: list[str],
        name: str,
        breached: bool,
        message: str,
    ) -> None:
        if breached:
            violations.append(message)
            decisions.append(ConstraintDecision(ConstraintResult.REJECT, name, message))
        else:
            decisions.append(
                ConstraintDecision(ConstraintResult.PASS, name, f"{name} within limit")
            )

    @staticmethod
    def _reject_value(
        decisions: list[ConstraintDecision],
        violations: list[str],
        name: str,
        field: str,
    ) -> None:
        message = f"RISK_VALUE_INVALID: {field} is missing or invalid"
        violations.append(message)
        decisions.append(ConstraintDecision(ConstraintResult.REJECT, name, message))

    @staticmethod
    def _check_margin(
        decisions: list[ConstraintDecision],
        violations: list[str],
        snapshot: RiskSnapshot,
    ) -> None:
        """Broker-neutral margin boundary: finite, non-negative, sufficient."""
        required = _risk_number(snapshot.required_margin)
        available = _risk_number(snapshot.available_margin)
        if required is None or available is None:
            message = "MARGIN_INSUFFICIENT: required/available margin is unavailable"
        elif required < 0 or available < 0:
            message = "MARGIN_INSUFFICIENT: margin values must not be negative"
        elif required > available:
            message = (
                f"MARGIN_INSUFFICIENT: required margin {required} exceeds "
                f"available margin {available}"
            )
        else:
            decisions.append(
                ConstraintDecision(
                    ConstraintResult.PASS, "snapshot_margin", "sufficient available margin"
                )
            )
            return
        violations.append(message)
        decisions.append(ConstraintDecision(ConstraintResult.REJECT, "snapshot_margin", message))


def _signed_notional(intent: TradeIntent, order_value: Decimal | None) -> Decimal | None:
    """Signed order notional: BUY adds exposure, SELL reduces it."""
    if order_value is None:
        return None
    if intent.side is OrderSide.BUY:
        return order_value
    if intent.side is OrderSide.SELL:
        return -order_value
    return None
