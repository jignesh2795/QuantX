"""India market-pack pre-trade checks behind the neutral check contract.

These adapters move the India session/calendar and compatibility/rule
evaluation (including coherence validation) out of application
orchestration. They project India-owned results into neutral
``MarketCheckResult`` values; India result classes never cross into
``quantx.application``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import MarketFamily, MarketRegion
from quantx.ports.market_checks import (
    MarketCheckEvidence,
    MarketCheckOutcome,
    MarketCheckResult,
    MarketCheckStage,
    MarketPolicyConfig,
    MarketRuleCheckEvidence,
    PlacedCheck,
    RegionMarketPolicy,
    contains_banned_text,
    normalize_market_context,
)

from .domain import IndianSegment
from .execution_rules import IndiaRuleCheck, IndiaRuleDecision, IndiaRuleResult
from .session_calendar import IndiaSessionDecision, IndiaSessionResult

_PUBLIC_RULE_CODES: frozenset[str] = frozenset(
    {
        "INDIA_INSTRUMENT_MISMATCH",
        "INDIA_ORDER_TYPE_INVALID",
        "INDIA_QUANTITY_INVALID",
        "INDIA_LOT_SIZE_INVALID",
        "INDIA_PRICE_TICK_INVALID",
        "INDIA_DERIVATIVE_METADATA_INVALID",
        "INDIA_SEGMENT_INVALID",
        "INDIA_PRODUCT_INVALID",
        "INDIA_TIF_INVALID",
        "INDIA_QUANTITY_FREEZE_INVALID",
        "INDIA_PRICE_BAND_INVALID",
        "INDIA_RULE_SCOPE_MISMATCH",
        "INDIA_RULE_DATA_UNAVAILABLE",
        "INDIA_SESSION_SCOPE_MISMATCH",
        "INDIA_SESSION_DATA_UNAVAILABLE",
        "INDIA_SESSION_PERMISSION_BLOCKED",
    }
)

_BATCH_CODE_PATTERN = re.compile(r"\bB\d+\b")


def sanitize_rule_reason(reason: object) -> str | None:
    """Return pack text safe for public reasons, else None (fail closed).

    Only reasons headed by an allow-listed ``INDIA_*`` rule code and free
    of batch codenames or traceback text may reach users. Anything else —
    including raw exception text — stays in non-user-facing diagnostics.
    """
    if not isinstance(reason, str) or not reason.strip():
        return None
    if reason.split(":", 1)[0].strip() not in _PUBLIC_RULE_CODES:
        return None
    if contains_banned_text(reason):
        return None
    return reason


_APPROVED_SESSION_REJECTIONS: frozenset[str] = frozenset({"india trading session is closed"})
"""Finite vocabulary of plain (non-code) session rejection reasons that
may appear in public output. Anything else falls back to the static
template without interpolating evaluator text."""


def sanitize_session_rejection(reason: object) -> str | None:
    """Return an approved public session rejection reason, else None.

    A reason is public only when it is headed by an allow-listed
    ``INDIA_*`` rule code or appears in the approved plain-text
    vocabulary. Arbitrary evaluator text never reaches users.
    """
    if sanitize_rule_reason(reason) is not None:
        return str(reason)  # already code-gated by sanitize_rule_reason
    if isinstance(reason, str) and reason.strip() in _APPROVED_SESSION_REJECTIONS:
        return reason.strip()
    return None


def sanitize_evidence_text(text: object) -> str | None:
    """Return evidence metadata text safe for the public surface, else None.

    Applies to provenance, rule-set versions, and rule-check reasons:
    banned fragments (batch codenames, tracebacks, file paths) make the
    value ineligible for public evidence.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    if contains_banned_text(text):
        return None
    return text


_RULE_NAME_PATTERN = re.compile(r"[a-z0-9_]+")


def _public_rule_check_name(name: object) -> str:
    """Project a rule-check name onto the public evidence surface.

    Only names matching the engine's snake_case rule-name grammar are
    public; clean-looking but unapproved names collapse to the fixed
    ``india-rule`` identity so arbitrary text never serializes.
    """
    if isinstance(name, str) and _RULE_NAME_PATTERN.fullmatch(name) is not None:
        return name
    return "india-rule"


def _public_rule_check_reason(check: IndiaRuleCheck) -> str:
    """Project one engine rule-check fact onto the public evidence surface.

    Failed checks keep their reason only when it carries an allow-listed
    ``INDIA_*`` rule code; passed checks and anything unapproved collapse
    to fixed text. Banned fragments never reach serialized evidence.
    """
    if not check.passed:
        return sanitize_rule_reason(check.reason) or "india rule check failed (details withheld)"
    return "india rule check passed"


