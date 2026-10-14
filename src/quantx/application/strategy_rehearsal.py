"""Deployment-bound deterministic strategy rehearsal on the paper venue.

A rehearsal composes only existing canonical seams — registry resolution,
runtime evaluation, deployment-context binding, risk/policy preparation,
and the paper order executor — into one run-scoped session. It proves a
registered Python strategy can reach the paper boundary deterministically
without any broker-submit path: execution flows exclusively through
``PaperOrderExecutor`` and only ``PAPER`` deployments are admitted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from quantx.domain.deployment import ExecutionMode, StrategyDeployment
from quantx.domain.finance import AccountFinancialState
from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.market_data import MarketDataEvent
from quantx.domain.policy import ExecutionPolicyEngine, PolicyContext
from quantx.domain.risk import PreTradeRiskEngine
from quantx.execution.paper.executor import PaperExecutionOutcome, PaperOrderExecutor
from quantx.execution.paper.fills import MarketSnapshot
from quantx.execution.paper.profile import OrderBookSnapshot
from quantx.strategy.deployment import StrategyExecutionDecision
from quantx.strategy.evaluation import StrategyEvaluation, StrategyEvaluationService
from quantx.strategy.execution import (
    StrategyExecutionPreparation,
    StrategyExecutionPreparer,
    bind_deployment_context,
)
from quantx.strategy.ir import StrategyIR
from quantx.strategy.registry import StrategyRegistry


@dataclass(frozen=True, slots=True)
class RehearsalInput:
    """Injected market evidence for one rehearsal step.

    Time comes from the event itself: the paper executor observes
    ``event.timestamp``, so there is no separate clock to diverge. A missing
    snapshot means missing market evidence; the paper venue then produces
    no fill rather than an invented one. An optional order book carries
    depth evidence for partial-fill semantics.
    """

    event: MarketDataEvent
    snapshot: MarketSnapshot | None
    submitted_at_ns: int
    order_book: OrderBookSnapshot | None = None

    def __post_init__(self) -> None:
        if self.submitted_at_ns < 0:
            raise ValueError("submitted_at_ns cannot be negative")


@dataclass(frozen=True, slots=True)
class StrategyRehearsalStep:
    """Recorded outcome of one rehearsal step."""

    event: MarketDataEvent
    evaluation: StrategyEvaluation
    preparation: StrategyExecutionPreparation
    paper_outcome: PaperExecutionOutcome | None
    note: str


@dataclass(frozen=True, slots=True)
class StrategyRehearsalResult:
    """Immutable record of one completed rehearsal run."""

    deployment: StrategyDeployment
    strategy_ir: StrategyIR
    steps: tuple[StrategyRehearsalStep, ...]


class StrategyRehearsalSession:
    """Run a registered strategy once against injected paper market evidence.

    The session resolves exactly one fresh strategy instance and is
    single-use: a second ``run`` call raises, so private strategy state can
    never leak across runs. Only ``PAPER`` deployments are admitted; any
    other execution mode — including ``LIVE`` — is rejected at
    construction.
    """

    def __init__(
        self,
        *,
        registry: StrategyRegistry,
        strategy_ir: StrategyIR,
        deployment: StrategyDeployment,
        instrument_registry: InstrumentRegistry,
        paper_executor: PaperOrderExecutor,
        financial_state: AccountFinancialState,
        risk_engine: PreTradeRiskEngine | None = None,
        policy_engine: ExecutionPolicyEngine | None = None,
        policy_context: PolicyContext | None = None,
    ) -> None:
        if deployment.execution_mode is not ExecutionMode.PAPER:
            raise ValueError("strategy rehearsal admits PAPER deployments only")
        if not deployment.enabled:
            raise ValueError("strategy deployment is disabled")
        if deployment.strategy_id != strategy_ir.strategy_id.value:
            raise ValueError("deployment strategy id does not match strategy IR")
        if deployment.strategy_version != strategy_ir.version:
            raise ValueError("deployment strategy version does not match strategy IR")
        self._deployment = deployment
        self._strategy_ir = strategy_ir
        self._evaluation = StrategyEvaluationService(registry.resolve(strategy_ir))
        self._preparer = StrategyExecutionPreparer(
            instrument_registry,
            risk_engine=risk_engine,
            policy_engine=policy_engine,
        )
        self._paper_executor = paper_executor
        self._financial_state = financial_state
        self._policy_context = policy_context or PolicyContext()
        self._consumed = False

    def run(self, inputs: tuple[RehearsalInput, ...]) -> StrategyRehearsalResult:
        """Evaluate, bind, prepare, and paper-execute one input per step."""
        if self._consumed:
            raise ValueError("rehearsal session is single-use; resolve a fresh session per run")
        self._consumed = True
        steps = tuple(self._step(rehearsal_input) for rehearsal_input in inputs)
        return StrategyRehearsalResult(
            deployment=self._deployment,
            strategy_ir=self._strategy_ir,
            steps=steps,
        )

    def _step(self, rehearsal_input: RehearsalInput) -> StrategyRehearsalStep:
        event = rehearsal_input.event
        if self._deployment.market.venue != event.instrument.venue:
            raise ValueError("deployment market venue does not match market event")
        evaluation = self._evaluation.evaluate(event, self._strategy_ir)
        intent = evaluation.result.intent
        if intent is None:
            preparation = StrategyExecutionPreparation(
                StrategyExecutionDecision(self._deployment, evaluation.result),
                None,
                None,
                None,
            )
            return StrategyRehearsalStep(
                event, evaluation, preparation, None, "strategy produced no executable intent"
            )
        bound = replace(evaluation.result, intent=bind_deployment_context(intent, self._deployment))
        preparation = self._preparer.prepare(
            StrategyExecutionDecision(self._deployment, bound),
            event,
            self._financial_state,
            policy_context=self._policy_context,
        )
        if preparation.request is None:
            return StrategyRehearsalStep(
                event, evaluation, preparation, None, self._rejection_note(preparation)
            )
        paper_outcome = self._paper_executor.execute(
            preparation.request.order,
            snapshot=rehearsal_input.snapshot,
            submitted_at_ns=rehearsal_input.submitted_at_ns,
            observed_at=event.timestamp,
            order_book=rehearsal_input.order_book,
        )
        return StrategyRehearsalStep(
            event, evaluation, preparation, paper_outcome, "paper executed"
        )

    @staticmethod
    def _rejection_note(preparation: StrategyExecutionPreparation) -> str:
        if preparation.risk_result is None:
            return "strategy produced no executable intent"
        if preparation.policy_result is None:
            return f"risk rejected: {preparation.risk_result.reason}"
        return f"policy rejected: {preparation.policy_result.reason}"
