"""Deployment-aware strategy execution boundary.

This module binds a validated strategy identity to a deployment without
implementing broker execution. The same boundary can feed backtest, replay,
paper, shadow, or live adapters.
"""

from __future__ import annotations

from dataclasses import dataclass

from quantx.domain.deployment import StrategyDeployment
from quantx.domain.market_data import MarketDataEvent
from quantx.domain.strategy import StrategyResult

from .evaluation import StrategyEvaluationService
from .ir import StrategyIR
from .registry import StrategyRegistry


@dataclass(frozen=True, slots=True)
class StrategyExecutionDecision:
    """Strategy output together with the deployment that authorized evaluation."""

    deployment: StrategyDeployment
    result: StrategyResult


class StrategyDeploymentRuntime:
    """Resolve a deployed strategy and evaluate it against canonical market data."""

    def __init__(self, registry: StrategyRegistry) -> None:
        self._registry = registry

    def evaluate(
        self,
        deployment: StrategyDeployment,
        ir: StrategyIR,
        event: MarketDataEvent,
    ) -> StrategyExecutionDecision:
        self._validate_deployment(deployment, ir, event)
        strategy = self._registry.resolve(ir)
        evaluation = StrategyEvaluationService(strategy).evaluate(event, ir)
        return StrategyExecutionDecision(
            deployment=deployment,
            result=evaluation.result,
        )

    @staticmethod
    def _validate_deployment(
        deployment: StrategyDeployment,
        ir: StrategyIR,
        event: MarketDataEvent,
    ) -> None:
        if not deployment.enabled:
            raise ValueError("strategy deployment is disabled")
        if deployment.strategy_id != ir.strategy_id.value:
            raise ValueError("deployment strategy id does not match strategy IR")
        if deployment.strategy_version != ir.version:
            raise ValueError("deployment strategy version does not match strategy IR")
        if deployment.market.venue != event.instrument.venue:
            raise ValueError("deployment market venue does not match market event")
