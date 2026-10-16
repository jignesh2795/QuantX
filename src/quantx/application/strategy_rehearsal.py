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

from quantx.domain.deployment import ExecutionMode, StrategyDeployment
from quantx.domain.finance import AccountFinancialState
from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.clock import SimulatedClock
from quantx.domain.market_data import Candle, MarketDataEvent
from quantx.domain.policy import ExecutionPolicyEngine, PolicyContext
from quantx.domain.risk import PreTradeRiskEngine
from quantx.execution.paper.executor import PaperExecutionOutcome, PaperOrderExecutor
from quantx.execution.paper.fills import MarketSnapshot
from quantx.execution.paper.profile import OrderBookSnapshot
from quantx.strategy.callbacks import (
    CallbackFault,
    OrderUpdateFact,
    RunHaltRecord,
    TemporalIntegrityFault,
    callback_fault,
    dispatch_post_commit_callbacks,
    dispatch_timer_callback,
)
from quantx.strategy.engine_snapshot import (
    OpenOrderFact,
    active_order_fact,
    build_simulated_engine_snapshot,
    prior_candle_history,
)
from quantx.application.strategy_preflight import assess_rehearsal_event_time_support
from quantx.strategy.deployment import StrategyExecutionDecision
from quantx.strategy.evaluation import StrategyEvaluation, StrategyEvaluationService
from quantx.strategy.execution import (
    StrategyExecutionPreparation,
    StrategyExecutionPreparer,
    bind_deployment_context,
)
from quantx.strategy.ir import StrategyIR
from quantx.strategy.registry import StrategyRegistry
from quantx.strategy.timers import TimerRegistry, UndeliveredTimer
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
    """Recorded outcome of one rehearsal step, including pre-commit failures."""

    event: MarketDataEvent
    evaluation: StrategyEvaluation | None
    preparation: StrategyExecutionPreparation | None
    paper_outcome: PaperExecutionOutcome | None
    note: str
    faults: tuple[CallbackFault, ...] = ()


