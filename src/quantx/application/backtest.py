"""Deterministic backtest application service.

The application layer composes market-data replay, strategy output, pre-trade
risk, execution policy, paper execution, and fill accounting. It contains no
broker SDK or network dependency.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from quantx.domain.enums import OrderSide, OrderType
from quantx.domain.execution_request import ApprovedExecutionRequest, build_order_from_intent
from quantx.domain.finance import AccountFinancialState, BrokerConstraint
from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.market_data import Candle
from quantx.domain.order_intents import TradeIntent
from quantx.domain.policy import ExecutionPolicyEngine, PolicyContext, PolicyDecision, PolicyResult
from quantx.domain.risk import PreTradeRiskEngine, RiskContext, RiskDecision, RiskResult
from quantx.domain.strategy import SignalAction, StrategyResult
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.historical_account_state import (
    HistoricalAccountStateSnapshot,
    HistoricalAccountStateTracker,
)
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.models import CandleFillModel, DataAdaptiveFillModel, FillModel, StopTrigger
from quantx.execution.paper import PaperExecutionEngine, PaperSimulationProfile
from quantx.execution.ports import ExecutionReceipt
from quantx.research.data import HistoricalDataSeries, HistoricalSnapshot
from quantx.research.provenance import ResearchProvenance
from quantx.research.quality import DataQualityStatus
from quantx.research.replay import HistoricalReplay, MultiSeries, ReplayFrame
from quantx.research.result import ResultQuality
from quantx.strategy.evaluation import StrategyEvaluationService
from quantx.strategy.ir import StrategyIR


class BacktestDisposition(StrEnum):
    NO_ACTION = "NO_ACTION"
    EXECUTED = "EXECUTED"
    RISK_REJECTED = "RISK_REJECTED"
    POLICY_REJECTED = "POLICY_REJECTED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    BLOCKED = "BLOCKED"


class AccountStateSamplingPolicy(StrEnum):
    EXACT_CURRENT = "EXACT_CURRENT"
    AS_OF_OBSERVED = "AS_OF_OBSERVED"


@dataclass(frozen=True, slots=True)
class BacktestStep:
    frame_index: int
    timestamp: str
    strategy_result: StrategyResult
    risk_result: RiskResult | None
    policy_result: PolicyResult | None
    receipt: ExecutionReceipt | None
    disposition: BacktestDisposition
    reason: str


@dataclass(frozen=True, slots=True)
class BacktestFidelity:
    """Experiment-level fidelity record for one deterministic backtest run.

    This reuses the research ResultQuality vocabulary: simulated fills
    derived deterministically from observed market data are
    COMPLETE_WITH_DETERMINISTIC_DERIVATIONS, while a run that declined to
    simulate something is INCOMPLETE. Observed broker execution is never
    claimed. Research-provenance inputs the backtest does not possess
    (dataset identity, code/configuration revisions) are not fabricated
    here; see ResearchProvenance for the immutable experiment identity.
    """

    quality: ResultQuality
    execution_models: tuple[str, ...]
    evidence_types: tuple[str, ...]
    deterministic: bool = True
    simulated: bool = True
    limitations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BacktestResult:
    data_quality: DataQualityStatus
    fidelity: BacktestFidelity
    steps: tuple[BacktestStep, ...]
    receipts: tuple[ExecutionReceipt, ...]
    ledger: tuple[PositionLedgerEntry, ...]
    account_states: tuple[HistoricalAccountStateSnapshot, ...] = ()
    account_state_series: tuple[HistoricalAccountStateSnapshot, ...] = ()
    account_state_sampling_policy: AccountStateSamplingPolicy = (
        AccountStateSamplingPolicy.EXACT_CURRENT
    )
    provenance: ResearchProvenance | None = None

    @property
    def executed_count(self) -> int:
        return sum(step.disposition is BacktestDisposition.EXECUTED for step in self.steps)

    @property
    def rejected_count(self) -> int:
        return sum(
            step.disposition in {
                BacktestDisposition.RISK_REJECTED,
                BacktestDisposition.POLICY_REJECTED,
                BacktestDisposition.APPROVAL_REQUIRED,
                BacktestDisposition.BLOCKED,
            }
            for step in self.steps
        )


StrategyRunner = Callable[[ReplayFrame], StrategyResult]

_MODEL_ID_PREFIX = "model_id="

_BASE_LIMITATIONS = (
    "fills are simulated executions, not observed broker executions",
    "no intrabar path is modeled",
    "no liquidity or depth is modeled",
)

_CANDLE_LIMITATIONS = (
    "candle market orders fill at the observed bar close",
    "candle limit orders use the close-cross rule only; high/low never trigger fills",
    "candle stop triggers require close confirmation; ambiguous intrabar paths are blocked",
    "stop-limit post-trigger limit ordering is unknowable from OHLCV; never filled",
)


def _evidence_types(frames: tuple[ReplayFrame, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    for frame in frames:
        snapshot = frame.observation.snapshot
        if isinstance(snapshot, Candle):
            label = "CANDLE"
        elif isinstance(snapshot, MarketSnapshot):
            label = "QUOTE"
        else:
            raise TypeError(
                f"unsupported backtest observation payload: {type(snapshot).__name__}"
            )
        if label not in ordered:
            ordered.append(label)
    return tuple(ordered)


def _execution_models(receipts: tuple[ExecutionReceipt, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    for receipt in receipts:
        if not receipt.fills:
            continue
        model_id = next(
            (
                item[len(_MODEL_ID_PREFIX):]
                for item in receipt.assumptions
                if item.startswith(_MODEL_ID_PREFIX)
            ),
            None,
        )
        if model_id is None:
            continue
        label = f"{model_id}@{receipt.model_version}"
        if label not in ordered:
            ordered.append(label)
    return tuple(ordered)


def _fidelity_limitations(
    frames: tuple[ReplayFrame, ...],
    steps: tuple[BacktestStep, ...],
    volume_participation_rate: Decimal | None = None,
    slippage_bps: Decimal | None = None,
) -> tuple[str, ...]:
    limitations = list(_BASE_LIMITATIONS)
    candle_order_types = {
        step.strategy_result.intent.order_type
        for frame, step in zip(frames, steps, strict=True)
        if isinstance(frame.observation.snapshot, Candle)
        and step.strategy_result.intent is not None
    }
    if OrderType.MARKET in candle_order_types:
        limitations.append(_CANDLE_LIMITATIONS[0])
    if OrderType.LIMIT in candle_order_types:
        limitations.append(_CANDLE_LIMITATIONS[1])
    if OrderType.STOP in candle_order_types:
        limitations.append(_CANDLE_LIMITATIONS[2])
    if OrderType.STOP_LIMIT in candle_order_types:
        limitations.append(_CANDLE_LIMITATIONS[3])
    if volume_participation_rate is not None and candle_order_types:
        limitations.append(
            "candle fills bounded by configured volume participation "
            f"(rate={volume_participation_rate}); cap is modeled, not observed liquidity"
        )
    if slippage_bps is not None and slippage_bps != 0:
        limitations.append(
            "configured deterministic slippage "
            f"(slippage_bps={slippage_bps}); modeled price adjustment, not observed liquidity"
        )
    return tuple(limitations)


def _backtest_fidelity(
    frames: tuple[ReplayFrame, ...],
    steps: tuple[BacktestStep, ...],
    receipts: tuple[ExecutionReceipt, ...],
    volume_participation_rate: Decimal | None = None,
    slippage_bps: Decimal | None = None,
) -> BacktestFidelity:
    blocked = any(step.disposition is BacktestDisposition.BLOCKED for step in steps)
    quality = (
        ResultQuality.INCOMPLETE
        if blocked
        else ResultQuality.COMPLETE_WITH_DETERMINISTIC_DERIVATIONS
    )
    return BacktestFidelity(
        quality=quality,
        execution_models=_execution_models(receipts),
        evidence_types=_evidence_types(frames),
        limitations=_fidelity_limitations(
            frames, steps, volume_participation_rate, slippage_bps
        ),
    )


def _reference_price(snapshot: MarketSnapshot | Candle) -> Decimal | None:
    if isinstance(snapshot, Candle):
        # Bar-close reference, mirroring the existing strategy execution
        # preparation contract; no quote fields are invented.
        return snapshot.close
    if isinstance(snapshot, MarketSnapshot):
        if snapshot.last is not None:
            return snapshot.last
        if snapshot.bid is not None and snapshot.ask is not None:
            return (snapshot.bid + snapshot.ask) / Decimal("2")
        return snapshot.ask if snapshot.ask is not None else snapshot.bid
    raise TypeError(f"unsupported backtest observation payload: {type(snapshot).__name__}")


def _require_coherent_provenance(
    frames: tuple[ReplayFrame, ...],
    provenance: ResearchProvenance,
) -> None:
    """Fail closed when supplied provenance cannot name the replay evidence.

    The backtest has no catalog dependency, so dataset identity is a caller
    declaration. The only honest check available is coherence with the
    observation-carried evidence: all frames must share exactly one
    (source_id, dataset_version) pair, and the declared dataset_version must
    match it. Heterogeneous multi-dataset provenance binding is explicitly
    deferred, never silently merged.
    """
    pairs = {(frame.observation.source_id, frame.observation.dataset_version) for frame in frames}
    if len(pairs) != 1:
        raise ValueError(
            "provenance binding requires replay evidence from exactly one dataset; "
            f"observed {len(pairs)} distinct (source_id, dataset_version) pairs"
        )
    if next(iter(pairs))[1] != provenance.dataset_version:
        raise ValueError("supplied provenance dataset_version does not match replay evidence")


class DeterministicBacktestService:
    """Run a strategy over historical observations without vendor dependencies."""

    def __init__(
        self,
        *,
        instrument_registry: InstrumentRegistry,
        risk_engine: PreTradeRiskEngine | None = None,
        policy_engine: ExecutionPolicyEngine | None = None,
        execution_engine: PaperExecutionEngine | None = None,
        accounting: FillAccounting | None = None,
    ) -> None:
        self._instrument_registry = instrument_registry
        self._risk_engine = risk_engine or PreTradeRiskEngine()
        self._policy_engine = policy_engine or ExecutionPolicyEngine()
        self._execution_engine = execution_engine
        self._accounting_override = accounting

    @staticmethod
    def _validate_strategy_result(strategy_result: StrategyResult, frame: ReplayFrame) -> None:
        signal = strategy_result.signal
        if signal.instrument != frame.observation.instrument:
            raise ValueError("strategy signal instrument does not match replay frame")
        if signal.generated_at != frame.observation.timestamp:
            raise ValueError("strategy signal timestamp does not match replay frame")
        intent = strategy_result.intent
        if intent is None:
            return
        if intent.instrument != frame.observation.instrument:
            raise ValueError("strategy intent instrument does not match replay frame")
        if intent.strategy_id != signal.strategy_id.value:
            raise ValueError("strategy intent id does not match strategy signal")
        if intent.strategy_version != signal.strategy_version:
            raise ValueError("strategy intent version does not match strategy signal")
        if signal.action is SignalAction.HOLD:
            raise ValueError("HOLD signal cannot carry an executable intent")
        if signal.action is SignalAction.BUY and intent.side is not OrderSide.BUY:
            raise ValueError("BUY signal must carry a BUY intent")
        if signal.action is SignalAction.SELL and intent.side is not OrderSide.SELL:
            raise ValueError("SELL signal must carry a SELL intent")

    @staticmethod
    def _candle_stop_disposition(
        intent: TradeIntent, snapshot: HistoricalSnapshot
    ) -> str | None:
        """Block candle stop orders whose outcome OHLCV cannot establish.

        A stop whose trigger the observed bar cannot confirm would need an
        invented intrabar path to price; a stop-limit additionally needs an
        unknowable post-trigger limit ordering. Both stop here with an
        explicit reason instead of a fabricated fill.
        """
        if not isinstance(snapshot, Candle):
            return None
        if intent.order_type is OrderType.STOP:
            if intent.stop_price is None:
                return "stop price is required for stop orders"
            if (
                CandleFillModel.classify_stop(intent.side, intent.stop_price, snapshot)
                is StopTrigger.AMBIGUOUS
            ):
                return "stop trigger intrabar path is unknowable from OHLCV; no simulated fill"
            return None
        if intent.order_type is OrderType.STOP_LIMIT:
            if intent.stop_price is None:
                return "stop price is required for stop-limit orders"
            trigger = CandleFillModel.classify_stop(intent.side, intent.stop_price, snapshot)
            if trigger is StopTrigger.AMBIGUOUS:
                return "stop-limit intrabar path is unknowable from OHLCV; no fill simulated"
            if trigger is StopTrigger.TRIGGERED:
                return (
                    "stop triggered but post-trigger limit execution ordering "
                    "is unknowable from OHLCV; no simulated fill"
                )
            return None
        return None

    def run(
        self,
        *,
        series: HistoricalDataSeries | MultiSeries,
        strategy: StrategyRunner | StrategyEvaluationService,
        financial_state: AccountFinancialState,
        strategy_ir: StrategyIR | None = None,
        policy_context: PolicyContext | None = None,
        broker_constraints: tuple[BrokerConstraint, ...] = (),
        allow_incomplete: bool = False,
        execution_profile: PaperSimulationProfile | None = None,
        candle_volume_participation_rate: Decimal | None = None,
        account_state_sampling_policy: AccountStateSamplingPolicy = (
            AccountStateSamplingPolicy.EXACT_CURRENT
        ),
        provenance: ResearchProvenance | None = None,
    ) -> BacktestResult:
        replay = HistoricalReplay(series, allow_incomplete=allow_incomplete)
        frames = replay.frames()
        if provenance is not None:
            _require_coherent_provenance(frames, provenance)
        execution_engine = self._execution_engine
        simulation_clock = None
        effective_slippage_bps: Decimal | None = None
        if execution_engine is None:
            from quantx.domain.clock import SimulatedClock

            first_timestamp = frames[0].observation.timestamp
            simulation_clock = SimulatedClock(first_timestamp)
            effective_profile = execution_profile or PaperSimulationProfile()
            effective_slippage_bps = effective_profile.slippage_bps
            candle_model: FillModel = CandleFillModel(
                volume_participation_rate=candle_volume_participation_rate
            )
            execution_engine = PaperExecutionEngine(
                clock=simulation_clock,
                profile=effective_profile,
                fill_model=DataAdaptiveFillModel(candle_model=candle_model),
            )

        effective_policy = policy_context or PolicyContext()
        accounting = self._accounting_override or FillAccounting()
        steps: list[BacktestStep] = []
        receipts: list[ExecutionReceipt] = []
        account_state_tracker = HistoricalAccountStateTracker(
            financial_state,
            accounting=accounting,
            instrument_registry=self._instrument_registry,
        )
        account_states: list[HistoricalAccountStateSnapshot] = []
        account_state_series: list[HistoricalAccountStateSnapshot] = []

        for frame in frames:
            account_state_tracker.observe_mark(frame.observation.snapshot)
            account_state_series.append(
                account_state_tracker.snapshot_at(
                    frame.observation.timestamp,
                    require_current_marks=(
                        account_state_sampling_policy is AccountStateSamplingPolicy.EXACT_CURRENT
                    ),
                )
            )
            if isinstance(strategy, StrategyEvaluationService):
                if strategy_ir is None:
                    raise ValueError("strategy_ir is required for StrategyEvaluationService")
                strategy_result = strategy.evaluate_replay_frame(frame, strategy_ir).result
            else:
                strategy_result = strategy(frame)
            self._validate_strategy_result(strategy_result, frame)
            intent = strategy_result.intent
            timestamp = frame.observation.timestamp.isoformat()

            if intent is None or strategy_result.signal.action in {SignalAction.HOLD}:
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        strategy_result,
                        None,
                        None,
                        None,
                        BacktestDisposition.NO_ACTION,
                        "strategy produced no executable intent",
                    )
                )
                continue

            instrument = self._instrument_registry.resolve(frame.observation.instrument)
            if instrument is None:
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        strategy_result,
                        None,
                        None,
                        None,
                        BacktestDisposition.BLOCKED,
                        f"instrument metadata unavailable for {frame.observation.instrument}",
                    )
                )
                continue

            if intent.execution_context is None:
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        strategy_result,
                        None,
                        None,
                        None,
                        BacktestDisposition.BLOCKED,
                        "execution context is required",
                    )
                )
                continue

            if strategy_result.signal.instrument != frame.observation.instrument:
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        strategy_result,
                        None,
                        None,
                        None,
                        BacktestDisposition.BLOCKED,
                        "strategy signal instrument does not match replay frame",
                    )
                )
                continue

            if intent.instrument != frame.observation.instrument:
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        strategy_result,
                        None,
                        None,
                        None,
                        BacktestDisposition.BLOCKED,
                        "strategy intent instrument does not match replay frame",
                    )
                )
                continue

            if intent.execution_context.market != instrument.market:
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        strategy_result,
                        None,
                        None,
                        None,
                        BacktestDisposition.BLOCKED,
                        "strategy intent market does not match canonical instrument",
                    )
                )
                continue

            risk = self._risk_engine.evaluate(
                intent,
                RiskContext(
                    instrument=instrument,
                    financial_state=financial_state,
                    broker_constraints=broker_constraints,
                    reference_price=_reference_price(frame.observation.snapshot),
                ),
            )
            if risk.decision is not RiskDecision.APPROVE:
                disposition = (
                    BacktestDisposition.APPROVAL_REQUIRED
                    if risk.decision is RiskDecision.APPROVAL_REQUIRED
                    else BacktestDisposition.RISK_REJECTED
                )
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        strategy_result,
                        risk,
                        None,
                        None,
                        disposition,
                        risk.reason,
                    )
                )
                continue

            policy = self._policy_engine.evaluate(intent, effective_policy)
            if not policy.approved:
                disposition = (
                    BacktestDisposition.APPROVAL_REQUIRED
                    if policy.decision is PolicyDecision.APPROVAL_REQUIRED
                    else BacktestDisposition.POLICY_REJECTED
                )
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        strategy_result,
                        risk,
                        policy,
                        None,
                        disposition,
                        policy.reason,
                    )
                )
                continue

            snapshot = frame.observation.snapshot
            blocked_reason = self._candle_stop_disposition(intent, snapshot)
            if blocked_reason is not None:
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        strategy_result,
                        risk,
                        policy,
                        None,
                        BacktestDisposition.BLOCKED,
                        blocked_reason,
                    )
                )
                continue

            if simulation_clock is not None:
                simulation_clock.set_time(frame.observation.timestamp)
            request: ApprovedExecutionRequest = ApprovedExecutionRequest(
                order=build_order_from_intent(intent),
                execution_context=intent.execution_context,
                risk_result=risk,
                policy_result=policy,
            )
            receipt = execution_engine.execute(
                request,
                snapshot=snapshot,
            )
            receipts.append(receipt)
            account_states.append(
                account_state_tracker.record(receipt, snapshot=snapshot)
            )

            steps.append(
                BacktestStep(
                    frame.index,
                    timestamp,
                    strategy_result,
                    risk,
                    policy,
                    receipt,
                    BacktestDisposition.EXECUTED,
                    receipt.message or receipt.outcome.value,
                )
            )

        frames_tuple = tuple(frames)
        steps_tuple = tuple(steps)
        receipts_tuple = tuple(receipts)
        return BacktestResult(
            data_quality=replay.quality.status,
            fidelity=_backtest_fidelity(
            frames_tuple,
            steps_tuple,
            receipts_tuple,
            candle_volume_participation_rate,
            effective_slippage_bps,
        ),
            steps=steps_tuple,
            receipts=receipts_tuple,
            ledger=accounting.snapshot(),
            account_states=tuple(account_states),
            account_state_series=tuple(account_state_series),
            account_state_sampling_policy=account_state_sampling_policy,
            provenance=provenance,
        )
