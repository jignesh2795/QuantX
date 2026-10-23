"""Validated LIVE pre-trade risk evaluator composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.order_intents import TradeIntent
from quantx.domain.risk import (
    PreTradeRiskEngine,
    RiskContext,
    RiskLimits,
    RiskResult,
    RiskSnapshot,
    require_live_risk_limits,
)


@dataclass(frozen=True, slots=True)
class LiveRiskEvaluationInputs:
    """Explicit inputs for one LIVE risk evaluation."""

    intent: TradeIntent
    context: RiskContext
    snapshot: RiskSnapshot
    evaluated_at: datetime


class LivePreTradeRiskEvaluator:
    """Callable LIVE risk evaluator with construction-time limit validation."""

    def __init__(
        self,
        *,
        engine: PreTradeRiskEngine,
        limits: RiskLimits,
        inputs_for_request: Callable[[ApprovedExecutionRequest], LiveRiskEvaluationInputs],
    ) -> None:
        self._engine = engine
        self._limits = require_live_risk_limits(limits)
        self._inputs_for_request = inputs_for_request

    def __call__(self, request: ApprovedExecutionRequest) -> RiskResult:
        inputs = self._inputs_for_request(request)
        if type(inputs) is not LiveRiskEvaluationInputs:
            raise TypeError("LIVE risk evaluation inputs have an unsupported type")
        return self._engine.evaluate_with_limits(
            inputs.intent,
            inputs.context,
            limits=self._limits,
            snapshot=inputs.snapshot,
            evaluated_at=inputs.evaluated_at,
        )
