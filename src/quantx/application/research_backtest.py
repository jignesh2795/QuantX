"""Application binding for durable deterministic backtest research runs."""

from __future__ import annotations

from collections.abc import Callable

from quantx.application.backtest import DeterministicBacktestService
from quantx.domain.finance import AccountFinancialState, BrokerConstraint
from quantx.domain.policy import PolicyContext
from quantx.domain.clock import Clock
from quantx.research.provenance import ResearchProvenance
from quantx.research.replay import MultiSeries
from quantx.research.data import HistoricalDataSeries
from quantx.research.result import ResearchResult, ResearchRunSpec
from quantx.application.backtest import AccountStateSamplingPolicy
from quantx.application.backtest import BacktestResult
from quantx.execution.paper import PaperSimulationProfile
from quantx.strategy.evaluation import StrategyEvaluationService
from quantx.strategy.ir import StrategyIR

StrategyArgument = Callable | StrategyEvaluationService
HistoricalSeries = HistoricalDataSeries | MultiSeries


class ResearchBacktestApplicationService:
    """Bind one deterministic backtest attempt to one durable research run."""

    def __init__(
        self,
        *,
        lifecycle: object,
        backtest: DeterministicBacktestService,
        clock: Clock,
    ) -> None:
        self._lifecycle = lifecycle
        self._backtest = backtest
        self._clock = clock

    def execute(
        self,
        spec: ResearchRunSpec,
        *,
        series: HistoricalSeries,
        strategy: StrategyArgument,
        financial_state: AccountFinancialState,
        strategy_ir: StrategyIR | None = None,
        policy_context: PolicyContext | None = None,
        broker_constraints: tuple[BrokerConstraint, ...] = (),
        allow_incomplete: bool = False,
        execution_profile: PaperSimulationProfile | None = None,
        candle_volume_participation_rate=None,
        account_state_sampling_policy: AccountStateSamplingPolicy = (
            AccountStateSamplingPolicy.EXACT_CURRENT
        ),
    ):
        """Execute a backtest through the durable research-run lifecycle."""
        def operation() -> ResearchResult:
            started_at = self._timestamp()
            backtest_result = self._backtest.run(
                series=series,
                strategy=strategy,
                financial_state=financial_state,
                strategy_ir=strategy_ir,
                policy_context=policy_context,
                broker_constraints=broker_constraints,
                allow_incomplete=allow_incomplete,
                execution_profile=execution_profile,
                candle_volume_participation_rate=candle_volume_participation_rate,
                account_state_sampling_policy=account_state_sampling_policy,
                provenance=spec.to_provenance(),
            )
            completed_at = self._timestamp()
            return self._to_research_result(
                spec=spec,
                backtest_result=backtest_result,
                started_at=started_at,
                completed_at=completed_at,
            )

        return self._lifecycle.execute(spec, operation)

    @staticmethod
    def _to_research_result(
        *,
        spec: ResearchRunSpec,
        backtest_result: BacktestResult,
        started_at: str,
        completed_at: str,
    ) -> ResearchResult:
        if not backtest_result.steps:
            raise ValueError("backtest result contains no replay steps")

        fidelity = backtest_result.fidelity
        assumptions = (
            f"deterministic={str(fidelity.deterministic).lower()}",
            f"simulated={str(fidelity.simulated).lower()}",
            *tuple(f"evidence_type={item}" for item in fidelity.evidence_types),
            *tuple(f"execution_model={item}" for item in fidelity.execution_models),
        )
        metrics = (
            ("step_count", str(len(backtest_result.steps))),
            ("receipt_count", str(len(backtest_result.receipts))),
            ("ledger_entry_count", str(len(backtest_result.ledger))),
            ("account_state_count", str(len(backtest_result.account_states))),
            ("account_state_series_count", str(len(backtest_result.account_state_series)),
             ),
            ("executed_count", str(backtest_result.executed_count)),
            ("rejected_count", str(backtest_result.rejected_count)),
        )
        from decimal import Decimal

        return ResearchResult(
            spec=spec,
            quality=fidelity.quality,
            started_at=started_at,
            completed_at=completed_at,
            time_range_start=backtest_result.steps[0].timestamp,
            time_range_end=backtest_result.steps[-1].timestamp,
            metrics=tuple((name, Decimal(value)) for name, value in metrics),
            assumptions=assumptions,
            limitations=fidelity.limitations,
            provenance=backtest_result.provenance or ResearchProvenance.from_run_spec(spec),
        )

    def _timestamp(self) -> str:
        observed = self._clock.now()
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("research backtest clock must return a timezone-aware timestamp")
        return observed.isoformat()
