"""Post-trade risk enforcement at the execution/accounting boundary."""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.finance import AccountFinancialState
from quantx.domain.value_objects import Money
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

    def evaluate(
        self,
        *,
        financial_state: AccountFinancialState,
        daily_pnl: Money,
        gross_exposure: Money,
    ) -> RiskEnforcementResult:
        result = self._engine.evaluate(
            PostTradeRiskSnapshot(financial_state, daily_pnl, gross_exposure),
            self._limits,
        )
        if result.breached:
            self._gate.block("; ".join(result.reasons))
        return RiskEnforcementResult(result.allowed, result.reasons)
