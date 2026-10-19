"""Deterministic backtest application service.

The application layer composes market-data replay, strategy output, pre-trade
risk, execution policy, paper execution, and fill accounting. It contains no
broker SDK or network dependency.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from quantx.application.strategy_preflight import assess_backtest_event_time_support
from quantx.domain.clock import SimulatedClock
from quantx.domain.deployment import ExecutionContext, ExecutionMode
from quantx.domain.enums import OrderSide, OrderStatus, OrderType, PositionEffect
from quantx.domain.execution_request import (
    ApprovedExecutionRequest,
    build_order_from_intent,
)
from quantx.domain.finance import AccountFinancialState, BrokerConstraint
from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.market_data import Candle
from quantx.domain.order_intents import TradeIntent
from quantx.domain.orders import Order
from quantx.domain.policy import (
    ExecutionPolicyEngine,
    PolicyContext,
    PolicyDecision,
    PolicyResult,
)
from quantx.domain.position_effect import PositionEvidence, resolve_position_effect
from quantx.domain.product_selection import ProductSelectionPolicy, resolve_request_product
from quantx.domain.risk import PreTradeRiskEngine, RiskContext, RiskDecision, RiskResult
from quantx.domain.strategy import SignalAction, StrategyResult
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.charges import PercentageBpsChargeModel
from quantx.execution.historical_account_state import (
    AccountStateCompleteness,
    HistoricalAccountStateSnapshot,
    HistoricalAccountStateTracker,
)
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.models import (
    CandleFillModel,
    DataAdaptiveFillModel,
    FillModel,
    QuoteFillModel,
    SlippageModel,
    StopTrigger,
)
from quantx.execution.paper import PaperExecutionEngine, PaperSimulationProfile
from quantx.execution.ports import ExecutionReceipt
from quantx.research.data import HistoricalDataSeries, HistoricalSnapshot
from quantx.research.provenance import (
    BrokerConstraintConfiguration,
    ExecutionConfiguration,
    PolicyConfiguration,
    ResearchProvenance,
    ResearchRunConfiguration,
    SimulationModelIdentity,
    StartingCapitalConfiguration,
    StrategyConfiguration,
)
from quantx.research.quality import DataQualityStatus
from quantx.research.replay import HistoricalReplay, MultiSeries, ReplayFrame
from quantx.research.result import ResultQuality
from quantx.strategy.callbacks import (
    CallbackFault,
    OrderUpdateFact,
    RunHaltRecord,
    TemporalIntegrityFault,
    callback_fault,
    dispatch_post_commit_callbacks,
    dispatch_timer_callback,
)
from quantx.strategy.context import StrategyContext
from quantx.strategy.engine_snapshot import (
    OpenOrderFact,
    active_order_fact,
    build_simulated_engine_snapshot,
    prior_candle_history,
)
from quantx.strategy.evaluation import StrategyEvaluation, StrategyEvaluationService
from quantx.strategy.ir import StrategyIR
from quantx.strategy.timers import TimerRegistry, UndeliveredTimer
from quantx.strategy.typed_params import TypedParams


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
    strategy_result: StrategyResult | None
    risk_result: RiskResult | None
    policy_result: PolicyResult | None
    receipt: ExecutionReceipt | None
    disposition: BacktestDisposition
    reason: str
    faults: tuple[CallbackFault, ...] = ()


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
    callback_faults: tuple[CallbackFault, ...] = ()
    halt: RunHaltRecord | None = None
    temporal_faults: tuple[TemporalIntegrityFault, ...] = ()
    undelivered_timers: tuple[UndeliveredTimer, ...] = ()

    @property
    def executed_count(self) -> int:
        return sum(step.disposition is BacktestDisposition.EXECUTED for step in self.steps)

    @property
    def rejected_count(self) -> int:
        return sum(
            step.disposition
            in {
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
            raise TypeError(f"unsupported backtest observation payload: {type(snapshot).__name__}")
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
                item[len(_MODEL_ID_PREFIX) :]
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
        if (
            isinstance(frame.observation.snapshot, Candle)
            and step.strategy_result is not None
            and step.strategy_result.intent is not None
        )
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
            f"(rate={volume_participation_rate}); cap is modeled, not observed "
            "liquidity"
        )
    if slippage_bps is not None and slippage_bps != 0:
        limitations.append(
            "configured deterministic slippage "
            f"(slippage_bps={slippage_bps}); modeled price adjustment, not observed "
            "liquidity"
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
        limitations=_fidelity_limitations(frames, steps, volume_participation_rate, slippage_bps),
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


def _require_coherent_run_configuration(
    effective: ResearchRunConfiguration,
    declared: ResearchRunConfiguration,
) -> None:
    """Fail closed when declared run configuration is not the effective one.

    The backtest is authoritative about the configuration it actually used.
    A declared configuration that differs from the effective one cannot describe
    the run, so the run fails instead of claiming a reproducible identity.
    """
    if effective.canonical_payload() != declared.canonical_payload():
        raise ValueError(
            "declared research run configuration does not match the effective "
            "backtest configuration"
        )


def _effective_run_configuration(
    *,
    strategy: StrategyRunner | StrategyEvaluationService,
    strategy_ir: StrategyIR | None,
    profile: PaperSimulationProfile,
    execution_models: tuple[SimulationModelIdentity, ...] | None,
    candle_volume_participation_rate: Decimal | None,
    allow_incomplete: bool,
    account_state_sampling_policy: AccountStateSamplingPolicy,
    policy_context: PolicyContext,
    broker_constraints: tuple[BrokerConstraint, ...],
    financial_state: AccountFinancialState,
) -> ResearchRunConfiguration:
    """Derive the effective, canonical run configuration of one backtest run.

    Only authoritative, service-owned knowledge is captured. Strategy identity
    comes from ``StrategyIR`` when the run uses the runtime-neutral evaluation
    service. A bare callable exposes no canonical strategy configuration, so it
    fails closed here rather than being introspected or invented.
    """
    if isinstance(strategy, StrategyEvaluationService) and strategy_ir is not None:
        strategy_configuration = StrategyConfiguration(
            strategy_id=strategy_ir.strategy_id.value,
            strategy_version=strategy_ir.version,
            strategy_parameters=tuple(strategy_ir.parameters),
        )
    else:
        raise ValueError(
            "structured run configuration requires authoritative strategy identity; "
            "a bare strategy callable exposes no canonical configuration"
        )

    if execution_models is None:
        raise ValueError(
            "structured run configuration requires authoritative execution-model "
            "identity; the injected execution engine exposes no explicit canonical "
            "configuration contract"
        )

    effective_slippage = SlippageModel(profile.slippage_bps)
    slippage_model = (
        SimulationModelIdentity(
            model_id=effective_slippage.model_id,
            model_version=effective_slippage.model_version,
            parameters=(("basis_points", str(effective_slippage.basis_points)),),
        )
        if profile.slippage_bps != Decimal("0")
        else None
    )
    charge_model = profile.charge_model
    if charge_model is None:
        charge_identity: SimulationModelIdentity | None = None
    elif isinstance(charge_model, PercentageBpsChargeModel):
        charge_identity = SimulationModelIdentity(
            model_id=charge_model.model_id,
            model_version=charge_model.model_version,
            parameters=(
                ("component_name", charge_model.component_name),
                ("rate_bps", str(charge_model.rate_bps)),
            ),
        )
    else:
        # A real charge model without an explicit canonical material-parameter
        # representation must never be recorded as "no charge model": doing so
        # would let a material cost model look like an absent one.
        raise ValueError(
            "charge model exposes no canonical material-parameter representation "
            "and cannot be recorded in structured run configuration"
        )

    execution_configuration = ExecutionConfiguration(
        simulation_profile_name=profile.name,
        latency_ms=profile.latency_ms,
        slippage_bps=profile.slippage_bps,
        partial_fill_ratio=profile.partial_fill_ratio,
        fee_bps=profile.fee_bps,
        execution_models=execution_models,
        volume_participation_rate=candle_volume_participation_rate,
        slippage_model=slippage_model,
        charge_model=charge_identity,
    )

    return ResearchRunConfiguration(
        strategy=strategy_configuration,
        execution=execution_configuration,
        allow_incomplete=allow_incomplete,
        account_state_sampling_policy=account_state_sampling_policy.value,
        policy=PolicyConfiguration(
            granted_capabilities=tuple(sorted(policy_context.granted_capabilities)),
            live_trading_enabled=policy_context.live_trading_enabled,
            manual_approval=policy_context.manual_approval,
        ),
        broker_constraints=tuple(
            BrokerConstraintConfiguration(
                name=constraint.name,
                minimum_order_value=constraint.minimum_order_value,
                minimum_quantity=constraint.minimum_quantity,
                minimum_margin_amount=(
                    None if constraint.minimum_margin is None else constraint.minimum_margin.amount
                ),
                minimum_margin_currency=(
                    None
                    if constraint.minimum_margin is None
                    else constraint.minimum_margin.currency
                ),
            )
            for constraint in sorted(broker_constraints, key=lambda item: item.name)
        ),
        starting_capital=StartingCapitalConfiguration(
            capital_source=financial_state.capital_source.value,
            currency=financial_state.cash_balance.currency,
            cash_balance=financial_state.cash_balance.amount,
            available_cash=financial_state.available_cash.amount,
            blocked_cash=financial_state.blocked_cash.amount,
            margin_used=financial_state.margin_used.amount,
            margin_available=financial_state.margin_available.amount,
            buying_power=financial_state.buying_power.amount,
        ),
    )


def _require_coherent_provenance(
    frames: tuple[ReplayFrame, ...],
    provenance: ResearchProvenance,
) -> None:
    """Fail closed when supplied provenance cannot name the replay evidence.

    The backtest has no catalog dependency, so dataset identity is a caller
    declaration. The only honest check available is coherence with the
    observation-carried evidence: all frames must share exactly one logical
    (dataset_id, dataset_version) pair, and that pair must equal the declared
    provenance identity. ``source_id`` is provider identity and is never
    compared against ``dataset_id``: different sources remain valid when the
    logical dataset identity and version agree. No normalization, aliasing,
    inference, or catalog lookup is attempted. Heterogeneous multi-dataset
    provenance binding is explicitly deferred, never silently merged.
    """
    pairs = {(frame.observation.dataset_id, frame.observation.dataset_version) for frame in frames}
    if len(pairs) != 1:
        raise ValueError(
            "provenance binding requires replay evidence from exactly one dataset; "
            f"observed {len(pairs)} distinct (dataset_id, dataset_version) pairs"
        )
    observed_id, observed_version = next(iter(pairs))
    if observed_id != provenance.dataset_id:
        raise ValueError("supplied provenance dataset_id does not match replay evidence")
    if observed_version != provenance.dataset_version:
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
        product_selection: ProductSelectionPolicy | None = None,
    ) -> None:
        self._instrument_registry = instrument_registry
        self._risk_engine = risk_engine or PreTradeRiskEngine()
        self._policy_engine = policy_engine or ExecutionPolicyEngine()
        self._execution_engine = execution_engine
        self._accounting_override = accounting
        self._product_selection = product_selection

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
    def _require_coherent_execution_time(order: Order, receipt: ExecutionReceipt) -> None:
        """Detect residual clock divergence after execution.

        Backstop for the pre-execution check above: it covers a clock that
        moves between validation and execution, or an engine that stamps
        from a different source than its exposed clock. This exception does
        not roll back venue state already written by the engine — it aborts
        the run so contradictory evidence is never recorded in the
        backtest result. Prevention lives in the preflight check; this is
        detection only.
        """
        if receipt.executed_at < order.created_at:
            raise ValueError(
                "injected execution clock predates the replay frame: "
                "receipt execution precedes order creation"
            )
        for fill in receipt.fills:
            if fill.filled_at < order.created_at:
                raise ValueError(
                    "injected execution clock predates the replay frame: "
                    "fill precedes order creation"
                )

    @staticmethod
    def _require_engine_time_coherent(
        execution_engine: PaperExecutionEngine, frame_time: datetime
    ) -> datetime:
        """Fail closed before execution unless the engine clock is replay-safe.

        Reading the injected clock up front keeps a rejected run free of venue
        side effects: no idempotency reservation, no receipt write, no retained
        receipt, no lifecycle events. Only an explicitly deterministic clock is
        admitted — wall-clock time can never be replay evidence, even when it
        currently reads ahead of the frame. A deterministic clock behind the
        replay frame can never produce coherent evidence either, so the run
        aborts before executing. Monotonic forward movement between this read
        and execution cannot break coherence, only increase the margin.
        """
        engine_clock = execution_engine.clock
        if not engine_clock.is_deterministic:
            raise ValueError(
                "injected execution clock must be deterministic for replay: "
                "wall-clock time cannot back replay evidence"
            )
        engine_now = engine_clock.now()
        if engine_now.tzinfo is None or engine_now.utcoffset() is None:
            raise ValueError("injected execution clock must return a timezone-aware timestamp")
        if engine_now < frame_time:
            raise ValueError(
                "injected execution clock predates the replay frame: "
                "execution cannot precede the replay occurrence time"
            )
        return engine_now

    @staticmethod
    def _candle_stop_disposition(intent: TradeIntent, snapshot: HistoricalSnapshot) -> str | None:
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
        execution_context: ExecutionContext | None = None,
        policy_context: PolicyContext | None = None,
        broker_constraints: tuple[BrokerConstraint, ...] = (),
        allow_incomplete: bool = False,
        execution_profile: PaperSimulationProfile | None = None,
        candle_volume_participation_rate: Decimal | None = None,
        account_state_sampling_policy: AccountStateSamplingPolicy = (
            AccountStateSamplingPolicy.EXACT_CURRENT
        ),
        provenance: ResearchProvenance | None = None,
        position_evidence: PositionEvidence | None = None,
        position_evidence_max_age: timedelta | None = None,
    ) -> BacktestResult:
        """Run replay; bind the explicit context only to bare QX-08 strategy intents.

        The supplied context is caller-owned simulated execution authority. Existing
        intent contexts remain unchanged, and the legacy callable strategy path is
        unaffected.
        """
        replay = HistoricalReplay(series, allow_incomplete=allow_incomplete)
        frames = replay.frames()
        if provenance is not None:
            _require_coherent_provenance(frames, provenance)
        execution_engine = self._execution_engine
        simulation_clock = None
        effective_slippage_bps: Decimal | None = None
        effective_profile = execution_profile or PaperSimulationProfile()
        # ``None`` means "no authoritative identity available". An injected
        # execution engine stays ``None`` so provenance-aware validation fails
        # closed instead of recording an empty model list.
        effective_execution_models: tuple[SimulationModelIdentity, ...] | None = None
        if execution_engine is None:
            first_timestamp = frames[0].observation.timestamp
            simulation_clock = SimulatedClock(first_timestamp)
            effective_slippage_bps = effective_profile.slippage_bps
            configured_candle_model = CandleFillModel(
                volume_participation_rate=candle_volume_participation_rate
            )
            # The service owns these routes, so their identities are authoritative.
            effective_execution_models = tuple(
                sorted(
                    (
                        SimulationModelIdentity(
                            model_id=QuoteFillModel.model_id,
                            model_version=QuoteFillModel.model_version,
                        ),
                        SimulationModelIdentity(
                            model_id=configured_candle_model.model_id,
                            model_version=configured_candle_model.model_version,
                        ),
                    ),
                    key=lambda item: (item.model_id, item.model_version),
                )
            )
            candle_model: FillModel = configured_candle_model
            execution_engine = PaperExecutionEngine(
                clock=simulation_clock,
                profile=effective_profile,
                fill_model=DataAdaptiveFillModel(candle_model=candle_model),
            )

        effective_policy = policy_context or PolicyContext()
        if provenance is not None and provenance.run_configuration is not None:
            _require_coherent_run_configuration(
                _effective_run_configuration(
                    strategy=strategy,
                    strategy_ir=strategy_ir,
                    profile=effective_profile,
                    execution_models=effective_execution_models,
                    candle_volume_participation_rate=candle_volume_participation_rate,
                    allow_incomplete=allow_incomplete,
                    account_state_sampling_policy=account_state_sampling_policy,
                    policy_context=effective_policy,
                    broker_constraints=broker_constraints,
                    financial_state=financial_state,
                ),
                provenance.run_configuration,
            )
        qx08_active = isinstance(strategy, StrategyEvaluationService)
        if execution_context is not None and not qx08_active:
            raise ValueError("execution_context binding requires StrategyEvaluationService")
        if (
            qx08_active
            and execution_context is not None
            and execution_context.execution_mode
            not in {ExecutionMode.PAPER, ExecutionMode.SHADOW, ExecutionMode.REPLAY}
        ):
            raise ValueError("QX-08 backtest execution context must use a supported simulated mode")
        callback_target: object = strategy
        if isinstance(strategy, StrategyEvaluationService):
            if strategy_ir is None:
                raise ValueError("strategy_ir is required for StrategyEvaluationService")
            assess_backtest_event_time_support(
                execution_engine,
                internally_composed=self._execution_engine is None,
                configured_latency_ms=effective_profile.latency_ms,
            ).require_supported()
            first_frame_time = frames[0].observation.timestamp
            initial_engine_time = self._require_engine_time_coherent(
                execution_engine,
                first_frame_time,
            )
            if initial_engine_time != first_frame_time:
                raise ValueError(
                    "QX-08 event-time preflight requires the injected execution clock "
                    "to start at the first replay frame"
                )
            history_limit = TypedParams.from_ir(strategy_ir).get_int(
                "history_bars", default=0, minimum=0, maximum=512
            )
            callback_target = strategy.callback_target
        else:
            history_limit = 0

        timers = TimerRegistry()
        active_orders: dict[str, OpenOrderFact] = {}
        callback_faults: list[CallbackFault] = []
        temporal_faults: list[TemporalIntegrityFault] = []
        halt: RunHaltRecord | None = None
        current_cohort_time: datetime | None = None
        blocked_cohort_time: datetime | None = None
        cohort_timer_faults: tuple[CallbackFault, ...] = ()
        cohort_timer_faults_attached = False
        candle_history = tuple(
            frame.observation.snapshot
            for frame in frames
            if isinstance(frame.observation.snapshot, Candle)
        )

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
            frame_time = frame.observation.timestamp
            timestamp = frame_time.isoformat()
            if halt is not None:
                # Halted frames are recorded as blocked, but not sampled into a
                # later account-state trajectory.
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        None,
                        None,
                        None,
                        None,
                        BacktestDisposition.BLOCKED,
                        f"run halted: {halt.reason}",
                    )
                )
                continue

            if qx08_active and simulation_clock is None:
                identity = f"{frame_time.isoformat()}:{frame.observation.instrument}"
                try:
                    engine_time = self._require_engine_time_coherent(execution_engine, frame_time)
                    if engine_time != frame_time:
                        raise ValueError(
                            "injected execution clock must align exactly "
                            "with the current replay frame for QX-08 callbacks"
                        )
                except Exception as exc:
                    reason = (
                        "execution event-time alignment failed before "
                        f"strategy evaluation: {type(exc).__name__}: {exc}"
                    )
                    fault = callback_fault(
                        "event_time_alignment",
                        identity,
                        ValueError(reason),
                    )
                    callback_faults.append(fault)
                    halt = RunHaltRecord(
                        kind="EVENT_TIME_SUPPORT_VIOLATION",
                        as_of=frame_time,
                        identity=identity,
                        reason=reason,
                    )
                    steps.append(
                        BacktestStep(
                            frame.index,
                            timestamp,
                            None,
                            None,
                            None,
                            None,
                            BacktestDisposition.BLOCKED,
                            reason,
                            (fault,),
                        )
                    )
                    continue

            if current_cohort_time != frame_time:
                current_cohort_time = frame_time
                blocked_cohort_time = None
                cohort_timer_faults = ()
                cohort_timer_faults_attached = False
                if isinstance(strategy, StrategyEvaluationService):
                    assert strategy_ir is not None
                    due_faults: list[CallbackFault] = []
                    for timer in timers.take_due(frame_time):
                        if simulation_clock is not None:
                            simulation_clock.set_time(timer.due_at)
                        try:
                            timer_account = account_state_tracker.snapshot_at(
                                timer.due_at,
                                require_current_marks=(
                                    account_state_sampling_policy
                                    is AccountStateSamplingPolicy.EXACT_CURRENT
                                ),
                            )
                            timer_engine = build_simulated_engine_snapshot(
                                as_of=timer.due_at,
                                accounting=accounting,
                                active_orders=tuple(
                                    active_orders[key] for key in sorted(active_orders)
                                ),
                                account_state=timer_account,
                            )
                            timer_history = prior_candle_history(
                                candle_history,
                                instrument=timer.instrument,
                                as_of=timer.due_at,
                                limit=history_limit,
                            )
                            timer_context = StrategyContext(
                                event=None,
                                ir=strategy_ir,
                                as_of=timer.due_at,
                                engine=timer_engine,
                                history=timer_history,
                            )
                            timer_fault = dispatch_timer_callback(
                                callback_target, timer_context, timer
                            )
                        except Exception as exc:
                            timer_fault = callback_fault("on_timer_context", timer.timer_id, exc)
                        if timer_fault is not None:
                            due_faults.append(timer_fault)
                            callback_faults.append(timer_fault)
                    if simulation_clock is not None:
                        simulation_clock.set_time(frame_time)
                    if due_faults:
                        blocked_cohort_time = frame_time
                        cohort_timer_faults = tuple(due_faults)

            if blocked_cohort_time == frame_time:
                account_state_series.append(
                    account_state_tracker.snapshot_at(
                        frame_time,
                        require_current_marks=(
                            account_state_sampling_policy
                            is AccountStateSamplingPolicy.EXACT_CURRENT
                        ),
                    )
                )
                step_faults = () if cohort_timer_faults_attached else cohort_timer_faults
                cohort_timer_faults_attached = True
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        None,
                        None,
                        None,
                        None,
                        BacktestDisposition.BLOCKED,
                        "timestamp cohort blocked because a due timer callback failed",
                        step_faults,
                    )
                )
                continue

            account_state_tracker.observe_mark(frame.observation.snapshot)
            pre_account_state = account_state_tracker.snapshot_at(
                frame_time,
                require_current_marks=(
                    account_state_sampling_policy is AccountStateSamplingPolicy.EXACT_CURRENT
                ),
            )
            account_state_series.append(pre_account_state)

            strategy_evaluation: StrategyEvaluation | None = None
            strategy_result: StrategyResult
            if isinstance(strategy, StrategyEvaluationService):
                try:
                    assert strategy_ir is not None
                    market_engine = build_simulated_engine_snapshot(
                        as_of=frame_time,
                        accounting=accounting,
                        active_orders=tuple(active_orders[key] for key in sorted(active_orders)),
                        account_state=pre_account_state,
                    )
                    history = prior_candle_history(
                        candle_history,
                        instrument=frame.observation.instrument,
                        as_of=frame_time,
                        limit=history_limit,
                    )
                    assert isinstance(strategy, StrategyEvaluationService)
                    strategy_evaluation = strategy.evaluate_replay_frame(
                        frame,
                        strategy_ir,
                        engine=market_engine,
                        history=history,
                    )
                    strategy_result = strategy_evaluation.result
                    self._validate_strategy_result(strategy_result, frame)
                    timers.register_result(strategy_result, strategy_evaluation.event)
                except Exception as exc:
                    fault = callback_fault(
                        "on_market_data",
                        f"{frame_time.isoformat()}:{frame.observation.instrument}",
                        exc,
                    )
                    callback_faults.append(fault)
                    steps.append(
                        BacktestStep(
                            frame.index,
                            timestamp,
                            None,
                            None,
                            None,
                            None,
                            BacktestDisposition.BLOCKED,
                            f"pre-commit strategy step failed: {fault.message}",
                            (fault,),
                        )
                    )
                    continue
            else:
                strategy_result = strategy(frame)
                self._validate_strategy_result(strategy_result, frame)
                if strategy_result.timers:
                    raise ValueError("timer requests require StrategyEvaluationService context")

            intent = strategy_result.intent
            if (
                qx08_active
                and intent is not None
                and intent.execution_context is None
                and execution_context is not None
            ):
                # Mirror rehearsal's deployment-owned binding for bare intents,
                # while keeping the chosen execution authority explicit at the
                # backtest call site. Existing intent contexts are left untouched.
                intent = replace(intent, execution_context=execution_context)
                strategy_result = replace(strategy_result, intent=intent)

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

            failure_identity = f"{timestamp}:{frame.observation.instrument}"
            try:
                # Pre-approval resolution: product and position effect are
                # fixed before risk/policy, then used unchanged to build the
                # approved request. No later stage resolves them again.
                product, resolved_context = resolve_request_product(
                    intent.execution_context,
                    explicit_product=intent.product,
                    policy=self._product_selection,
                )
                resolved_intent = replace(
                    intent,
                    product=product,
                    execution_context=resolved_context,
                )
                # The order always carries the explicit replay occurrence time,
                # including on the caller-supplied engine path: the wall-clock
                # default must never reach replay evidence, and the service must
                # not silently rewrite the caller's own execution clock.
                order = replace(
                    build_order_from_intent(resolved_intent),
                    created_at=frame.observation.timestamp,
                )
                effective_position_effect: PositionEffect | None = None
                position_evidence_cut: datetime | None = None
                evidence: PositionEvidence | None = None
                evidence_max_age: timedelta | None = None
                if resolved_intent.position_effect in {PositionEffect.CLOSE, PositionEffect.AUTO}:
                    evidence = position_evidence
                    evidence_max_age = position_evidence_max_age
                    if evidence_max_age is None:
                        raise ValueError(
                            f"{resolved_intent.position_effect.value} position effect "
                            "requires a position evidence freshness policy"
                        )
                    resolution = resolve_position_effect(
                        order,
                        evidence=evidence,
                        max_evidence_age=evidence_max_age,
                    )
                    effective_position_effect = resolution.effective
                    position_evidence_cut = resolution.evidence_cut
                elif position_evidence is not None or position_evidence_max_age is not None:
                    raise ValueError(
                        "position evidence is only valid for AUTO or CLOSE position effects"
                    )
            except Exception as exc:
                if not qx08_active:
                    raise
                fault = callback_fault("approval_resolution", failure_identity, exc)
                callback_faults.append(fault)
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        strategy_result,
                        None,
                        None,
                        None,
                        BacktestDisposition.BLOCKED,
                        f"pre-commit approval resolution failed: {fault.message}",
                        (fault,),
                    )
                )
                continue
            intent = resolved_intent
            try:
                risk = self._risk_engine.evaluate(
                    intent,
                    RiskContext(
                        instrument=instrument,
                        financial_state=financial_state,
                        broker_constraints=broker_constraints,
                        reference_price=_reference_price(frame.observation.snapshot),
                        product=product,
                        effective_position_effect=effective_position_effect,
                        market_pack_id=resolved_context.market_pack_id,
                        rule_version=resolved_context.rule_version,
                    ),
                )
            except Exception as exc:
                if not qx08_active:
                    raise
                fault = callback_fault("risk_preparation", failure_identity, exc)
                callback_faults.append(fault)
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        strategy_result,
                        None,
                        None,
                        None,
                        BacktestDisposition.BLOCKED,
                        f"pre-commit risk preparation failed: {fault.message}",
                        (fault,),
                    )
                )
                continue
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

            try:
                policy = self._policy_engine.evaluate(intent, effective_policy)
            except Exception as exc:
                if not qx08_active:
                    raise
                fault = callback_fault("policy_preparation", failure_identity, exc)
                callback_faults.append(fault)
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        strategy_result,
                        risk,
                        None,
                        None,
                        BacktestDisposition.BLOCKED,
                        f"pre-commit policy preparation failed: {fault.message}",
                        (fault,),
                    )
                )
                continue
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
            # Build the request from exactly the resolved semantics risk and
            # policy evaluated; nothing here re-resolves a product or effect.
            request: ApprovedExecutionRequest = ApprovedExecutionRequest(
                order=order,
                execution_context=resolved_context,
                risk_result=risk,
                policy_result=policy,
                product=product,
                position_effect=intent.position_effect,
                effective_position_effect=effective_position_effect,
                position_evidence_cut=position_evidence_cut,
                position_evidence=evidence,
                position_evidence_max_age=evidence_max_age,
            )
            try:
                engine_time = self._require_engine_time_coherent(
                    execution_engine, frame.observation.timestamp
                )
                if qx08_active and engine_time != frame_time:
                    raise ValueError(
                        "execution clock must align exactly with the current "
                        "replay frame for QX-08 callbacks"
                    )
            except Exception as exc:
                if not qx08_active:
                    raise
                fault = callback_fault("event_time_alignment", failure_identity, exc)
                reason = (
                    f"execution event-time alignment failed before paper execution: {fault.message}"
                )
                callback_faults.append(fault)
                halt = RunHaltRecord(
                    kind="EVENT_TIME_SUPPORT_VIOLATION",
                    as_of=frame_time,
                    identity=failure_identity,
                    reason=reason,
                )
                steps.append(
                    BacktestStep(
                        frame.index,
                        timestamp,
                        strategy_result,
                        risk,
                        policy,
                        None,
                        BacktestDisposition.BLOCKED,
                        reason,
                        (fault,),
                    )
                )
                continue

            receipt = execution_engine.execute(
                request,
                snapshot=snapshot,
            )
            if not qx08_active:
                # Preserve the legacy callable path's fail-fast clock contract.
                self._require_coherent_execution_time(order, receipt)
            receipts.append(receipt)
            post_account_state = account_state_tracker.record(receipt, snapshot=snapshot)

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

            if qx08_active:
                order_id = str(order.client_order_id)
                filled_quantity = (
                    None
                    if receipt.order_status is OrderStatus.UNKNOWN and not receipt.fills
                    else sum(
                        (fill.quantity for fill in receipt.fills),
                        Decimal("0"),
                    )
                )
                order_fact = active_order_fact(
                    client_order_id=order_id,
                    instrument=order.instrument,
                    status=receipt.order_status,
                    order_quantity=order.quantity,
                    filled_quantity=filled_quantity,
                    created_at=order.created_at,
                    evidence_time=frame_time,
                    reason=receipt.message,
                    effective_at=receipt.executed_at,
                )
                if order_fact is None:
                    active_orders.pop(order_id, None)
                else:
                    active_orders[order_id] = order_fact

                temporal_violations: list[TemporalIntegrityFault] = []
                if receipt.executed_at > frame_time:
                    temporal_violations.append(
                        TemporalIntegrityFault(
                            source="receipt",
                            identity=str(receipt.receipt_id),
                            expected_at=frame_time,
                            effective_at=receipt.executed_at,
                            reason=("receipt effective time is later than the replay frame"),
                        )
                    )
                elif receipt.executed_at < order.created_at:
                    temporal_violations.append(
                        TemporalIntegrityFault(
                            source="receipt",
                            identity=str(receipt.receipt_id),
                            expected_at=frame_time,
                            effective_at=receipt.executed_at,
                            reason="receipt effective time precedes order creation",
                        )
                    )
                for fill in receipt.fills:
                    if fill.filled_at > frame_time:
                        temporal_violations.append(
                            TemporalIntegrityFault(
                                source="fill",
                                identity=str(fill.execution_id),
                                expected_at=frame_time,
                                effective_at=fill.filled_at,
                                reason=("fill effective time is later than the replay frame"),
                            )
                        )
                    elif fill.filled_at < order.created_at:
                        temporal_violations.append(
                            TemporalIntegrityFault(
                                source="fill",
                                identity=str(fill.execution_id),
                                expected_at=frame_time,
                                effective_at=fill.filled_at,
                                reason="fill effective time precedes order creation",
                            )
                        )
                if temporal_violations:
                    temporal_faults.extend(temporal_violations)
                    reason = (
                        "execution evidence outside the replay frame's event-time cut; "
                        "no coherent strategy snapshot delivered"
                    )
                    account_states.append(
                        replace(
                            post_account_state,
                            timestamp=frame_time,
                            cash=None,
                            market_value=None,
                            equity=None,
                            unrealized_pnl=None,
                            gross_exposure=None,
                            completeness=AccountStateCompleteness.INCOMPLETE,
                            issue=reason,
                        )
                    )
                    halt = RunHaltRecord(
                        kind="TEMPORAL_INTEGRITY",
                        as_of=frame_time,
                        identity=temporal_violations[0].identity,
                        reason=reason,
                    )
                    continue

                account_states.append(post_account_state)
                post_engine = build_simulated_engine_snapshot(
                    as_of=frame_time,
                    accounting=accounting,
                    active_orders=tuple(active_orders[key] for key in sorted(active_orders)),
                    account_state=post_account_state,
                )
                assert strategy_evaluation is not None and strategy_ir is not None
                post_context = StrategyContext(
                    event=strategy_evaluation.event,
                    ir=strategy_ir,
                    as_of=frame_time,
                    engine=post_engine,
                    history=history,
                )
                update_reason = receipt.message or receipt.outcome.value
                if receipt.order_status is OrderStatus.UNKNOWN and not receipt.message:
                    update_reason = (
                        "order status is UNKNOWN; fill and remaining quantities "
                        "are not authoritative"
                    )
                order_update = OrderUpdateFact(
                    client_order_id=order_id,
                    instrument=order.instrument,
                    status=receipt.order_status,
                    order_quantity=order.quantity,
                    filled_quantity=filled_quantity,
                    remaining_quantity=(
                        None
                        if (filled_quantity is None or receipt.order_status is OrderStatus.UNKNOWN)
                        else order.quantity - filled_quantity
                    ),
                    created_at=order.created_at,
                    evidence_time=frame_time,
                    reason=update_reason,
                    effective_at=receipt.executed_at,
                )
                faults = dispatch_post_commit_callbacks(
                    callback_target,
                    post_context,
                    receipt.fills,
                    order_update,
                )
                if faults:
                    callback_faults.extend(faults)
                    halt = RunHaltRecord(
                        kind="POST_COMMIT_CALLBACK_FAILURE",
                        as_of=frame_time,
                        identity=faults[0].identity,
                        reason="one or more post-commit strategy callbacks failed",
                    )
            else:
                account_states.append(post_account_state)

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
            callback_faults=tuple(callback_faults),
            halt=halt,
            temporal_faults=tuple(temporal_faults),
            undelivered_timers=timers.record_undelivered(
                "run halted before timer delivery"
                if halt is not None
                else "run ended before the timer became due"
            ),
        )