def _family_segment(family: MarketFamily) -> IndianSegment | None:
    return {
        MarketFamily.EQUITY: IndianSegment.EQUITY,
        MarketFamily.DERIVATIVES: IndianSegment.DERIVATIVES,
        MarketFamily.FX: IndianSegment.CURRENCY,
        MarketFamily.COMMODITIES: IndianSegment.COMMODITY,
    }.get(family)


def _best_effort_evidence(
    check_id: str, stage: MarketCheckStage, request: ApprovedExecutionRequest
) -> MarketCheckEvidence | None:
    """Record the request's claimed market context for a failed evaluation.

    Values pass through verbatim (no fabrication); anything unbuildable
    yields None so the runner synthesizes the entry from normalized values.
    """
    try:
        market = request.execution_context.market
        return MarketCheckEvidence(
            check_id=check_id,
            stage=stage,
            outcome=MarketCheckOutcome.UNAVAILABLE,
            region=market.region,
            family=market.family,
            venue=market.venue,
        )
    except (ValueError, AttributeError):
        return None


@dataclass(frozen=True, slots=True)
class IndiaSessionCheck:
    """Pre-dispatch India session/calendar check (neutral contract)."""

    evaluator: Callable[[ApprovedExecutionRequest], IndiaSessionResult]
    check_id: str = "india.session-calendar"

    def __call__(self, request: ApprovedExecutionRequest) -> MarketCheckResult:
        try:
            result = self.evaluator(request)
        except Exception as exc:
            return MarketCheckResult(
                self.check_id,
                MarketCheckOutcome.UNAVAILABLE,
                "india.session-calendar.evaluation-failed",
                "india session/calendar evaluation failed closed",
                detail=f"{type(exc).__name__}: {exc}",
                evidence=_best_effort_evidence(
                    self.check_id, MarketCheckStage.PRE_DISPATCH, request
                ),
            )
        if not isinstance(result, IndiaSessionResult):
            return MarketCheckResult(
                self.check_id,
                MarketCheckOutcome.UNAVAILABLE,
                "india.session-calendar.evaluation-failed",
                "india session/calendar evaluation failed closed",
                detail=f"evaluator returned {type(result).__name__}",
            )
        region, family, venue = normalize_market_context(request.execution_context.market)
        expected_segment = _family_segment(family)
        if (
            not result.calendar_evaluated
            or not result.calendar_version.strip()
            or not result.provenance.strip()
            or result.evaluated_at.tzinfo is None
            or result.evaluated_at.utcoffset() is None
            or result.exchange.value != venue
            or expected_segment is None
            or result.segment is not expected_segment
        ):
            return MarketCheckResult(
                self.check_id,
                MarketCheckOutcome.UNAVAILABLE,
                "india.session-calendar.evidence-missing",
                "india LIVE execution requires authoritative India session/calendar evidence",
                evidence=MarketCheckEvidence(
                    check_id=self.check_id,
                    stage=MarketCheckStage.PRE_DISPATCH,
                    outcome=MarketCheckOutcome.UNAVAILABLE,
                    region=region,
                    family=family,
                    venue=venue,
                ),
            )
        approved_version = sanitize_evidence_text(result.calendar_version)
        approved_provenance = sanitize_evidence_text(result.provenance)
        evidence = MarketCheckEvidence(
            check_id=self.check_id,
            stage=MarketCheckStage.PRE_DISPATCH,
            outcome=MarketCheckOutcome.PASS,
            region=region,
            family=family,
            venue=venue,
            rule_set_version=approved_version,
            provenance=approved_provenance,
            evaluated_at=result.evaluated_at,
            session_evaluated=True,
            session_exchange=result.exchange.value,
            session_segment=result.segment.value,
        )
        if result.decision is not IndiaSessionDecision.ALLOW:
            approved = sanitize_session_rejection(result.reason)
            session_reason = (
                f"india session/calendar blocked the request: {approved}"
                if approved is not None
                else "india session/calendar blocked the request"
            )
            return MarketCheckResult(
                self.check_id,
                MarketCheckOutcome.BLOCK,
                "india.session-calendar.rejected",
                session_reason,
                detail="" if approved is not None else f"withheld: {result.reason}",
                evidence=replace(evidence, outcome=MarketCheckOutcome.BLOCK),
            )
        return MarketCheckResult(
            self.check_id,
            MarketCheckOutcome.PASS,
            None,
            "india session/calendar approved the request",
            evidence=evidence,
        )


