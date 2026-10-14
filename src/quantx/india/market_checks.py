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
    normalize_market_context,
)

from .domain import IndianSegment
from .execution_rules import IndiaRuleDecision, IndiaRuleResult
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
    if _BATCH_CODE_PATTERN.search(reason) is not None:
        return None
    if "Traceback" in reason or 'File "' in reason:
        return None
    return reason


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
        evidence = MarketCheckEvidence(
            check_id=self.check_id,
            stage=MarketCheckStage.PRE_DISPATCH,
            outcome=MarketCheckOutcome.PASS,
            region=region,
            family=family,
            venue=venue,
            rule_set_version=result.calendar_version,
            provenance=result.provenance,
            evaluated_at=result.evaluated_at,
            session_evaluated=True,
            session_exchange=result.exchange.value,
            session_segment=result.segment.value,
        )
        if result.decision is not IndiaSessionDecision.ALLOW:
            session_reason = result.reason
            if (
                not session_reason.strip()
                or _BATCH_CODE_PATTERN.search(session_reason) is not None
                or "Traceback" in session_reason
            ):
                session_reason = "india session/calendar blocked the request"
            else:
                session_reason = f"india session/calendar blocked the request: {session_reason}"
            return MarketCheckResult(
                self.check_id,
                MarketCheckOutcome.BLOCK,
                "india.session-calendar.rejected",
                session_reason,
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
        evidence = MarketCheckEvidence(
            check_id=self.check_id,
            stage=MarketCheckStage.PRE_SUBMIT,
            outcome=MarketCheckOutcome.PASS,
            region=region,
            family=family,
            venue=venue,
            rule_set_version=result.rule_set_version,
            provenance=result.provenance,
            evaluated_at=result.evaluated_at,
            compatibility_evaluated=True,
            rule_checks=tuple(
                MarketRuleCheckEvidence(check.name, check.passed, check.reason)
                for check in result.checks
            ),
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
