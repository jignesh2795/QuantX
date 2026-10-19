"""Single execution boundary for paper, replay, shadow, and live modes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timezone
from decimal import Decimal
from enum import StrEnum
from uuid import NAMESPACE_URL, UUID, uuid5

from quantx.domain.deployment import ExecutionMode
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import MarketFamily, MarketRegion
from quantx.domain.risk import RiskDecision, RiskResult
from quantx.execution.idempotency import NotSubmittedSource, PendingExecutionContext
from quantx.execution.idempotency.fingerprint import request_fingerprint
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.ports import ExecutionOutcome, ExecutionReceipt, MarketDataExecutionPort
from quantx.execution.receipts.identity import (
    ReceiptIdentityViolation,
    validate_live_receipt_identity,
    validate_receipt_runtime_shape,
)
from quantx.execution.receipts.lifecycle import ExecutionLifecycle
from quantx.execution.receipts.quarantine import (
    QuarantinedSubmissionObservation,
    QuarantineObservationKind,
)
from quantx.execution.session_guard import SessionExecutionGuard
from quantx.execution.submission_preflight import BrokerPreflightRejected
from quantx.execution.trading_gate import TradingGate
from quantx.persistence import UnitOfWork
from quantx.ports.broker import BrokerPort
from quantx.ports.market_checks import (
    SKIPPED_STAGE_STATUS_CODE,
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
    is_trusted_check,
    is_valid_failure_code,
    is_valid_provenance,
    is_valid_rule_check_name,
    is_valid_rule_check_reason,
    is_valid_rule_set_version,
    sanitize_public_reason,
    select_market_policy,
    trusted_failure_codes,
)
from quantx.ports.persistence import SubmissionQuarantineRepository

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


# Static, sanitized observation reasons. Quarantine evidence must never
# carry raw exception messages or transport payloads, so every record uses
# one of these fixed, category-owned texts.
_QUARANTINE_REASONS: dict[QuarantineObservationKind, str] = {
    QuarantineObservationKind.TRANSPORT_UNCERTAIN: (
        "transport outcome uncertain after submission may have begun; unresolved"
    ),
    QuarantineObservationKind.BROKER_UNKNOWN: (
        "broker returned an UNKNOWN receipt; unresolved pending reconciliation"
    ),
    QuarantineObservationKind.IDENTITY_REJECTED: (
        "broker receipt identity rejected; retained for reconciliation only"
    ),
    QuarantineObservationKind.MALFORMED_RECEIPT: (
        "broker response outside the canonical receipt contract; retained for reconciliation only"
    ),
    QuarantineObservationKind.RECEIPT_PERSISTENCE_UNCERTAIN: (
        "canonical receipt persistence failed after the submission may have "
        "reached the broker; outcome unresolved"
    ),
}


def _quarantine_reason(kind: QuarantineObservationKind) -> str:
    return _QUARANTINE_REASONS[kind]


def _validated_evidence(
    evidence: MarketCheckEvidence | None,
    *,
    check_id: str,
    stage: MarketCheckStage,
    region: MarketRegion,
    family: MarketFamily,
    venue: str,
    outcome: MarketCheckOutcome,
    trusted: bool,
) -> MarketCheckEvidence | None:
    """Accept check evidence only when it matches its registration and result.

    Returns None for missing evidence or any inconsistency: wrong check
    identity, wrong insertion stage, non-normalized region/family/venue,
    outcome mismatch, wrong runtime types, or malformed rule facts. The
    caller synthesizes a safe entry instead of trusting the rejected one.

    ``trusted`` additionally gates the *values* that survive into the
    record: only a trusted check's evidence is serialized as provided, so
    only a trusted check's rule names, rule reasons, versions, and
    provenance must already be approved. An untrusted check's values are
    never serialized (the caller re-stamps a canonical entry), so they are
    only screened for banned diagnostic text here.

    Every field is validated before use: dataclasses do not enforce their
    annotations at runtime, so a pack can supply ``rule_checks=None``, a
    non-tuple container, non-fact entries, non-string text, non-boolean
    flags, or a smuggled stage status code. Any of those returns None
    instead of raising, so malformed evidence always lands on the
    synthesized safe-evidence path (``MALFORMED_RESULT``/``UNAVAILABLE``)
    and never escapes the orchestrator as an exception or a contradictory
    public record.
    """
    if evidence is None:
        return None
    # This is an extension boundary: subclasses may execute arbitrary code in
    # attribute access. Accept only the concrete neutral evidence record.
    if type(evidence) is not MarketCheckEvidence:
        return None
    if type(evidence.check_id) is not str or evidence.check_id != check_id:
        return None
    if not isinstance(evidence.stage, MarketCheckStage):
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
        or type(evidence.venue) is not str
        or evidence.venue != venue
    ):
        return None
    if evidence.outcome is not outcome:
        return None
    # The stage status code is runner-synthesized for skipped optional
    # stages only; a check must never smuggle its own status text into a
    # non-skipped record (or forge the skipped marker on one).
    if evidence.outcome is MarketCheckOutcome.SKIPPED:
        if evidence.stage_status_code != SKIPPED_STAGE_STATUS_CODE:
            return None
    elif evidence.stage_status_code is not None:
        return None
    # Timestamps and session flags must be well-typed so serialization
    # cannot emit contradictory facts (a naive timestamp, a truthy string
    # flag, or a non-datetime value).
    # Snapshot timestamps onto a standard fixed-offset timezone. Caller-
    # supplied tzinfo objects can raise or change behavior when serialized.
    safe_evaluated_at: datetime | None = None
    if evidence.evaluated_at is not None:
        if type(evidence.evaluated_at) is not datetime:
            return None
        try:
            offset = evidence.evaluated_at.utcoffset()
            if offset is None:
                return None
            safe_evaluated_at = evidence.evaluated_at.replace(tzinfo=timezone(offset))
        except Exception:
            return None
    if (
        type(evidence.session_evaluated) is not bool
        or type(evidence.compatibility_evaluated) is not bool
    ):
        return None
    for session_field in (evidence.session_exchange, evidence.session_segment):
        if session_field is not None and type(session_field) is not str:
            return None
    # The supported rule-fact container is a tuple; entries must be real
    # facts with string text and an actual boolean verdict. ``passed`` is
    # checked by exact runtime type, so integers and strings are rejected
    # before any text scan. Non-string fact text fails closed before the
    # banned-text scan can raise.
    rule_checks = evidence.rule_checks
    if type(rule_checks) is not tuple:
        return None
    for item in rule_checks:
        if type(item) is not MarketRuleCheckEvidence:
            return None
        if type(item.name) is not str or type(item.reason) is not str:
            return None
        if type(item.passed) is not bool:
            return None
    if any(
        contains_banned_text(item.reason) or contains_banned_text(item.name) for item in rule_checks
    ):
        return None
    for metadata, is_approved in (
        (evidence.rule_set_version, is_valid_rule_set_version),
        (evidence.provenance, is_valid_provenance),
    ):
        # Runtime type enforcement: malformed (non-string) metadata must
        # fail closed as malformed evidence instead of raising TypeError
        # from a banned-text scan.
        if metadata is None:
            continue
        if type(metadata) is not str:
            return None
        if not trusted:
            if contains_banned_text(metadata):
                return None
            continue
        if not is_approved(metadata):
            return None
    if trusted and any(
        not is_valid_rule_check_name(item.name) or not is_valid_rule_check_reason(item.reason)
        for item in rule_checks
    ):
        return None
    # Detach timestamps from caller-controlled tzinfo before public JSON
    # serialization can invoke it again.
    if safe_evaluated_at is not None:
        return replace(evidence, evaluated_at=safe_evaluated_at)
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
        submission_quarantine: SubmissionQuarantineRepository | None = None,
    ) -> None:
        self._paper_executor = paper_executor
        self._unit_of_work = unit_of_work
        self._trading_gate = trading_gate or TradingGate()
        self._trading_gate_explicit = trading_gate is not None
        self._application_runtime = application_runtime
        self._session_guard = session_guard
        self._live_risk_evaluator = live_risk_evaluator
        self._market_policy = market_policy or default_market_policy()
        self._submission_quarantine = submission_quarantine

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
            # Trust is decided entirely inside the core: the placed class
            # object must be the exact approved implementation, and the
            # placement region and stage must match its core-owned binding.
            # A caller-controlled check ID alone grants nothing, so an
            # impersonating check is treated as generic.
            trusted = is_trusted_check(
                check_id,
                check,
                region=placement.region,
                stage=placement.stage,
            )
            trusted_codes = trusted_failure_codes(check_id) if trusted else None
            try:
                result = check(request)
            except Exception as exc:
                # Keep diagnostics private and ensure even a hostile exception
                # whose __str__ or metaclass raises cannot escape the boundary.
                try:
                    diagnostic = f"{type(exc).__name__}: {exc}"
                except Exception:
                    diagnostic = "check raised an exception; diagnostics unavailable"
                result = MarketCheckResult(
                    check_id,
                    MarketCheckOutcome.UNAVAILABLE,
                    MarketCheckFailureCode.EVALUATION_FAILED,
                    f"{check_id} evaluation failed closed",
                    detail=diagnostic,
                )
            # Validate exact field types before equality, sanitization, or
            # registry membership: a frozen dataclass can still have fields
            # rewritten with object.__setattr__, and hostile values can make
            # those later operations raise.
            code = result.failure_code if type(result) is MarketCheckResult else None
            code_has_shape = (
                code is None or type(code) is str or type(code) is MarketCheckFailureCode
            )
            shape_ok = (
                type(result) is MarketCheckResult
                and type(result.outcome) is MarketCheckOutcome
                and result.outcome
                in (
                    MarketCheckOutcome.PASS,
                    MarketCheckOutcome.BLOCK,
                    MarketCheckOutcome.UNAVAILABLE,
                )
                and type(result.check_id) is str
                and result.check_id == check_id
                and type(result.reason) is str
                and bool(result.reason.strip())
                and type(result.detail) is str
                and code_has_shape
                and (
                    (result.outcome is MarketCheckOutcome.PASS and code is None)
                    or (
                        result.outcome is not MarketCheckOutcome.PASS
                        and code is not None
                        and bool(code.strip())
                    )
                )
            )
            if not shape_ok:
                result = MarketCheckResult(
                    check_id,
                    MarketCheckOutcome.UNAVAILABLE,
                    MarketCheckFailureCode.MALFORMED_RESULT,
                    f"{check_id} returned a malformed result",
                    detail="check returned an object outside the result contract",
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
                # reaches public structured evidence. The grammar check runs
                # first so a non-string code fails closed here instead of
                # raising TypeError inside the membership test.
                if trusted_codes is not None:
                    if (
                        not is_valid_failure_code(result.failure_code)
                        or result.failure_code not in trusted_codes
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
                try:
                    validated = _validated_evidence(
                        provided,
                        check_id=check_id,
                        stage=stage,
                        region=region,
                        family=family,
                        venue=venue,
                        outcome=result.outcome,
                        trusted=trusted,
                    )
                except Exception:
                    # Unexpected exceptions while inspecting caller-supplied
                    # evidence must fail closed, not escape orchestration.
                    validated = None
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

        # Submission is not a resolution point. An approved request must
        # already carry the product the pre-approval seam resolved; LIVE has no
        # legacy default, so an unresolved product is denied here before any
        # gate, reservation, or broker call. Non-live modes keep absent
        # distinct (no broker product).
        if mode is ExecutionMode.LIVE and request.product is None:
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason=(
                    "live execution requires a resolved product from a versioned "
                    "market-pack selection policy"
                ),
            )

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
            if self._submission_quarantine is None:
                # LIVE admission requires the capability that preserves
                # unresolved submission evidence durably. Establish it here,
                # beside the other LIVE-only composition prerequisites, so it
                # is proven before any broker-specific probe (connection,
                # health, instrument, capabilities), before any durable
                # reservation, and before broker submission. Without it an
                # uncertain post-admission outcome would have no durable
                # evidence path, so the request is denied instead of
                # degrading silently after the broker call.
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason=("live execution requires a durable submission quarantine repository"),
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
        atomically saves the receipt and completes the reservation. Between
        Scope A and the broker call, submit admission is re-checked at the
        gate linearization point, so a block() that returned before admission
        denies the submission before ``broker.submit()``; the read-only
        connection/health/instrument/capability observations in ``execute``
        may already have run and are not undone by the denial.

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
            if existing.not_submitted_resolution is not None:
                return ExecutionResult(
                    ExecutionDispatchStatus.BLOCKED,
                    reason=(
                        "reservation was durably closed as not submitted after an "
                        "adapter preflight rejection; implicit resubmission is "
                        "prohibited, use a new client_order_id for another attempt"
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
                if decision.not_submitted_resolution is not None:
                    return ExecutionResult(
                        ExecutionDispatchStatus.BLOCKED,
                        reason=(
                            "reservation was durably closed as not submitted after an "
                            "adapter preflight rejection; implicit resubmission is "
                            "prohibited, use a new client_order_id for another attempt"
                        ),
                    )
                if not decision.reservation_acquired:
                    return ExecutionResult(
                        ExecutionDispatchStatus.UNKNOWN,
                        reason=(
                            "idempotency reservation was not acquired; reconciliation is required"
                        ),
                    )

        # Submit admission boundary (linearization point): re-check the kill
        # switch after the reservation is durable and immediately before the
        # external broker call is admitted. Once block() has returned, any
        # submission that has not crossed this check is denied here and
        # broker.submit() is never called; the read-only health/instrument/
        # capability observations in execute may already have run. An
        # already-admitted in-flight broker call is never reversed by a
        # later block().
        #
        # The check holds no gate/store lock across broker I/O, so block()
        # never waits for a slow or hung broker call. A denied admission
        # leaves the PENDING reservation intact for reconciliation and
        # operator resolution; the attempt is reported BLOCKED (never
        # submitted, never uncertain) and is never automatically retried.
        if not self._trading_gate.admit_submission():
            state = self._trading_gate.state()
            return ExecutionResult(
                ExecutionDispatchStatus.BLOCKED,
                reason=f"trading is blocked: {state.reason}",
            )

        # Broker call happens OUTSIDE the trading-gate lock.
        # Timeout is enforced by the broker adapter; any timeout/exception
        # produces UNKNOWN outcome, never REJECTED, and no automatic retry.
        # A typed preflight rejection proves the trusted adapter entered no
        # transport I/O (NOT_SUBMITTED); every other failure after admission
        # stays SUBMISSION_UNKNOWN and is never retried automatically.
        try:
            receipt = broker.submit(request)
        except BrokerPreflightRejected as exc:
            return self._handle_preflight_rejection(request, unit_of_work, fingerprint, exc)
        except Exception as exc:
            return self._fail_closed_unknown(
                request,
                fingerprint,
                kind=QuarantineObservationKind.TRANSPORT_UNCERTAIN,
                receipt=None,
                reason=f"submission outcome is unknown; reconciliation is required: {exc}",
            )
        # The broker response is untrusted plugin-boundary data: it may be any
        # runtime object, its enum/identity fields may hold non-canonical
        # values, and attribute access itself may raise. Because the external
        # submit may already have started, such a response must become explicit
        # uncertainty with quarantined evidence — never an exception escaping
        # the public API, and never authoritative.
        try:
            runtime_violation = validate_receipt_runtime_shape(receipt)
            receipt_outcome = None if runtime_violation is not None else receipt.outcome
        except Exception:
            runtime_violation = ReceiptIdentityViolation(
                reason="broker response could not be inspected safely"
            )
            receipt_outcome = None
        if runtime_violation is not None:
            return self._fail_closed_unknown(
                request,
                fingerprint,
                kind=QuarantineObservationKind.MALFORMED_RECEIPT,
                receipt=receipt,
                expose_receipt=False,
                reason=(
                    "broker returned a response outside the canonical receipt contract; "
                    "submission outcome is unknown and reconciliation is required"
                ),
                quarantine_reason=runtime_violation.reason,
            )
        if receipt_outcome is ExecutionOutcome.UNKNOWN:
            return self._fail_closed_unknown(
                request,
                fingerprint,
                kind=QuarantineObservationKind.BROKER_UNKNOWN,
                receipt=receipt,
                reason="broker returned an UNKNOWN receipt; reconciliation is required",
            )
        # Identity validation: the broker response must be demonstrably bound to
        # the approved request before it can be persisted as authoritative evidence
        # or used to complete the idempotency reservation.  Any mismatch leaves the
        # PENDING reservation intact so that reconciliation can resolve the outcome;
        # the foreign receipt is never written to the canonical store, and its
        # sanitized identity evidence is retained separately for reconciliation.
        # A residual runtime failure inside the validator is the same class of
        # untrusted-response fault as a malformed shape: keep it as UNKNOWN.
        try:
            identity_violation = validate_live_receipt_identity(request, receipt)
        except Exception:
            return self._fail_closed_unknown(
                request,
                fingerprint,
                kind=QuarantineObservationKind.MALFORMED_RECEIPT,
                receipt=receipt,
                expose_receipt=False,
                reason=(
                    "broker receipt could not be validated against the approved request; "
                    "submission outcome is unknown and reconciliation is required"
                ),
                quarantine_reason=("receipt failed request-identity validation at runtime"),
            )
        if identity_violation is not None:
            return self._fail_closed_unknown(
                request,
                fingerprint,
                kind=QuarantineObservationKind.IDENTITY_REJECTED,
                receipt=receipt,
                expose_receipt=False,
                reason=(
                    f"broker receipt identity mismatch — keeping reservation pending "
                    f"for reconciliation; {identity_violation.reason}"
                ),
                quarantine_reason=identity_violation.reason,
            )
        completion_error: Exception | None = None
        try:
            with unit_of_work:
                unit_of_work.receipts.save(receipt)
                try:
                    unit_of_work.idempotency.complete(
                        client_order_id, fingerprint, receipt.receipt_id
                    )
                except Exception as exc:
                    # Returning inside the with-block exits the transaction
                    # normally, so the saved receipt still commits while the
                    # reservation stays pending.
                    completion_error = exc
        except Exception as exc:
            # receipts.save() or the surrounding transaction commit failed
            # after the broker may have accepted the request: whether the
            # receipt is durable is itself unknown, so the outcome must
            # escape as explicit uncertainty, never as a raised exception
            # implying a known result, and never as a fabricated success.
            reason = (
                "post-submit persistence failed; submission outcome is uncertain; "
                f"reconciliation is required: {type(exc).__name__}"
            )
            persistence_failed = self._record_quarantined_evidence(
                request,
                fingerprint,
                kind=QuarantineObservationKind.RECEIPT_PERSISTENCE_UNCERTAIN,
                receipt=receipt,
                reason=_quarantine_reason(QuarantineObservationKind.RECEIPT_PERSISTENCE_UNCERTAIN),
            )
            if persistence_failed:
                reason = f"{reason}; {self._latch_persistence_safety_fault(type(exc).__name__)}"
            return ExecutionResult(
                ExecutionDispatchStatus.UNKNOWN,
                receipt=receipt,
                reason=reason,
            )
        if completion_error is not None:
            return ExecutionResult(
                ExecutionDispatchStatus.UNKNOWN,
                receipt=receipt,
                reason=(
                    "submission completed; receipt is durable but idempotency completion "
                    "is uncertain; "
                    f"reconciliation is required: {completion_error}"
                ),
            )
        return ExecutionResult(ExecutionDispatchStatus.EXECUTED, receipt=receipt, reason="")

    def _handle_preflight_rejection(
        self,
        request: ApprovedExecutionRequest,
        unit_of_work: UnitOfWork,
        fingerprint: str,
        exc: BrokerPreflightRejected,
    ) -> ExecutionResult:
        """Close a definitely-not-submitted request durably and report it.

        The trusted adapter proved no transport I/O was entered, so the
        pending reservation must not linger as a possible external
        submission. The durable representation is the typed not-submitted
        resolution (a definite local outcome, never a human operator
        decision and never a fabricated receipt); a later replay of the
        same request is then a known local block instead of an ambiguous
        unknown submission. If the durable closure cannot be persisted,
        the conservative pending reservation plus an explicit unresolved
        result is kept for reconciliation.
        """
        reason = self._bounded_preflight_reason(exc)
        try:
            unit_of_work.idempotency.record_not_submitted(
                request.order.client_order_id,
                fingerprint,
                source=NotSubmittedSource.ADAPTER_PREFLIGHT_REJECTION,
                reason=reason,
                recorded_at=datetime.now(UTC),
            )
        except Exception:
            return ExecutionResult(
                ExecutionDispatchStatus.UNKNOWN,
                reason=(
                    "preflight rejected the request before submission, but the durable "
                    "closure of the reservation failed; the outcome is unresolved and "
                    "reconciliation is required"
                ),
            )
        return ExecutionResult(
            ExecutionDispatchStatus.BLOCKED,
            reason=f"submission was not sent: {reason}",
        )

    @staticmethod
    def _bounded_preflight_reason(exc: BrokerPreflightRejected) -> str:
        try:
            text = " ".join(str(exc).split())
        except Exception:
            text = ""
        if not text:
            return "preflight validation rejected the request before submission"
        return text[:300]

    def _fail_closed_unknown(
        self,
        request: ApprovedExecutionRequest,
        fingerprint: str,
        *,
        kind: QuarantineObservationKind,
        receipt: object | None,
        reason: str,
        quarantine_reason: str | None = None,
        expose_receipt: bool = True,
    ) -> ExecutionResult:
        """Return explicit uncertainty, attempting durable quarantined evidence.

        Used for every post-admission outcome that is not provably known:
        transport failure after submission may have begun, a broker
        UNKNOWN receipt, and identity-mismatched receipts. The
        reservation stays pending for reconciliation and the request is
        never retried here. ``receipt`` is the object the sanitized
        observation is derived from; it is attached to the result only
        when ``expose_receipt`` is set, so a foreign receipt is never
        presented as authoritative while still being quarantined. When
        the evidence cannot be durably recorded, the reusable trading-gate
        safety fault disables further submission pending reconciliation
        instead of dropping the uncertainty silently.
        """
        persistence_failed = self._record_quarantined_evidence(
            request,
            fingerprint,
            kind=kind,
            receipt=receipt,
            reason=quarantine_reason or _quarantine_reason(kind),
        )
        if persistence_failed:
            reason = f"{reason}; {self._latch_persistence_safety_fault(kind.value)}"
        return ExecutionResult(
            ExecutionDispatchStatus.UNKNOWN,
            receipt=(receipt if expose_receipt and isinstance(receipt, ExecutionReceipt) else None),
            reason=reason,
        )

    def _record_quarantined_evidence(
        self,
        request: ApprovedExecutionRequest,
        fingerprint: str,
        *,
        kind: QuarantineObservationKind,
        receipt: object | None,
        reason: str,
    ) -> bool:
        """Attempt one sanitized, non-authoritative observation record.

        Returns True when the evidence could not be durably recorded — a
        configured store that raised, or (defense in depth; unreachable for
        LIVE after the admission precondition) no store at all. Both mean
        the system cannot preserve the unresolved submission evidence, so
        the caller latches the safety fault instead of dropping the
        uncertainty silently.
        """
        recorder = self._submission_quarantine
        if recorder is None:
            return True
        try:
            observation = QuarantinedSubmissionObservation.from_receipt(
                observation_id=self._quarantine_observation_id(request, fingerprint, kind, receipt),
                kind=kind,
                client_order_id=request.order.client_order_id,
                request_correlation_id=request.correlation_id,
                receipt=receipt,
                reason=self._bounded_quarantine_reason(reason),
                observed_at=datetime.now(UTC),
            )
            recorder.record(observation)
        except Exception:
            return True
        return False

    @staticmethod
    def _bounded_quarantine_reason(reason: str) -> str:
        """Bound a quarantine reason to a stored-evidence-safe size.

        Identity-violation diagnostics embed broker-supplied identity values,
        so a hostile response could otherwise make the reason unbounded. The
        record is non-authoritative reconciliation evidence: bounding it keeps
        the store safe without dropping the observation.
        """
        text = " ".join(reason.split())
        if not text:
            return "unspecified submission uncertainty"
        return text[:384]

    @staticmethod
    def _quarantine_observation_id(
        request: ApprovedExecutionRequest,
        fingerprint: str,
        kind: QuarantineObservationKind,
        receipt: object | None,
    ) -> UUID:
        """Derive one stable observation identity per logical uncertainty.

        The identity is deterministic per (kind, request, receipt), so a
        re-observation of the same unresolved event writes idempotently
        instead of duplicating evidence.
        """
        receipt_key = "no-receipt"
        if receipt is not None:
            try:
                receipt_id = getattr(receipt, "receipt_id", None)
            except Exception:
                receipt_id = None
            receipt_key = (
                str(receipt_id) if isinstance(receipt_id, UUID) else "unidentified-receipt"
            )
        key = (
            f"quantx:submission-quarantine:{kind.value}:"
            f"{request.order.client_order_id}:{fingerprint}:{receipt_key}"
        )
        return uuid5(NAMESPACE_URL, key)

    def _latch_persistence_safety_fault(self, detail: str) -> str:
        """Disable further submission pending reconciliation (fail-closed).

        Reuses the existing durable trading-gate fault semantics: a
        successful durable ``block()`` disables submission across restart,
        and if the durable write itself fails the gate latches its
        process-local fail-closed fault so admission stays denied in this
        process. This is never an independent, fail-open gate.
        """
        reason = (
            "submission evidence persistence failed; submissions are disabled "
            f"pending reconciliation: {detail}"
        )
        try:
            self._trading_gate.block(reason)
        except Exception:
            # The durable block could not be persisted; the gate has
            # latched its fail-closed fault, so submission stays denied in
            # this process while the uncertainty is reported.
            pass
        return reason