@dataclass(frozen=True, slots=True)
class StrategyRehearsalResult:
    """Immutable record of one completed rehearsal run."""

    deployment: StrategyDeployment
    strategy_ir: StrategyIR
    steps: tuple[StrategyRehearsalStep, ...]
    callback_faults: tuple[CallbackFault, ...] = ()
    halt: RunHaltRecord | None = None
    temporal_faults: tuple[TemporalIntegrityFault, ...] = ()
    undelivered_timers: tuple[UndeliveredTimer, ...] = ()


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
        self._consumed = False

    def run(self, inputs: tuple[RehearsalInput, ...]) -> StrategyRehearsalResult:
        """Run one monotonic, event-time-coherent paper rehearsal."""
        if self._consumed:
            raise ValueError("rehearsal session is single-use; resolve a fresh session per run")

        previous: datetime | None = None
        for rehearsal_input in inputs:
            event_time = rehearsal_input.event.timestamp
            if previous is not None and event_time < previous:
                raise ValueError("rehearsal input timestamps must be nondecreasing")
            previous = event_time

        history_limit = TypedParams.from_ir(self._strategy_ir).get_int(
            "history_bars", default=0, minimum=0, maximum=512
        )
        # Preflight before consuming the single-use session or executing any step.
        assess_rehearsal_event_time_support(self._paper_executor).require_supported()
        self._consumed = True

        timers = TimerRegistry()
        active_orders: dict[str, OpenOrderFact] = {}
        steps: list[StrategyRehearsalStep] = []
        callback_faults: list[CallbackFault] = []
        temporal_faults: list[TemporalIntegrityFault] = []
        halt: RunHaltRecord | None = None
        candles = tuple(
            item.event.payload
            for item in inputs
            if isinstance(item.event.payload, Candle)
        )
        logical_clock = SimulatedClock(inputs[0].event.timestamp) if inputs else None
        callback_target = self._evaluation.callback_target
        index = 0

        while index < len(inputs):
            cohort_time = inputs[index].event.timestamp
            cohort_end = index + 1
            while cohort_end < len(inputs) and inputs[cohort_end].event.timestamp == cohort_time:
                cohort_end += 1
            cohort = inputs[index:cohort_end]

            if halt is not None:
                for rehearsal_input in cohort:
                    steps.append(
                        StrategyRehearsalStep(
                            rehearsal_input.event, None, None, None,
                            f"run halted: {halt.reason}",
                        )
                    )
                index = cohort_end
                continue

            due_faults: list[CallbackFault] = []
            for timer in timers.take_due(cohort_time):
                assert logical_clock is not None
                logical_clock.set_time(timer.due_at)
                try:
                    snapshot = build_simulated_engine_snapshot(
                        as_of=timer.due_at,
                        accounting=self._paper_executor.accounting,
                        active_orders=tuple(
                            active_orders[key] for key in sorted(active_orders)
                        ),
                        account_state=None,
                        account_reason=(
                            "paper rehearsal does not expose authoritative current "
                            "account-state valuation"
                        ),
                    )
                    history = prior_candle_history(
                        candles,
                        instrument=timer.instrument,
                        as_of=timer.due_at,
                        limit=history_limit,
                    )
                    assert logical_clock is not None
                    context = StrategyContext(
                        event=None,
                        ir=self._strategy_ir,
                        as_of=logical_clock.now(),
                        engine=snapshot,
                        history=history,
                    )
                    fault = dispatch_timer_callback(callback_target, context, timer)
                except Exception as exc:
                    fault = callback_fault("on_timer_context", timer.timer_id, exc)
                if fault is not None:
                    due_faults.append(fault)
                    callback_faults.append(fault)

            if logical_clock is not None:
                logical_clock.set_time(cohort_time)

            if due_faults:
                for offset, rehearsal_input in enumerate(cohort):
                    steps.append(
                        StrategyRehearsalStep(
                            rehearsal_input.event,
                            None,
                            None,
                            None,
                            "timestamp cohort blocked because a due timer callback failed",
                            tuple(due_faults) if offset == 0 else (),
                        )
                    )
                index = cohort_end
                continue

            for rehearsal_input in cohort:
                if halt is not None:
                    steps.append(
                        StrategyRehearsalStep(
                            rehearsal_input.event, None, None, None,
                            f"run halted: {halt.reason}",
                        )
                    )
                    continue
                event = rehearsal_input.event
                identity = f"{event.timestamp.isoformat()}:{event.instrument}"
                try:
                    if self._deployment.market.venue != event.instrument.venue:
                        raise ValueError("deployment market venue does not match market event")
                    snapshot = build_simulated_engine_snapshot(
                        as_of=event.timestamp,
                        accounting=self._paper_executor.accounting,
                        active_orders=tuple(
                            active_orders[key] for key in sorted(active_orders)
                        ),
                        account_state=None,
                        account_reason=(
                            "paper rehearsal does not expose authoritative current "
                            "account-state valuation"
                        ),
                    )
                    history = prior_candle_history(
                        candles,
                        instrument=event.instrument,
                        as_of=event.timestamp,
                        limit=history_limit,
                    )
                    assert logical_clock is not None
                    evaluation = self._evaluation.evaluate(
                        event,
                        self._strategy_ir,
                        engine=snapshot,
                        as_of=logical_clock.now(),
                        history=history,
                    )
                    if evaluation.result.signal.generated_at != event.timestamp:
                        raise ValueError("strategy signal timestamp does not match market event")
                    timers.register_result(evaluation.result, event)
                except Exception as exc:
                    fault = callback_fault("on_market_data", identity, exc)
                    callback_faults.append(fault)
                    steps.append(
                        StrategyRehearsalStep(
                            event, None, None, None,
                            f"pre-commit strategy step failed: {fault.message}",
                            (fault,),
                        )
                    )
                    continue

                step = self._step(rehearsal_input, evaluation)
                steps.append(step)
                outcome = step.paper_outcome
                preparation = step.preparation
                if outcome is None or preparation is None or preparation.request is None:
                    continue

                order = preparation.request.order
                order_id = str(order.client_order_id)
                update_reason = outcome.reason
                if outcome.lifecycle_status is OrderStatus.UNKNOWN and not update_reason:
                    update_reason = (
                        "order status is UNKNOWN; fill and remaining quantities "
                        "are not authoritative"
                    )
                filled_quantity = (
                    None
                    if outcome.lifecycle_status is OrderStatus.UNKNOWN and outcome.fill is None
                    else Decimal("0")
                    if outcome.fill is None
                    else outcome.fill.quantity
                )
                fact = active_order_fact(
                    client_order_id=order_id,
                    instrument=order.instrument,
                    status=outcome.lifecycle_status,
                    order_quantity=order.quantity,
                    filled_quantity=filled_quantity,
                    created_at=order.created_at,
                    evidence_time=event.timestamp,
                    reason=update_reason,
                    effective_at=(
                        event.timestamp
                        if outcome.fill is None
                        else outcome.fill.filled_at
                    ),
                )
                if fact is None:
                    active_orders.pop(order_id, None)
                else:
                    active_orders[order_id] = fact

                if outcome.fill is not None and outcome.fill.filled_at > event.timestamp:
                    temporal_fault = TemporalIntegrityFault(
                        source="paper_fill",
                        identity=order_id,
                        expected_at=event.timestamp,
                        effective_at=outcome.fill.filled_at,
                        reason="fill effective time is later than the rehearsal event",
                    )
                    temporal_faults.append(temporal_fault)
                    halt = RunHaltRecord(
                        kind="TEMPORAL_INTEGRITY",
                        as_of=event.timestamp,
                        identity=order_id,
                        reason=temporal_fault.reason,
                    )
                    continue

                post_snapshot = build_simulated_engine_snapshot(
                    as_of=event.timestamp,
                    accounting=self._paper_executor.accounting,
                    active_orders=tuple(active_orders[key] for key in sorted(active_orders)),
                    account_state=None,
                    account_reason=(
                        "paper rehearsal does not expose authoritative current "
                        "account-state valuation"
                    ),
                )
                post_context = StrategyContext(
                    event=event,
                    ir=self._strategy_ir,
                    as_of=event.timestamp,
                    engine=post_snapshot,
                    history=history,
                )
                update = OrderUpdateFact(
                    client_order_id=order_id,
                    instrument=order.instrument,
                    status=outcome.lifecycle_status,
                    order_quantity=order.quantity,
                    filled_quantity=filled_quantity,
                    remaining_quantity=(
                        None
                        if filled_quantity is None
                        or outcome.lifecycle_status is OrderStatus.UNKNOWN
                        else order.quantity - filled_quantity
                    ),
                    created_at=order.created_at,
                    evidence_time=event.timestamp,
                    reason=update_reason,
                    effective_at=(
                        event.timestamp
                        if outcome.fill is None
                        else outcome.fill.filled_at
                    ),
                )
                faults = dispatch_post_commit_callbacks(
                    callback_target,
                    post_context,
                    () if outcome.fill is None else (outcome.fill,),
                    update,
                )
                if faults:
                    callback_faults.extend(faults)
                    halt = RunHaltRecord(
                        kind="POST_COMMIT_CALLBACK_FAILURE",
                        as_of=event.timestamp,
                        identity=faults[0].identity,
                        reason="one or more post-commit strategy callbacks failed",
                    )

            index = cohort_end

        pending_reason = (
            "run halted before timer delivery"
            if halt is not None
            else "run ended before the timer became due"
        )
        undelivered = timers.record_undelivered(pending_reason)
        return StrategyRehearsalResult(
            deployment=self._deployment,
            strategy_ir=self._strategy_ir,
            steps=tuple(steps),
            callback_faults=tuple(callback_faults),
            halt=halt,
            temporal_faults=tuple(temporal_faults),
            undelivered_timers=undelivered,
        )

    def _step(
        self,
        rehearsal_input: RehearsalInput,
        evaluation: StrategyEvaluation,
    ) -> StrategyRehearsalStep:
        event = rehearsal_input.event
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
        deterministic = replace(approved, order=replace(approved.order, created_at=event.timestamp))
        preparation = replace(preparation, request=deterministic)
        paper_outcome = self._paper_executor.execute(
            deterministic.order,
            snapshot=rehearsal_input.snapshot,
            submitted_at_ns=_event_submitted_at_ns(event),
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
