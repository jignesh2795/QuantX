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
from datetime import UTC, datetime
from decimal import Decimal

from quantx.application.strategy_preflight import assess_rehearsal_event_time_support
from quantx.domain.deployment import ExecutionMode, StrategyDeployment
from quantx.domain.finance import AccountFinancialState
from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.market_data import Candle, MarketDataEvent
from quantx.domain.policy import ExecutionPolicyEngine, PolicyContext
from quantx.domain.risk import PreTradeRiskEngine
from quantx.execution.paper.executor import PaperExecutionOutcome, PaperOrderExecutor
from quantx.execution.paper.fills import MarketSnapshot
from quantx.execution.paper.profile import OrderBookSnapshot
from quantx.strategy.engine_snapshot import (
    EngineEvidenceAdapter,
    EngineStateSnapshot,
    EvidenceCollection,
    OpenOrderFact,
    active_order_fact,
    build_engine_snapshot,
    position_facts,
    prior_candle_history,
)
from quantx.strategy.deployment import StrategyExecutionDecision
from quantx.strategy.evaluation import StrategyEvaluation, StrategyEvaluationService
from quantx.strategy.execution import (
    StrategyExecutionPreparation,
    StrategyExecutionPreparer,
    bind_deployment_context,
)
from quantx.strategy.ir import StrategyIR
from quantx.strategy.registry import StrategyRegistry
from quantx.strategy.typed_params import TypedParams


@dataclass(frozen=True, slots=True)
class RehearsalInput:
    """Injected market evidence for one rehearsal step.

    A rehearsal runs on a single simulation timeline owned by the market
    event: the paper executor observes ``event.timestamp``, the submitted
    order is stamped from the same instant, and modeled venue latency is
    added on top by the venue profile. There is deliberately no separate
    injected submission clock, so contradictory timestamps (for example an
    epoch-nanosecond submission against a 2026 event) cannot be expressed.
    A missing snapshot means missing market evidence; the paper venue then
    produces no fill rather than an invented one. An optional order book
    carries depth evidence for partial-fill semantics.
    """

    event: MarketDataEvent
    snapshot: MarketSnapshot | None
    order_book: OrderBookSnapshot | None = None


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


_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _event_submitted_at_ns(event: MarketDataEvent) -> int:
    """Derive submission time from the event instant using exact integer math.

    The paper venue interprets submission time as Unix epoch nanoseconds, so
    the rehearsal derives it from the market event that caused the order.
    ``timedelta`` fields are integers, which keeps the conversion exact where
    a float epoch division would lose nanosecond precision.
    """
    delta = event.timestamp - _UNIX_EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


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
        self._active_orders: dict[str, OpenOrderFact] = {}
        self._consumed = False

    def run(self, inputs: tuple[RehearsalInput, ...]) -> StrategyRehearsalResult:
        """Evaluate, bind, prepare, and paper-execute one input per step."""
        if self._consumed:
            raise ValueError("rehearsal session is single-use; resolve a fresh session per run")
        previous_timestamp: datetime | None = None
        for rehearsal_input in inputs:
            timestamp = rehearsal_input.event.timestamp
            if previous_timestamp is not None and timestamp < previous_timestamp:
                raise ValueError("rehearsal input timestamps must be nondecreasing")
            previous_timestamp = timestamp

        history_bars = TypedParams.from_ir(self._strategy_ir).get_int(
            "history_bars", default=0, minimum=0, maximum=512
        )
        assess_rehearsal_event_time_support(self._paper_executor).require_supported()
        self._consumed = True
        candles = tuple(
            item.event.payload
            for item in inputs
            if isinstance(item.event.payload, Candle)
        )
        steps = tuple(
            self._step(rehearsal_input, candles=candles, history_bars=history_bars)
            for rehearsal_input in inputs
        )
        return StrategyRehearsalResult(
            deployment=self._deployment,
            strategy_ir=self._strategy_ir,
            steps=steps,
        )

    def _engine_snapshot(self, as_of: datetime) -> EngineStateSnapshot:
        adapter = EngineEvidenceAdapter(
            positions=EvidenceCollection.known(
                position_facts(self._paper_executor.accounting.snapshot())
            ),
            orders=EvidenceCollection.known(
                tuple(self._active_orders[key] for key in sorted(self._active_orders))
            ),
            account_state=None,
            account_reason=(
                "paper rehearsal does not have a canonical point-in-time account-state tracker"
            ),
        )
        return build_engine_snapshot(adapter, as_of=as_of)

    def _step(
        self,
        rehearsal_input: RehearsalInput,
        *,
        candles: tuple[Candle, ...],
        history_bars: int,
    ) -> StrategyRehearsalStep:
        event = rehearsal_input.event
        if self._deployment.market.venue != event.instrument.venue:
            raise ValueError("deployment market venue does not match market event")
        as_of = event.timestamp.astimezone(UTC)
        engine = self._engine_snapshot(as_of)
        history = prior_candle_history(
            candles,
            instrument=event.instrument,
            as_of=as_of,
            limit=history_bars,
        )
        evaluation = self._evaluation.evaluate(
            event,
            self._strategy_ir,
            engine=engine,
            as_of=as_of,
            history=history,
        )
        if evaluation.result.signal.generated_at != event.timestamp:
            raise ValueError("strategy signal timestamp does not match market event")
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
        approved = preparation.request
        if approved is None:
            return StrategyRehearsalStep(
                event, evaluation, preparation, None, self._rejection_note(preparation)
            )
        # Stamp order creation from the market event that caused the order.
        # The shared ``build_order_from_intent`` default is wall-clock time
        # for interactive construction; a rehearsal record carrying that
        # default would be nondeterministic, so this path pins it here
        # without changing the shared default. The recorded preparation
        # carries the same deterministic order that reaches the paper venue.
        deterministic = replace(
            approved,
            order=replace(approved.order, created_at=event.timestamp),
        )
        preparation = replace(preparation, request=deterministic)
        paper_outcome = self._paper_executor.execute(
            deterministic.order,
            snapshot=rehearsal_input.snapshot,
            submitted_at_ns=_event_submitted_at_ns(event),
            observed_at=event.timestamp,
            order_book=rehearsal_input.order_book,
        )
        order_key = str(deterministic.order.client_order_id)
        fill = paper_outcome.fill
        fact = active_order_fact(
            client_order_id=order_key,
            instrument=deterministic.order.instrument,
            status=paper_outcome.lifecycle_status,
            order_quantity=deterministic.order.quantity,
            filled_quantity=Decimal("0") if fill is None else fill.quantity,
            created_at=deterministic.order.created_at,
            evidence_time=event.timestamp if fill is None else fill.filled_at,
            reason=paper_outcome.reason or None,
        )
        if fact is None:
            self._active_orders.pop(order_key, None)
        else:
            self._active_orders[order_key] = fact
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
