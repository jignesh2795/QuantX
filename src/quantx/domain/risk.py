"""Pre-trade risk evaluation for TradeIntent objects.

The first implementation deliberately evaluates only deterministic domain
constraints. Execution-time and post-trade risk can be layered on later.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from .constraints import (
    ConstraintDecision,
    ConstraintResult,
    TradeConstraintInput,
    evaluate_broker_constraint,
    evaluate_capital,
)
from .enums import OrderSide
from .finance import AccountFinancialState, BrokerConstraint
from .instruments import Instrument
from .order_intents import TradeIntent
from .value_objects import Money, Quantity


class RiskDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True, slots=True)
class RiskContext:
    instrument: Instrument
    financial_state: AccountFinancialState
    broker_constraints: tuple[BrokerConstraint, ...] = ()
    reference_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RiskResult:
    decision: RiskDecision
    reason: str
    constraints: tuple[ConstraintDecision, ...] = ()


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


class PreTradeRiskEngine:
    """Evaluate whether a TradeIntent may proceed to order construction."""

    def evaluate(self, intent: TradeIntent, context: RiskContext) -> RiskResult:
        if intent.execution_context is None:
            return RiskResult(RiskDecision.REJECT, "execution context is required")

        required_margin = Money(
            intent.required_margin,
            context.financial_state.margin_available.currency,
        )
        decisions: list[ConstraintDecision] = [
            evaluate_capital(context.financial_state, required_margin)
        ]
        if decisions[-1].result is ConstraintResult.REJECT:
            return RiskResult(RiskDecision.REJECT, decisions[-1].reason, tuple(decisions))

        order_value = _order_value(intent, context)
        if order_value is None:
            return RiskResult(
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
                return RiskResult(RiskDecision.REJECT, decision.reason, tuple(decisions))

        if intent.approval_required or any(
            decision.result is ConstraintResult.REQUIRES_APPROVAL for decision in decisions
        ):
            return RiskResult(
                RiskDecision.APPROVAL_REQUIRED,
                "explicit approval is required before execution",
                tuple(decisions),
            )

        return RiskResult(RiskDecision.APPROVE, "pre-trade risk checks passed", tuple(decisions))

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
            return RiskResult(
                RiskDecision.REJECT,
                "RISK_VALUE_INVALID: evaluated_at must be timezone-aware",
            )
        if snapshot is None:
            return RiskResult(
                RiskDecision.REJECT,
                "RISK_SNAPSHOT_MISSING: risk snapshot is required for limit enforcement",
            )

        violations: list[str] = []
        decisions: list[ConstraintDecision] = []

        if limits.max_snapshot_age is not None:
            age = evaluated_at - snapshot.observed_at
            if age < timedelta(0):
                violations.append(
                    "RISK_STATE_INCONSISTENT: risk snapshot is future-dated"
                )
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
            violations.append(
                "RISK_VALUE_INVALID: order notional cannot be determined"
            )
            decisions.append(
                ConstraintDecision(
                    ConstraintResult.REJECT, "order_notional", violations[-1]
                )
            )
            return RiskResult(RiskDecision.REJECT, "; ".join(violations), tuple(decisions))

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
            if (
                equity is None
                or high_water_mark is None
                or equity < 0
                or high_water_mark <= 0
            ):
                self._reject_value(
                    decisions, violations, "drawdown", "equity/high_water_mark"
                )
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
            return RiskResult(RiskDecision.REJECT, "; ".join(violations), tuple(decisions))
        return RiskResult(
            RiskDecision.APPROVE, "pre-trade risk checks passed", tuple(decisions)
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
