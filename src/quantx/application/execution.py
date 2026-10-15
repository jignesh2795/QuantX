"""Single execution boundary for paper, replay, shadow, and live modes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum

from quantx.domain.deployment import ExecutionMode
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import MarketFamily, MarketRegion
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.idempotency import PendingExecutionContext
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt, MarketDataExecutionPort
from quantx.execution.receipts.identity import validate_live_receipt_identity
from quantx.execution.receipts.lifecycle import ExecutionLifecycle
from quantx.execution.session_guard import SessionExecutionGuard
from quantx.execution.trading_gate import TradingGate
from quantx.persistence import UnitOfWork
from quantx.ports.broker import BrokerPort
from quantx.ports.market_checks import (
    SKIPPED_STAGE_STATUS_CODE,
    TRUSTED_CHECK_BINDINGS,
    TRUSTED_FAILURE_CODES,
    MarketCheckEvidence,
    MarketCheckFailureCode,
    MarketCheckOutcome,
    MarketCheckResult,
    MarketCheckSequence,
    MarketCheckStage,
    MarketPolicyConfig,
    MarketRuleCheckEvidence,
    PlacedCheck,
    UnclassifiedRegion,
    UnknownMarketValue,
    contains_banned_text,
    default_market_policy,
    is_valid_failure_code,
    sanitize_public_reason,
    select_market_policy,
)

from .runtime import ApplicationRuntime


class ExecutionDispatchStatus(StrEnum):
    EXECUTED = "EXECUTED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: ExecutionDispatchStatus
    receipt: ExecutionReceipt | None = None
    reason: str = ""
    check_evidence: MarketCheckSequence | None = None

    @property
    def executed(self) -> bool:
        return self.status is ExecutionDispatchStatus.EXECUTED


def _validated_evidence(
    evidence: MarketCheckEvidence | None,
    *,
    check_id: str,
    stage: MarketCheckStage,
    region: MarketRegion,
    family: MarketFamily,
    venue: str,
    outcome: MarketCheckOutcome,
) -> MarketCheckEvidence | None:
    """Accept check evidence only when it matches its registration and result.

    Returns None for missing evidence or any inconsistency: wrong check
    identity, wrong insertion stage, non-normalized region/family/venue,
    outcome mismatch, wrong runtime types, or malformed rule facts. The
    caller synthesizes a safe entry instead of trusting the rejected one.
    """
    if evidence is None:
        return None
    if not isinstance(evidence, MarketCheckEvidence):
        return None
    if evidence.check_id != check_id or not isinstance(evidence.stage, MarketCheckStage):
        return None
    if evidence.stage != stage:
        return None
    if not isinstance(evidence.outcome, MarketCheckOutcome):
        return None
    if (
        not isinstance(evidence.region, MarketRegion)
        or evidence.region is not region
        or not isinstance(evidence.family, MarketFamily)
        or evidence.family is not family
        or evidence.venue != venue
    ):
        return None
    if evidence.outcome is not outcome:
        return None
    if not all(isinstance(item, MarketRuleCheckEvidence) for item in evidence.rule_checks):
        return None
    # Public evidence text policy: rule-check facts and metadata carrying
    # batch codenames, tracebacks, or file fragments are rejected so the
    # caller synthesizes a safe canonical entry instead.
    if any(
        contains_banned_text(item.reason) or contains_banned_text(item.name)
        for item in evidence.rule_checks
    ):
        return None
    for metadata in (evidence.rule_set_version, evidence.provenance):
        # Runtime type enforcement: malformed (non-string) metadata must
        # fail closed as malformed evidence instead of raising TypeError
        # from a banned-text scan.
        if metadata is None:
            continue
        if not isinstance(metadata, str):
            return None
        if contains_banned_text(metadata):
            return None
    return evidence


class ExecutionOrchestrator:
    """Fail-closed dispatcher between approved requests and execution adapters."""

    def __init__(
        self,
        *,
        paper_executor: MarketDataExecutionPort | None = None,
        unit_of_work: UnitOfWork | None = None,
        trading_gate: TradingGate | None = None,
        application_runtime: ApplicationRuntime | None = None,
        session_guard: SessionExecutionGuard | None = None,
        live_risk_evaluator: Callable[[ApprovedExecutionRequest], RiskResult] | None = None,
        market_policy: MarketPolicyConfig | None = None,
    ) -> None:
        self._paper_executor = paper_executor
        self._unit_of_work = unit_of_work
        self._trading_gate = trading_gate or TradingGate()
        self._trading_gate_explicit = trading_gate is not None
        self._application_runtime = application_runtime
        self._session_guard = session_guard
        self._live_risk_evaluator = live_risk_evaluator
        self._market_policy = market_policy or default_market_policy()

    def _run_market_stage(
        self,
        checks: tuple[PlacedCheck, ...],
        request: ApprovedExecutionRequest,
        *,
        stage: MarketCheckStage,
        region: MarketRegion,
        family: MarketFamily,
        venue: str,
        entries: list[MarketCheckEvidence],
    ) -> MarketCheckResult | None:
        """Run one stage's checks in registration order; BLOCKED on first failure.

        Returns the blocking result, or None when every check passed. Each
        executed check appends validated evidence (or a synthesized safe
        entry) so the recorded prefix stays complete and deterministic.
        Check exceptions, malformed results, and inconsistent evidence fail
        closed; raw diagnostics never reach user reasons.
        """
        for placement in checks:
            # Identity comes from the registration snapshot, never re-read
            # from the live object, so a dynamic identifier cannot surface.
            check = placement.check
            check_id = placement.validated_check_id
            # Trust requires the core-owned binding to hold: approved
            # implementing module, placement region, and insertion stage.
            # A caller-controlled check ID alone grants nothing, so an
            # impersonating check is treated as generic.
            binding = TRUSTED_CHECK_BINDINGS.get(check_id)
            trusted = (
                binding is not None
                and type(check).__module__.startswith(binding.module_prefixes)
                and placement.region in binding.regions
                and placement.stage is binding.stage
            )
            trusted_codes = TRUSTED_FAILURE_CODES.get(check_id) if trusted else None
            try:
                result = check(request)
            except Exception as exc:
                result = MarketCheckResult(
                    check_id,
                    MarketCheckOutcome.UNAVAILABLE,
                    MarketCheckFailureCode.EVALUATION_FAILED,
                    f"{check_id} evaluation failed closed",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            shape_ok = (
                isinstance(result, MarketCheckResult)
                and type(result.outcome) is MarketCheckOutcome
                and result.outcome
                in (
                    MarketCheckOutcome.PASS,
                    MarketCheckOutcome.BLOCK,
                    MarketCheckOutcome.UNAVAILABLE,
                )
                and result.check_id == check_id
            )
            if not shape_ok:
                result = MarketCheckResult(
                    check_id,
                    MarketCheckOutcome.UNAVAILABLE,
                    MarketCheckFailureCode.MALFORMED_RESULT,
                    f"{check_id} returned a malformed result",
                    detail=f"unexpected result {type(result).__name__}",
                )
            elif result.outcome is not MarketCheckOutcome.PASS:
                # Sanitize only check-returned reasons here. Runner-synthesized
                # messages are static and trusted by construction, so they
                # bypass the sanitizer instead of being rewritten by it.
                sanitized = sanitize_public_reason(
                    result.reason,
                    check_id=check_id,
                    blocked=result.outcome is MarketCheckOutcome.BLOCK,
                    trusted=trusted,
                )
                if sanitized != result.reason:
                    result = replace(
                        result,
                        reason=sanitized,
                        detail=result.detail or f"withheld unsanitized reason for {check_id}",
                    )
                # Failure-code boundary: trusted checks may only return their
                # registry-listed codes; every other check's code is rewritten
                # to a framework-owned code so arbitrary pack vocabulary never
                # reaches public structured evidence.
                if trusted_codes is not None:
                    if result.failure_code not in trusted_codes or not is_valid_failure_code(
                        result.failure_code
                    ):
                        result = replace(
                            result,
                            outcome=MarketCheckOutcome.UNAVAILABLE,
                            failure_code=MarketCheckFailureCode.MALFORMED_RESULT,
                            reason=f"{check_id} returned an undeclared failure code",
                            detail=f"undeclared failure code {result.failure_code!r}",
                        )
                elif result.failure_code is MarketCheckFailureCode.EVALUATION_FAILED:
                    pass  # framework-owned: retain for check exceptions
                else:
                    rewritten = (
                        MarketCheckFailureCode.PACK_BLOCKED
                        if result.outcome is MarketCheckOutcome.BLOCK
                        else MarketCheckFailureCode.PACK_UNAVAILABLE
                    )
                    result = replace(
                        result,
                        failure_code=rewritten,
                        detail=result.detail or f"withheld undeclared failure code for {check_id}",
                    )
            provided = result.evidence
            if provided is None:
                entries.append(
                    MarketCheckEvidence(
                        check_id=check_id,
                        stage=stage,
                        outcome=result.outcome,
                        region=region,
                        family=family,
                        venue=venue,
                    )
                )
            else:
                validated = _validated_evidence(
                    provided,
                    check_id=check_id,
                    stage=stage,
                    region=region,
                    family=family,
                    venue=venue,
                    outcome=result.outcome,
                )
                if validated is None:
                    result = MarketCheckResult(
                        check_id,
                        MarketCheckOutcome.UNAVAILABLE,
                        MarketCheckFailureCode.MALFORMED_RESULT,
                        f"{check_id} returned malformed evidence",
                        detail="check evidence did not match its registration and outcome",
                    )
                    entries.append(
                        MarketCheckEvidence(
                            check_id=check_id,
                            stage=stage,
                            outcome=MarketCheckOutcome.UNAVAILABLE,
                            region=region,
                            family=family,
                            venue=venue,
                        )
                    )
                else:
                    if trusted:
                        # Trusted implementations keep their full validated
                        # evidence; the India adapters sanitize its text.
                        entries.append(validated)
                    else:
                        # Generic untrusted packs get a canonical normalized
                        # entry: clean-looking but unapproved metadata and
                        # rule facts are never serialized. The structural
                        # fields are re-stamped from the registered snapshot
                        # and the normalized request context.
                        entries.append(
                            MarketCheckEvidence(
                                check_id=check_id,
                                stage=stage,
                                outcome=result.outcome,
                                region=region,
                                family=family,
                                venue=venue,
                            )
                        )
            if result.outcome is not MarketCheckOutcome.PASS:
                return result
        return None

    def _blocked_with_evidence(
        self,
        result: MarketCheckResult,
        entries: list[MarketCheckEvidence],
    ) -> ExecutionResult:
        sequence = MarketCheckSequence(
            entries=tuple(entries),
            short_circuited=True,
            blocking_check_id=result.check_id,
            blocking_failure_code=result.failure_code,
        )
        return ExecutionResult(
            ExecutionDispatchStatus.BLOCKED, reason=result.reason, check_evidence=sequence
        )

    @staticmethod
    def _with_evidence_prefix(
        result: ExecutionResult, entries: list[MarketCheckEvidence]
    ) -> ExecutionResult:
        """Attach the executed-check prefix to a downstream core outcome.

        Outcomes produced after pack checks ran carry the recorded prefix
        (no blocking check); paths with no executed checks keep evidence
        absent, preserving the legacy core-only shape.
        """
        if entries and result.check_evidence is None:
            return replace(
                result,
                check_evidence=MarketCheckSequence(entries=tuple(entries), short_circuited=False),
            )
        return result

    def execute(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot | None = None,
        broker: BrokerPort | None = None,
    ) -> ExecutionResult:
        mode = request.execution_context.execution_mode

        if mode is ExecutionMode.LIVE:
            if not self._trading_gate_explicit:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="live execution requires an explicitly configured durable TradingGate",
                )
            if not self._trading_gate.is_durable:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="live execution requires a durable TradingGate",
                )
            if self._application_runtime is None:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="live execution requires the recovery-backed ApplicationRuntime",
                )
            if not self._application_runtime.started:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="live execution requires a started ApplicationRuntime",
                )

        if not self._trading_gate.allow():
            state = self._trading_gate.state()
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason=f"trading is blocked: {state.reason}",
            )

        try:
            selection = select_market_policy(
                self._market_policy, request.execution_context.market, mode
            )
        except UnknownMarketValue:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="unknown market region or family fails closed",
            )
        except UnclassifiedRegion:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="unclassified market region fails closed",
            )
        check_entries: list[MarketCheckEvidence] = []
        pack_applies = selection.applies_pack

        # P-A: pre-dispatch market policy at its existing position.
        if pack_applies:
            stage_checks = self._market_policy.checks_for(
                selection.region, MarketCheckStage.PRE_DISPATCH
            )
            if not stage_checks:
                if MarketCheckStage.PRE_DISPATCH in selection.policy.required_stages:
                    return self._blocked_with_evidence(
                        MarketCheckResult(
                            f"{selection.region.value}.pre_dispatch",
                            MarketCheckOutcome.UNAVAILABLE,
                            MarketCheckFailureCode.MISSING_REQUIRED_STAGE,
                            "required pre-dispatch market checks are missing for region "
                            f"{selection.region.value}",
                        ),
                        check_entries,
                    )
                if MarketCheckStage.PRE_DISPATCH in selection.policy.optional_stages:
                    check_entries.append(
                        MarketCheckEvidence(
                            check_id=f"{selection.region.value}.pre_dispatch",
                            stage=MarketCheckStage.PRE_DISPATCH,
                            outcome=MarketCheckOutcome.SKIPPED,
                            region=selection.region,
                            family=selection.family,
                            venue=selection.venue,
                            stage_status_code=SKIPPED_STAGE_STATUS_CODE,
                        )
                    )
            else:
                blocked = self._run_market_stage(
                    stage_checks,
                    request,
                    stage=MarketCheckStage.PRE_DISPATCH,
                    region=selection.region,
                    family=selection.family,
                    venue=selection.venue,
                    entries=check_entries,
                )
                if blocked is not None:
                    return self._blocked_with_evidence(blocked, check_entries)

        if self._session_guard is not None and not selection.skip_session_guard:
            session = self._session_guard.check(mode)
            if not session.allowed:
                return self._with_evidence_prefix(
                    ExecutionResult(
                        ExecutionDispatchStatus.BLOCKED,
                        reason=session.reason,
                    ),
                    check_entries,
                )

        if mode in {ExecutionMode.PAPER, ExecutionMode.SHADOW, ExecutionMode.REPLAY}:
            if self._paper_executor is None:
                return self._with_evidence_prefix(
                    ExecutionResult(
                        ExecutionDispatchStatus.BLOCKED,
                        reason="paper execution adapter is not configured",
                    ),
                    check_entries,
                )
            if snapshot is None:
                return self._with_evidence_prefix(
                    ExecutionResult(
                        ExecutionDispatchStatus.BLOCKED,
                        reason="market snapshot is required for paper/replay execution",
                    ),
                    check_entries,
                )
            if snapshot.instrument != request.order.instrument:
                return self._with_evidence_prefix(
                    ExecutionResult(
                        ExecutionDispatchStatus.BLOCKED,
                        reason="market snapshot instrument does not match execution request",
                    ),
                    check_entries,
                )
            return ExecutionResult(
                ExecutionDispatchStatus.EXECUTED,
                receipt=self._paper_executor.execute(request, snapshot=snapshot),
            )

        if mode is not ExecutionMode.LIVE:
            return self._with_evidence_prefix(
                ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason=f"unsupported execution mode: {mode.value}",
                ),
                check_entries,
            )

        if broker is None:
            return self._with_evidence_prefix(
                ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="live execution requires a broker adapter",
                ),
                check_entries,
            )

        connection_id = request.execution_context.broker_connection_id
        if connection_id is None:
            return self._with_evidence_prefix(
                ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="live execution requires a broker connection",
                ),
                check_entries,
            )

        connection = broker.connection
        if connection.account_id != request.execution_context.account_id:
            return self._with_evidence_prefix(
                ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="broker account does not match execution request account",
                ),
                check_entries,
            )
        if connection.connection_id != connection_id:
            return self._with_evidence_prefix(
                ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="broker connection does not match execution request connection",
                ),
                check_entries,
            )
        if not broker.health():
            return self._with_evidence_prefix(
                ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="broker connection is not healthy",
                ),
                check_entries,
            )

        broker_instrument = broker.instrument(request.order.instrument)
        if broker_instrument is None:
            return self._with_evidence_prefix(
                ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="broker does not expose the requested canonical instrument",
                ),
                check_entries,
            )
        if broker_instrument.market != request.execution_context.market:
            return self._with_evidence_prefix(
                ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="broker instrument market does not match execution request market",
                ),
                check_entries,
            )

        # P-B: pre-submit market policy at its existing position.
        if pack_applies:
            submit_checks = self._market_policy.checks_for(
                selection.region, MarketCheckStage.PRE_SUBMIT
            )
            if not submit_checks:
                if MarketCheckStage.PRE_SUBMIT in selection.policy.required_stages:
                    return self._blocked_with_evidence(
                        MarketCheckResult(
                            f"{selection.region.value}.pre_submit",
                            MarketCheckOutcome.UNAVAILABLE,
                            MarketCheckFailureCode.MISSING_REQUIRED_STAGE,
                            "required pre-submit market checks are missing for region "
                            f"{selection.region.value}",
                        ),
                        check_entries,
                    )
                if MarketCheckStage.PRE_SUBMIT in selection.policy.optional_stages:
                    check_entries.append(
                        MarketCheckEvidence(
                            check_id=f"{selection.region.value}.pre_submit",
                            stage=MarketCheckStage.PRE_SUBMIT,
                            outcome=MarketCheckOutcome.SKIPPED,
                            region=selection.region,
                            family=selection.family,
                            venue=selection.venue,
                            stage_status_code=SKIPPED_STAGE_STATUS_CODE,
                        )
                    )
            else:
                blocked = self._run_market_stage(
                    submit_checks,
                    request,
                    stage=MarketCheckStage.PRE_SUBMIT,
                    region=selection.region,
                    family=selection.family,
                    venue=selection.venue,
                    entries=check_entries,
                )
                if blocked is not None:
                    return self._blocked_with_evidence(blocked, check_entries)

        required_capabilities = request.order.required_capabilities
        if required_capabilities and not broker.capabilities().require(required_capabilities):
            return self._with_evidence_prefix(
                ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="broker does not support all required execution capabilities",
                ),
                check_entries,
            )

        unit_of_work = self._unit_of_work
        if unit_of_work is None:
            return self._with_evidence_prefix(
                ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason="live execution requires a durable UnitOfWork",
                ),
                check_entries,
            )
        if self._live_risk_evaluator is not None:
            try:
                live_risk = self._live_risk_evaluator(request)
            except Exception as exc:
                return self._with_evidence_prefix(
                    ExecutionResult(
                        ExecutionDispatchStatus.BLOCKED,
                        reason=f"live pre-trade risk evaluation failed closed: {exc}",
                    ),
                    check_entries,
                )
            if live_risk.decision is not RiskDecision.APPROVE:
                return self._with_evidence_prefix(
                    ExecutionResult(
                        ExecutionDispatchStatus.BLOCKED,
                        reason=f"live pre-trade risk rejected the request: {live_risk.reason}",
                    ),
                    check_entries,
                )
        live_result = self._execute_live_transactional(request, broker, unit_of_work)
        if pack_applies:
            return self._with_evidence_prefix(live_result, check_entries)
        return live_result

    def continue_partial(
        self,
        request: ApprovedExecutionRequest,
        lifecycle: ExecutionLifecycle,
        *,
        risk_result: RiskResult,
        snapshot: MarketSnapshot | None = None,
        requested_quantity: Decimal | None = None,
    ) -> ExecutionResult:
        """Continue a partial paper execution through the control plane."""
        mode = request.execution_context.execution_mode
        if not self._trading_gate.allow():
            state = self._trading_gate.state()
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason=f"trading is blocked: {state.reason}",
            )
        if self._session_guard is not None:
            session = self._session_guard.check(mode)
            if not session.allowed:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason=session.reason,
                )
        if mode not in {ExecutionMode.PAPER, ExecutionMode.SHADOW, ExecutionMode.REPLAY}:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="partial continuation is only supported for paper/replay execution",
            )
        if self._paper_executor is None:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="paper execution adapter is not configured",
            )
        if snapshot is None:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="market snapshot is required for partial continuation",
            )
        if snapshot.instrument != request.order.instrument:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="market snapshot instrument does not match execution request",
            )
        continue_partial = getattr(self._paper_executor, "continue_partial", None)
        if not callable(continue_partial):
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason="paper execution adapter does not support partial continuation",
            )
        try:
            receipt = continue_partial(
                request,
                lifecycle,
                risk_result=risk_result,
                snapshot=snapshot,
                requested_quantity=requested_quantity,
            )
        except Exception as exc:
            return ExecutionResult(
                ExecutionDispatchStatus.UNKNOWN,
                reason=f"partial continuation failed safely: {exc}",
            )
        return ExecutionResult(
            ExecutionDispatchStatus.EXECUTED,
            receipt=receipt,
        )

    def _execute_live_transactional(
        self,
        request: ApprovedExecutionRequest,
        broker: BrokerPort,
        unit_of_work: UnitOfWork,
    ) -> ExecutionResult:
        """Live execution in two scopes so no transaction spans broker submit.

        Scope A commits the PENDING reservation; the broker submission runs
        outside any transaction and outside the trading-gate lock; Scope B
        atomically saves the receipt and completes the reservation.

        R0-B scope: only the safety-critical submit/cancel/reconcile broker
        operations carry bounded timeouts. ``broker.health()`` (checked in
        ``execute`` before this method) never holds the submission permit,
        so an unbounded health probe cannot serialize ``block()``; the
        remaining read-only observations (fund limits, positions, quotes,
        candles) are outside the R0-B bounded-call contract.
        """
        fingerprint = request_fingerprint(request)
        client_order_id = request.order.client_order_id

        # Completed duplicates and existing pending reservations never submit.
        with unit_of_work:
            existing = unit_of_work.idempotency.check(client_order_id, fingerprint)
            if existing.existing_receipt_id is not None:
                authoritative = unit_of_work.receipts.get(existing.existing_receipt_id)
                if authoritative is None:
                    return ExecutionResult(
                        ExecutionDispatchStatus.UNKNOWN,
                        reason=(
                            "persisted receipt is missing for a completed reservation; "
                            "reconciliation is required"
                        ),
                    )
                return ExecutionResult(
                    ExecutionDispatchStatus.EXECUTED,
                    receipt=authoritative,
                    reason=f"idempotent duplicate; receipt={existing.existing_receipt_id}",
                )
            if existing.reservation_pending:
                return ExecutionResult(
                    ExecutionDispatchStatus.UNKNOWN,
                    reason="submission outcome is unknown; reconciliation is required",
                )
            if existing.operator_resolved:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason=(
                        "reservation was explicitly closed by an operator; "
                        "implicit resubmission is prohibited, "
                        "use a new client_order_id for another attempt"
                    ),
                )

        # The permit is acquired before creating the pending reservation.
        # The lock is released BEFORE the broker call so that block() cannot
        # be delayed by a slow/unbounded broker submission.
        # The gate check + reservation creation remain atomic under the lock.
        with self._trading_gate.submission_permit() as permitted:
            if not permitted:
                state = self._trading_gate.state()
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason=f"trading is blocked: {state.reason}",
                )

            with unit_of_work:
                pending_context = PendingExecutionContext.from_request(request, fingerprint)
                decision = unit_of_work.idempotency.reserve_or_get(
                    client_order_id,
                    fingerprint,
                    pending_context,
                )
                if decision.existing_receipt_id is not None:
                    authoritative = unit_of_work.receipts.get(decision.existing_receipt_id)
                    if authoritative is None:
                        return ExecutionResult(
                            ExecutionDispatchStatus.UNKNOWN,
                            reason=(
                                "persisted receipt is missing for a completed reservation; "
                                "reconciliation is required"
                            ),
                        )
                    return ExecutionResult(
                        ExecutionDispatchStatus.EXECUTED,
                        receipt=authoritative,
                        reason=f"idempotent duplicate; receipt={decision.existing_receipt_id}",
                    )
                if decision.reservation_pending and not decision.reservation_acquired:
                    return ExecutionResult(
                        ExecutionDispatchStatus.UNKNOWN,
                        reason="submission outcome is unknown; reconciliation is required",
                    )
                if decision.operator_resolved:
                    return ExecutionResult(
                        ExecutionDispatchStatus.BLOCKED,
                        reason=(
                            "reservation was explicitly closed by an operator; "
                            "implicit resubmission is prohibited, "
                            "use a new client_order_id for another attempt"
                        ),
                    )
                if not decision.reservation_acquired:
                    return ExecutionResult(
                        ExecutionDispatchStatus.UNKNOWN,
                        reason=(
                            "idempotency reservation was not acquired; reconciliation is required"
                        ),
                    )

        # Broker call happens OUTSIDE the trading-gate lock.
        # Timeout is enforced by the broker adapter; any timeout/exception
        # produces UNKNOWN outcome, never REJECTED, and no automatic retry.
        try:
            receipt = broker.submit(request)
        except Exception as exc:
            return ExecutionResult(
                ExecutionDispatchStatus.UNKNOWN,
                reason=f"submission outcome is unknown; reconciliation is required: {exc}",
            )
        if receipt.outcome is ExecutionOutcome.UNKNOWN:
            return ExecutionResult(
                ExecutionDispatchStatus.UNKNOWN,
                receipt=receipt,
                reason="broker returned an UNKNOWN receipt; reconciliation is required",
            )
        # Identity validation: the broker response must be demonstrably bound to
        # the approved request before it can be persisted as authoritative evidence
        # or used to complete the idempotency reservation.  Any mismatch leaves the
        # PENDING reservation intact so that reconciliation can resolve the outcome;
        # the foreign receipt is discarded without being written to the database.
        identity_violation = validate_live_receipt_identity(request, receipt)
        if identity_violation is not None:
            return ExecutionResult(
                ExecutionDispatchStatus.UNKNOWN,
                reason=(
                    f"broker receipt identity mismatch — keeping reservation pending "
                    f"for reconciliation; {identity_violation.reason}"
                ),
            )
        with unit_of_work:
            unit_of_work.receipts.save(receipt)
            try:
                unit_of_work.idempotency.complete(client_order_id, fingerprint, receipt.receipt_id)
            except Exception as exc:
                return ExecutionResult(
                    ExecutionDispatchStatus.UNKNOWN,
                    receipt=receipt,
                    reason=(
                        "submission completed; receipt is durable but idempotency completion "
                        "is uncertain; "
                        f"reconciliation is required: {exc}"
                    ),
                )
        return ExecutionResult(ExecutionDispatchStatus.EXECUTED, receipt=receipt, reason="")
