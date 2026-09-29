"""Deterministic post-trade account risk checks."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantx.domain.finance import AccountFinancialState
from quantx.domain.value_objects import Money


@dataclass(frozen=True, slots=True)
class PostTradeRiskLimits:
    max_daily_loss: Money | None = None
    max_margin_utilization: Decimal | None = None
    max_exposure: Money | None = None
    max_position_exposure: Money | None = None
    max_open_positions: int | None = None

    def __post_init__(self) -> None:
        if self.max_daily_loss is not None and self.max_daily_loss.amount < 0:
            raise ValueError("max_daily_loss cannot be negative")
        if self.max_margin_utilization is not None and not (
            Decimal("0") <= self.max_margin_utilization <= Decimal("1")
        ):
            raise ValueError("max_margin_utilization must be between 0 and 1")
        if self.max_exposure is not None and self.max_exposure.amount < 0:
            raise ValueError("max_exposure cannot be negative")
        if self.max_position_exposure is not None and self.max_position_exposure.amount < 0:
            raise ValueError("max_position_exposure cannot be negative")
        if self.max_open_positions is not None and self.max_open_positions < 0:
            raise ValueError("max_open_positions cannot be negative")


@dataclass(frozen=True, slots=True)
class PostTradeRiskSnapshot:
    financial_state: AccountFinancialState
    daily_pnl: Money
    gross_exposure: Money
    position_exposures: tuple[Money, ...] = ()


@dataclass(frozen=True, slots=True)
class PostTradeRiskResult:
    allowed: bool
    reasons: tuple[str, ...] = ()

    @property
    def breached(self) -> bool:
        return not self.allowed


class PostTradeRiskEngine:
    """Evaluate account limits after an execution state change.

    Limits are explicit policy inputs; this engine does not invent broker
    rules. A breach is intended to feed the runtime TradingGate.
    """

    def evaluate(
        self,
        snapshot: PostTradeRiskSnapshot,
        limits: PostTradeRiskLimits,
    ) -> PostTradeRiskResult:
        reasons: list[str] = []
        state = snapshot.financial_state

        if limits.max_daily_loss is not None:
            self._require_currency(snapshot.daily_pnl, limits.max_daily_loss, "daily loss")
            if snapshot.daily_pnl.amount < -limits.max_daily_loss.amount:
                reasons.append("maximum daily loss exceeded")

        if limits.max_margin_utilization is not None:
            total = state.margin_used.amount + state.margin_available.amount
            utilization = (
                state.margin_used.amount / total if total > 0 else Decimal("0")
            )
            if utilization > limits.max_margin_utilization:
                reasons.append("maximum margin utilization exceeded")

        if limits.max_exposure is not None:
            self._require_currency(snapshot.gross_exposure, limits.max_exposure, "exposure")
            if snapshot.gross_exposure.amount > limits.max_exposure.amount:
                reasons.append("maximum gross exposure exceeded")

        if limits.max_open_positions is not None:
            open_positions = sum(
                1
                for exposure in snapshot.position_exposures
                if exposure.amount > 0
            )
            if open_positions > limits.max_open_positions:
                reasons.append("maximum open positions exceeded")

        if limits.max_position_exposure is not None:
            for exposure in snapshot.position_exposures:
                self._require_currency(exposure, limits.max_position_exposure, "position exposure")
                if exposure.amount > limits.max_position_exposure.amount:
                    reasons.append("maximum single-position exposure exceeded")
                    break

        return PostTradeRiskResult(not reasons, tuple(reasons))

    def evaluate_projected_limits(
        self,
        *,
        margin_used: Money,
        margin_available: Money,
        gross_exposure: Money,
        position_exposures: tuple[Money, ...],
        limits: PostTradeRiskLimits,
    ) -> PostTradeRiskResult:
        """Evaluate hard limits against a projected execution state.

        Daily P&L is intentionally excluded because fill price, fees, and
        realized/unrealized P&L are not definitive before execution.
        """
        reasons: list[str] = []
        if margin_used.currency != margin_available.currency:
            raise ValueError("margin currency does not match")
        if limits.max_margin_utilization is not None:
            total = margin_used.amount + margin_available.amount
            utilization = margin_used.amount / total if total > 0 else Decimal("0")
            if utilization > limits.max_margin_utilization:
                reasons.append("maximum margin utilization exceeded")
        if limits.max_exposure is not None:
            self._require_currency(gross_exposure, limits.max_exposure, "exposure")
            if gross_exposure.amount > limits.max_exposure.amount:
                reasons.append("maximum gross exposure exceeded")
        if limits.max_open_positions is not None:
            open_positions = sum(1 for exposure in position_exposures if exposure.amount > 0)
            if open_positions > limits.max_open_positions:
                reasons.append("maximum open positions exceeded")
        if limits.max_position_exposure is not None:
            for exposure in position_exposures:
                self._require_currency(exposure, limits.max_position_exposure, "position exposure")
                if exposure.amount > limits.max_position_exposure.amount:
                    reasons.append("maximum single-position exposure exceeded")
                    break
        return PostTradeRiskResult(not reasons, tuple(reasons))

    @staticmethod
    def _require_currency(actual: Money, expected: Money, name: str) -> None:
        if actual.currency != expected.currency:
            raise ValueError(f"{name} currency does not match risk policy currency")
