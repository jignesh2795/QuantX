"""Post-trade risk enforcement at the execution/accounting boundary."""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.finance import AccountFinancialState
from quantx.domain.value_objects import Money
from quantx.execution.account_financial_state import AccountFinancialSnapshot
from quantx.execution.post_trade_risk import (
    PostTradeRiskEngine,
    PostTradeRiskLimits,
    PostTradeRiskSnapshot,
)
from quantx.execution.trading_gate import TradingGate


@dataclass(frozen=True, slots=True)
class RiskEnforcementResult:
    allowed: bool
    reasons: tuple[str, ...] = ()

    @property
    def breached(self) -> bool:
        return not self.allowed


class PostTradeRiskEnforcer:
    """Evaluate post-trade state and trip the runtime gate on a breach."""

    def __init__(
        self,
        *,
        limits: PostTradeRiskLimits,
        trading_gate: TradingGate,
        engine: PostTradeRiskEngine | None = None,
    ) -> None:
        self._limits = limits
        self._gate = trading_gate
        self._engine = engine or PostTradeRiskEngine()

    def evaluate_projected_limits(
        self,
        *,
        margin_used: Money,
        margin_available: Money,
        gross_exposure: Money,
        position_exposures: tuple[Money, ...],
    ) -> RiskEnforcementResult:
        result = self._engine.evaluate_projected_limits(
            margin_used=margin_used,
            margin_available=margin_available,
            gross_exposure=gross_exposure,
            position_exposures=position_exposures,
            limits=self._limits,
        )
        return RiskEnforcementResult(result.allowed, result.reasons)

    def evaluate_snapshot(
        self,
        snapshot: AccountFinancialSnapshot,
    ) -> RiskEnforcementResult:
        return self.evaluate(
            financial_state=snapshot.state,
            daily_pnl=snapshot.daily_pnl,
            gross_exposure=snapshot.gross_exposure,
            position_exposures=snapshot.position_exposures,
        )

    def evaluate(
        self,
        *,
        financial_state: AccountFinancialState,
        daily_pnl: Money,
        gross_exposure: Money,
        position_exposures: tuple[Money, ...] = (),
    ) -> RiskEnforcementResult:
        result = self._engine.evaluate(
            PostTradeRiskSnapshot(
                financial_state,
                daily_pnl,
                gross_exposure,
                position_exposures,
            ),
            self._limits,
        )
        if result.breached:
            self._gate.block("; ".join(result.reasons))
        return RiskEnforcementResult(result.allowed, result.reasons)
