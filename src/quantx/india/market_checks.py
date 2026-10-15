"""India market-pack pre-trade checks behind the neutral check contract.

These adapters move the India session/calendar and compatibility/rule
evaluation (including coherence validation) out of application
orchestration. They project India-owned results into neutral
``MarketCheckResult`` values; India result classes never cross into
``quantx.application``.
"""

from __future__ import annotations

import re
import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import MarketFamily, MarketRegion
from quantx.ports.market_checks import (
    FALLBACK_RULE_CHECK_NAME,
    RULE_CHECK_PASSED_REASON,
    RULE_CHECK_WITHHELD_REASON,
    MarketCheckEvidence,
    MarketCheckOutcome,
    MarketCheckResult,
    MarketCheckStage,
    MarketPolicyConfig,
    MarketRuleCheckEvidence,
    PlacedCheck,
    RegionMarketPolicy,
    is_valid_aggregate_rule_reason,
    is_valid_provenance,
    is_valid_rule_check_name,
    is_valid_rule_set_version,
    normalize_market_context,
    pin_trusted_implementations,
)

from .domain import IndianSegment
from .execution_rules import IndiaRuleCheck, IndiaRuleDecision, IndiaRuleResult
from .session_calendar import IndiaSessionDecision, IndiaSessionResult

_DECIMAL_FIELD = r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?"
"""Exact Decimal rendering used by approved rule messages."""

_VOCABULARY_FIELD = r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}"
"""Bounded identifier-shaped field (instrument ids, enum values, session ids)."""

_PRICE_FIELD_TEMPLATES: tuple[str, ...] = ("limit_price", "stop_price")
"""Finite vocabulary of order price fields a rule message may name."""

_REASON_TEMPLATES: Mapping[str, tuple[str, ...]] = types.MappingProxyType(
    {
        "INDIA_INSTRUMENT_MISMATCH": (
            "specification instrument {instrument_id} does not match "
            "order instrument {instrument_id}",
        ),
        "INDIA_ORDER_TYPE_INVALID": (
            "unsupported order type {vocabulary}",
            "order type {vocabulary} is not permitted by the venue rule snapshot",
        ),
        "INDIA_QUANTITY_INVALID": ("quantity must be a positive number",),
        "INDIA_LOT_SIZE_INVALID": (
            "instrument lot size is invalid",
            "quantity {quantity} is not a multiple of lot size {quantity}",
        ),
        "INDIA_PRICE_TICK_INVALID": (
            "instrument tick size is invalid",
            "{price_field} does not align to tick size {quantity}",
        ),
        "INDIA_DERIVATIVE_METADATA_INVALID": (
            "derivative contract metadata is not coherent",
            "non-derivative instrument carries derivative metadata",
        ),
        "INDIA_SEGMENT_INVALID": (
            "no India-universal segment is defined for asset class {vocabulary}",
            "asset class {vocabulary} must not use segment {vocabulary}",
        ),
        "INDIA_PRODUCT_INVALID": (
            "product {vocabulary} is not compatible with asset class {vocabulary}",
            "product {vocabulary} is not permitted by the venue rule snapshot",
        ),
        "INDIA_TIF_INVALID": (
            "time-in-force {vocabulary} is not permitted by the venue rule snapshot",
        ),
        "INDIA_QUANTITY_FREEZE_INVALID": ("quantity {quantity} exceeds freeze {quantity}",),
        "INDIA_PRICE_BAND_INVALID": ("price {quantity} is outside [{quantity}, {quantity}]",),
        "INDIA_RULE_SCOPE_MISMATCH": (
            "venue rule scope exchange {vocabulary} does not apply to {vocabulary}",
            "venue rule scope segment {vocabulary} does not apply to {vocabulary}",
            "venue rule scope instrument {instrument_id} does not apply to {instrument_id}",
        ),
        "INDIA_RULE_DATA_UNAVAILABLE": (
            "evaluation timestamp must be aware",
            "venue rule scope is unknown",
            "venue allowed order types are unknown",
            "venue allowed time-in-force set is unknown",
            "applicable quantity freeze is unknown",
            "applicable price band is unknown",
        ),
        "INDIA_SESSION_SCOPE_MISMATCH": (
            "calendar exchange does not match request market",
            "calendar segment does not match request market",
        ),
        "INDIA_SESSION_DATA_UNAVAILABLE": (
            "evaluation timestamp must be aware",
            "calendar coverage is unknown",
        ),
        "INDIA_SESSION_PERMISSION_BLOCKED": ("session {vocabulary} does not permit {vocabulary}",),
    }
)
"""India-owned trusted public-message templates, keyed by rule code.

Each code may render exactly these message shapes. Every variable is a
validated structured field (exact decimal, bounded identifier, or a
finite price-field vocabulary) and every shape is matched end to end, so
an approved code never licenses an arbitrary trailing suffix. This is the
India half of the core-owned reason contract: the core enforces the
``CODE: text`` segment structure and this registry constrains the values.
"""

_TEMPLATE_FIELDS: Mapping[str, str] = types.MappingProxyType(
    {
        "quantity": _DECIMAL_FIELD,
        "vocabulary": _VOCABULARY_FIELD,
        "instrument_id": _VOCABULARY_FIELD,
    }
)