@dataclass(frozen=True, slots=True)
class IndiaCompatCheck:
    """Pre-submit India compatibility/rule check (neutral contract)."""

    evaluator: Callable[[ApprovedExecutionRequest], IndiaRuleResult]
    check_id: str = "india.compatibility-rules"

    def __call__(self, request: ApprovedExecutionRequest) -> MarketCheckResult:
        try:
            result = self.evaluator(request)
        except Exception as exc:
            return MarketCheckResult(
                self.check_id,
                MarketCheckOutcome.UNAVAILABLE,
                "india.compatibility.evaluation-failed",
                "india execution-rule evaluation failed closed",
                detail=f"{type(exc).__name__}: {exc}",
                evidence=_best_effort_evidence(self.check_id, MarketCheckStage.PRE_SUBMIT, request),
            )
        if not isinstance(result, IndiaRuleResult):
            return MarketCheckResult(
                self.check_id,
                MarketCheckOutcome.UNAVAILABLE,
                "india.compatibility.evaluation-failed",
                "india execution-rule evaluation failed closed",
                detail=f"evaluator returned {type(result).__name__}",
            )
        region, family, venue = normalize_market_context(request.execution_context.market)
        if (
            not result.compatibility_evaluated
            or result.rule_set_version is None
            or result.provenance is None
            or result.evaluated_at is None
        ):
            return MarketCheckResult(
                self.check_id,
                MarketCheckOutcome.UNAVAILABLE,
                "india.compatibility.evidence-missing",
                "india LIVE execution requires authoritative India venue-rule "
                "compatibility evidence",
                evidence=MarketCheckEvidence(
                    check_id=self.check_id,
                    stage=MarketCheckStage.PRE_SUBMIT,
                    outcome=MarketCheckOutcome.UNAVAILABLE,
                    region=region,
                    family=family,
                    venue=venue,
                ),
            )
        approved_version = sanitize_evidence_text(result.rule_set_version)
        approved_provenance = sanitize_evidence_text(result.provenance)
        rule_checks = tuple(
            MarketRuleCheckEvidence(
                _public_rule_check_name(check.name),
                check.passed,
                _public_rule_check_reason(check),
            )
            for check in result.checks
        )
        evidence = MarketCheckEvidence(
            check_id=self.check_id,
            stage=MarketCheckStage.PRE_SUBMIT,
            outcome=MarketCheckOutcome.PASS,
            region=region,
            family=family,
            venue=venue,
            rule_set_version=approved_version,
            provenance=approved_provenance,
            evaluated_at=result.evaluated_at,
            compatibility_evaluated=True,
            rule_checks=rule_checks,
        )
        if result.decision is not IndiaRuleDecision.APPROVE:
            sanitized = sanitize_rule_reason(result.reason)
            if sanitized is None:
                return MarketCheckResult(
                    self.check_id,
                    MarketCheckOutcome.UNAVAILABLE,
                    "india.compatibility.malformed-evidence",
                    "india rule evidence is malformed",
                    detail=str(result.reason),
                    evidence=replace(evidence, outcome=MarketCheckOutcome.UNAVAILABLE),
                )
            return MarketCheckResult(
                self.check_id,
                MarketCheckOutcome.BLOCK,
                "india.compatibility.rejected",
                f"india execution rules rejected the request: {sanitized}",
                evidence=replace(evidence, outcome=MarketCheckOutcome.BLOCK),
            )
        return MarketCheckResult(
            self.check_id,
            MarketCheckOutcome.PASS,
            None,
            "india execution rules approved the request",
            evidence=evidence,
        )


def india_market_policy(
    *,
    session_evaluator: Callable[[ApprovedExecutionRequest], IndiaSessionResult] | None = None,
    rule_evaluator: Callable[[ApprovedExecutionRequest], IndiaRuleResult] | None = None,
) -> MarketPolicyConfig:
    """Build the default India-required policy with the given evaluators.

    A ``None`` evaluator leaves its stage empty, which fails closed at
    request time — preserving the legacy evaluator-required behavior. All
    other regions stay explicitly core-only.
    """
    checks: list[PlacedCheck] = []
    if session_evaluator is not None:
        checks.append(
            PlacedCheck(
                MarketRegion.INDIA,
                MarketCheckStage.PRE_DISPATCH,
                IndiaSessionCheck(session_evaluator),
            )
        )
    if rule_evaluator is not None:
        checks.append(
            PlacedCheck(
                MarketRegion.INDIA,
                MarketCheckStage.PRE_SUBMIT,
                IndiaCompatCheck(rule_evaluator),
            )
        )
    return MarketPolicyConfig(
        regions=tuple(
            RegionMarketPolicy(
                region=member,
                requires_pack=member is MarketRegion.INDIA,
                required_stages=(
                    frozenset({MarketCheckStage.PRE_DISPATCH, MarketCheckStage.PRE_SUBMIT})
                    if member is MarketRegion.INDIA
                    else frozenset()
                ),
                replaces_session_guard=member is MarketRegion.INDIA,
            )
            for member in MarketRegion
        ),
        checks=tuple(checks),
    )


__all__ = [
    "IndiaCompatCheck",
    "IndiaSessionCheck",
    "india_market_policy",
    "sanitize_rule_reason",
]