def _compile_template(template: str) -> str:
    """Turn a trusted template into a fully anchored regular expression.

    Placeholders are substituted with their validated field grammar and
    every literal run is escaped, so a message only matches when it is
    exactly the approved shape — nothing may follow the final field.
    """
    parts: list[str] = []
    index = 0
    for match in re.finditer(r"\{(\w+)\}", template):
        parts.append(re.escape(template[index : match.start()]))
        field = match.group(1)
        index = match.end()
        if field == "price_field":
            parts.append(f"(?:{'|'.join(_PRICE_FIELD_TEMPLATES)})")
            continue
        grammar = _TEMPLATE_FIELDS.get(field)
        if grammar is None:
            raise ValueError(f"unknown rule-reason template field: {field}")
        parts.append(f"({grammar})")
    parts.append(re.escape(template[index:]))
    return "".join(parts)


_COMPILED_TEMPLATES: Mapping[str, tuple[re.Pattern[str], ...]] = types.MappingProxyType(
    {
        code: tuple(re.compile(_compile_template(template)) for template in templates)
        for code, templates in _REASON_TEMPLATES.items()
    }
)


def _approved_segment(segment: str) -> str | None:
    """Return the segment when it exactly matches a trusted template."""
    code, separator, text = segment.partition(": ")
    if not separator:
        return None
    patterns = _COMPILED_TEMPLATES.get(code)
    if patterns is None:
        return None
    if any(pattern.fullmatch(text) is not None for pattern in patterns):
        return segment
    return None


def sanitize_rule_reason(reason: object) -> str | None:
    """Return pack text safe for public reasons, else None (fail closed).

    A reason is public only when it is a ``; ``-joined list of
    ``CODE: text`` segments whose code is an approved ``INDIA_*`` rule code
    and whose text matches that code's trusted template exactly. An
    approved code heading arbitrary extra text is therefore withheld, and
    raw exception text never reaches users. The approved text is returned
    unchanged, so valid messages stay byte-identical.
    """
    if not isinstance(reason, str) or not is_valid_aggregate_rule_reason(reason):
        return None
    approved = tuple(_approved_segment(segment) for segment in reason.split("; "))
    if any(segment is None for segment in approved):
        return None
    return "; ".join(segment for segment in approved if segment is not None)


_APPROVED_SESSION_REJECTIONS: frozenset[str] = frozenset(
    {
        "india trading calendar holiday",
        "india trading session is closed",
    }
)
"""Finite vocabulary of plain (non-code) session rejection reasons that
may appear in public output. Anything else falls back to the static
template without interpolating evaluator text."""


def sanitize_session_rejection(reason: object) -> str | None:
    """Return an approved public session rejection reason, else None.

    A reason is public only when it is an approved plain-text vocabulary
    item or every ``CODE: text`` segment matches its trusted template.
    Arbitrary evaluator text never reaches users.
    """
    approved = sanitize_rule_reason(reason)
    if approved is not None:
        return approved
    if isinstance(reason, str) and reason.strip() in _APPROVED_SESSION_REJECTIONS:
        return reason.strip()
    return None


def approved_rule_set_version(version: object) -> str | None:
    """Return a rule-set version eligible for public evidence, else None.

    Versioned venue/rule data is identified by an opaque version token;
    readable text, paths, and diagnostic fragments are dropped.
    """
    if not is_valid_rule_set_version(version):
        return None
    return version if isinstance(version, str) else None


def approved_provenance(provenance: object) -> str | None:
    """Return a provenance identifier eligible for public evidence, else None.

    Only a bounded token naming the evaluated rule data may be recorded; a
    sentence about where the data came from is unreviewed text.
    """
    if not is_valid_provenance(provenance):
        return None
    return provenance if isinstance(provenance, str) else None


def _public_rule_check_name(name: object) -> str:
    """Project a rule-check name onto the public evidence surface.

    Only names in the core-owned rule vocabulary are public; clean-looking
    but unapproved names collapse to the fixed fallback identity so
    arbitrary text never serializes.
    """
    if is_valid_rule_check_name(name):
        return str(name)
    return FALLBACK_RULE_CHECK_NAME


def _public_rule_check_reason(check: IndiaRuleCheck) -> str:
    """Project one engine rule-check fact onto the public evidence surface.

    Failed checks keep their reason only when every segment matches the
    code's trusted template; passed checks and anything unapproved collapse
    to fixed text. Unapproved text never reaches serialized evidence.
    """
    if not check.passed:
        return sanitize_rule_reason(check.reason) or RULE_CHECK_WITHHELD_REASON
    return RULE_CHECK_PASSED_REASON


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
        version_value = approved_rule_set_version(result.calendar_version)
        provenance_value = approved_provenance(result.provenance)
        evidence = MarketCheckEvidence(
            check_id=self.check_id,
            stage=MarketCheckStage.PRE_DISPATCH,
            outcome=MarketCheckOutcome.PASS,
            region=region,
            family=family,
            venue=venue,
            rule_set_version=version_value,
            provenance=provenance_value,
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
        version_value = approved_rule_set_version(result.rule_set_version)
        provenance_value = approved_provenance(result.provenance)
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
            rule_set_version=version_value,
            provenance=provenance_value,
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


pin_trusted_implementations()
"""Pin the approved implementation identities at adapter import time.

Any code that rebinds ``IndiaSessionCheck``/``IndiaCompatCheck`` must
import this module first, so the pin always observes the reviewed classes
before pack-supplied checks can execute or attack the binding. See
``quantx.ports.market_checks.pin_trusted_implementations`` for the exact
guarantee and its explicit exclusions.
"""


__all__ = [
    "IndiaCompatCheck",
    "IndiaSessionCheck",
    "approved_provenance",
    "approved_rule_set_version",
    "india_market_policy",
    "sanitize_rule_reason",
    "sanitize_session_rejection",
]
