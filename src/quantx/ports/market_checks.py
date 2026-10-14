"""Market-pack pre-trade check contracts (market-neutral).

A market pack contributes policy checks for its region; the application
orchestrator owns the ordered insertion points, short-circuit behavior,
and evidence collection. Packs never see broker adapters, credentials,
or submission permits, so registering a check cannot grant LIVE or
broker-submit capability.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from quantx.domain.deployment import ExecutionMode
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import MarketContext, MarketFamily, MarketRegion


class MarketCheckOutcome(StrEnum):
    """Outcome vocabulary for one market-pack check evaluation."""

    PASS = "PASS"
    BLOCK = "BLOCK"
    UNAVAILABLE = "UNAVAILABLE"
    SKIPPED = "SKIPPED"


class MarketCheckStage(StrEnum):
    """Core-owned insertion points for market policy checks."""

    PRE_DISPATCH = "pre_dispatch"
    PRE_SUBMIT = "pre_submit"


class MarketCheckFailureCode(StrEnum):
    """Stable framework-level failure codes (never batch codenames)."""

    UNKNOWN_REGION = "market-check.unknown-region"
    UNCLASSIFIED_REGION = "market-check.unclassified-region"
    MISSING_REQUIRED_PACK = "market-check.missing-required-pack"
    MISSING_REQUIRED_STAGE = "market-check.missing-required-stage"
    DUPLICATE_CHECK = "market-check.duplicate-check"
    INVALID_CONFIGURATION = "market-check.invalid-configuration"
    EVALUATION_FAILED = "market-check.evaluation-failed"
    MALFORMED_RESULT = "market-check.malformed-result"


SKIPPED_STAGE_STATUS_CODE = "market-check.stage-skipped-by-policy"
"""Status code marking runner-synthesized SKIPPED stage evidence.

SKIPPED entries never carry a failure code and never block; the code
exists so skipped optional stages stay explicitly visible instead of
masquerading as evaluated checks.
"""

_BATCH_CODE_PATTERN = re.compile(r"\bB\d+\b")


def contains_banned_text(text: str) -> bool:
    """Detect batch codenames, tracebacks, or file fragments in user text."""
    return _BATCH_CODE_PATTERN.search(text) is not None or "Traceback" in text or 'File "' in text


def sanitize_public_reason(reason: object, *, check_id: str, blocked: bool) -> str:
    """Return a user-safe reason, replacing untrusted text with a static message.

    Clean pack-authored reasons pass through unchanged; anything that is
    not a non-empty string or that contains banned content becomes a fixed
    per-outcome message naming only the registered check identity.
    """
    if isinstance(reason, str) and reason.strip() and not contains_banned_text(reason):
        return reason
    if blocked:
        return f"{check_id} blocked the request"
    return f"{check_id} evaluation failed closed"


@dataclass(frozen=True, slots=True)
class MarketRuleCheckEvidence:
    """One named rule-check fact carried inside check evidence."""

    name: str
    passed: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("rule check name must not be empty")
        if not self.reason.strip():
            raise ValueError("rule check reason must not be empty")


@dataclass(frozen=True, slots=True)
class MarketCheckEvidence:
    """Immutable evidence for one executed check or skipped optional stage."""

    check_id: str
    stage: MarketCheckStage
    outcome: MarketCheckOutcome
    region: MarketRegion
    family: MarketFamily
    venue: str
    rule_set_version: str | None = None
    provenance: str | None = None
    evaluated_at: datetime | None = None
    session_evaluated: bool = False
    session_exchange: str | None = None
    session_segment: str | None = None
    compatibility_evaluated: bool = False
    rule_checks: tuple[MarketRuleCheckEvidence, ...] = ()
    stage_status_code: str | None = None

    def __post_init__(self) -> None:
        if not self.check_id.strip():
            raise ValueError("check id must not be empty")
        if not self.venue.strip():
            raise ValueError("evidence venue must not be empty")
        if self.evaluated_at is not None and (
            self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None
        ):
            raise ValueError("evaluated_at must be timezone-aware")
        if self.outcome is MarketCheckOutcome.SKIPPED:
            if self.stage_status_code != SKIPPED_STAGE_STATUS_CODE:
                raise ValueError("skipped evidence must carry the skipped-stage status code")
        elif self.stage_status_code is not None:
            raise ValueError("only skipped evidence may carry a stage status code")


@dataclass(frozen=True, slots=True)
class MarketCheckResult:
    """Single check outcome with a public reason and private diagnostics.

    ``reason`` is user-facing and must come from trusted message
    definitions or allow-listed pack vocabulary. ``detail`` carries raw
    diagnostics (including exception text) and is never surfaced to
    users. ``failure_code`` is required for every non-PASS outcome and
    must be None for PASS. Individual checks never return SKIPPED; that
    outcome is synthesized by the runner for policy-declared optional
    stages only.
    """

    check_id: str
    outcome: MarketCheckOutcome
    failure_code: str | None
    reason: str
    detail: str = ""
    evidence: MarketCheckEvidence | None = None

    def __post_init__(self) -> None:
        if not self.check_id.strip():
            raise ValueError("check id must not be empty")
        if self.outcome is MarketCheckOutcome.SKIPPED:
            raise ValueError("individual checks must not return SKIPPED")
        if self.outcome is MarketCheckOutcome.PASS and self.failure_code is not None:
            raise ValueError("passing checks must not carry a failure code")
        if self.outcome is not MarketCheckOutcome.PASS and (
            self.failure_code is None or not self.failure_code.strip()
        ):
            raise ValueError("non-passing checks must carry a failure code")
        if not self.reason.strip():
            raise ValueError("check reason must not be empty")


@dataclass(frozen=True, slots=True)
class MarketCheckSequence:
    """Ordered evidence prefix collected across both insertion points."""

    entries: tuple[MarketCheckEvidence, ...] = ()
    short_circuited: bool = False
    blocking_check_id: str | None = None
    blocking_failure_code: str | None = None

    def __post_init__(self) -> None:
        if self.short_circuited and (
            self.blocking_check_id is None or self.blocking_failure_code is None
        ):
            raise ValueError("a short-circuited sequence must identify the blocking check")
        if not self.short_circuited and (
            self.blocking_check_id is not None or self.blocking_failure_code is not None
        ):
            raise ValueError("a completed sequence must not identify a blocking check")


@runtime_checkable
class PreTradeCheck(Protocol):
    """One market-pack policy check evaluated against an approved request."""

    @property
    def check_id(self) -> str: ...

    def __call__(self, request: ApprovedExecutionRequest) -> MarketCheckResult: ...


@dataclass(frozen=True, slots=True)
class RegionMarketPolicy:
    """Core-owned classification for one market region.

    ``requires_pack`` marks regions whose LIVE requests must run market
    policy; ``required_stages`` must each carry at least one check, while
    ``optional_stages`` may be absent or empty (recorded as SKIPPED).
    ``replaces_session_guard`` is inert unless the region is INDIA: only
    the approved core-owned INDIA+LIVE predicate may skip the core guard,
    so a flag on any other region never disables it.
    """

    region: MarketRegion
    requires_pack: bool = False
    required_stages: frozenset[MarketCheckStage] = frozenset()
    optional_stages: frozenset[MarketCheckStage] = frozenset()
    replaces_session_guard: bool = False

    def __post_init__(self) -> None:
        if self.required_stages & self.optional_stages:
            raise ValueError("a stage cannot be both required and optional")


@dataclass(frozen=True, slots=True)
class PlacedCheck:
    """One check bound to a region and insertion point, in plan order."""

    region: MarketRegion
    stage: MarketCheckStage
    check: PreTradeCheck

    def __post_init__(self) -> None:
        check_id = getattr(self.check, "check_id", None)
        if not isinstance(check_id, str) or not check_id.strip():
            raise ValueError("check id must not be empty")
        if contains_banned_text(check_id):
            raise ValueError("check id must not contain batch codes or diagnostic fragments")


@dataclass(frozen=True, slots=True)
class MarketPolicyConfig:
    """Explicit, validated market-policy configuration.

    Every ``MarketRegion`` member must be classified exactly once, so a
    newly added region fails configuration validation until it is
    classified. Duplicate check identities per region and stage are
    rejected. A required stage with no registered checks fails closed at
    request time (never silently skipped); use ``optional_stages`` for
    stages that may legitimately be empty.
    """

    regions: tuple[RegionMarketPolicy, ...] = ()
    checks: tuple[PlacedCheck, ...] = ()

    def __post_init__(self) -> None:
        seen_regions = [policy.region for policy in self.regions]
        if len(set(seen_regions)) != len(seen_regions):
            raise ValueError("duplicate region policy")
        missing = set(MarketRegion) - set(seen_regions)
        if missing:
            raise ValueError(
                "unclassified regions fail closed: "
                + ",".join(sorted(member.value for member in missing))
            )
        for policy in self.regions:
            if policy.region is MarketRegion.INDIA:
                # Canonical India invariant: India is never core-only and
                # always requires both insertion points for LIVE requests.
                if not policy.requires_pack:
                    raise ValueError("India must not be classified as core-only")
                if policy.required_stages != frozenset(
                    {MarketCheckStage.PRE_DISPATCH, MarketCheckStage.PRE_SUBMIT}
                ):
                    raise ValueError("India LIVE requires both pre-dispatch and pre-submit stages")
            elif policy.requires_pack and not policy.required_stages:
                raise ValueError(
                    f"region {policy.region.value} requires a pack but declares no required stages"
                )
        seen_checks = [
            (placed.region, placed.stage, getattr(placed.check, "check_id", None))
            for placed in self.checks
        ]
        if len(set(seen_checks)) != len(seen_checks):
            raise ValueError("duplicate check identity for region and stage")

    def policy_for(self, region: MarketRegion) -> RegionMarketPolicy:
        """Return the classification for a region (always present)."""
        for policy in self.regions:
            if policy.region is region:
                return policy
        raise UnclassifiedRegion(f"unclassified region fails closed: {region.value}")

    def checks_for(
        self, region: MarketRegion, stage: MarketCheckStage
    ) -> tuple[PreTradeCheck, ...]:
        """Return checks for a region and stage in registration order."""
        return tuple(
            placed.check
            for placed in self.checks
            if placed.region is region and placed.stage is stage
        )


@dataclass(frozen=True, slots=True)
class MarketSelection:
    """Policy outcome for one request's market and execution mode.

    ``applies_pack`` is true only when the region requires a pack and the
    mode is LIVE; every other combination stays core-only without consulting
    any pack. ``skip_session_guard`` is true only for the approved
    core-owned INDIA+LIVE predicate: the region policy must declare
    replacement, the region must be INDIA, and the mode must be LIVE. A
    replacement flag on any other region is inert by construction.
    """

    region: MarketRegion
    family: MarketFamily
    venue: str
    applies_pack: bool
    skip_session_guard: bool
    policy: RegionMarketPolicy


def select_market_policy(
    config: MarketPolicyConfig, market: MarketContext, mode: ExecutionMode
) -> MarketSelection:
    """Select market policy for a request without consulting any pack."""
    region, family, venue = normalize_market_context(market)
    policy = config.policy_for(region)
    applies_pack = policy.requires_pack and mode is ExecutionMode.LIVE
    return MarketSelection(
        region=region,
        family=family,
        venue=venue,
        applies_pack=applies_pack,
        skip_session_guard=(
            applies_pack and policy.replaces_session_guard and region is MarketRegion.INDIA
        ),
        policy=policy,
    )


def default_market_policy() -> MarketPolicyConfig:
    """Configuration preserving legacy behavior with no pack registered.

    India LIVE requires a pack (so it blocks until one is configured);
    every other region is explicitly core-only. Session-guard replacement
    stays declared for India so a later pack behaves as wired today.
    """
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
        )
    )


class UnknownMarketValue(ValueError):
    """A region/family value that coerces to no canonical enum member."""


class UnclassifiedRegion(ValueError):
    """A canonical region with no entry in the policy configuration."""


def coerce_market_context(
    region: MarketRegion | str, family: MarketFamily | str
) -> tuple[MarketRegion, MarketFamily]:
    """Normalize region/family into canonical enum members or fail closed.

    Raw strings that happen to equal a member would otherwise slip past
    ``is`` comparisons; uncoercible values raise instead of selecting a
    default policy.
    """
    try:
        coerced_region = region if isinstance(region, MarketRegion) else MarketRegion(region)
    except ValueError as exc:
        raise UnknownMarketValue(f"unknown market region fails closed: {region!r}") from exc
    try:
        coerced_family = family if isinstance(family, MarketFamily) else MarketFamily(family)
    except ValueError as exc:
        raise UnknownMarketValue(f"unknown market family fails closed: {family!r}") from exc
    return coerced_region, coerced_family


def normalize_market_context(market: MarketContext) -> tuple[MarketRegion, MarketFamily, str]:
    """Coerce a market context's region/family and return selection inputs."""
    region, family = coerce_market_context(market.region, market.family)
    if not market.venue.strip():
        raise ValueError("market venue must not be empty")
    return region, family, market.venue


def market_evidence_to_mapping(evidence: MarketCheckEvidence) -> dict[str, object]:
    """Project evidence into plain JSON-native values in a fixed schema.

    Serializing the mapping with sorted keys yields byte-identical output
    for equal evidence values (fixed clocks/evaluators required for live
    `evaluated_at` equality across runs).
    """
    return {
        "check_id": evidence.check_id,
        "compatibility_evaluated": evidence.compatibility_evaluated,
        "evaluated_at": (
            evidence.evaluated_at.isoformat() if evidence.evaluated_at is not None else None
        ),
        "family": evidence.family.value,
        "outcome": evidence.outcome.value,
        "provenance": evidence.provenance,
        "region": evidence.region.value,
        "rule_checks": [
            {"name": check.name, "passed": check.passed, "reason": check.reason}
            for check in evidence.rule_checks
        ],
        "rule_set_version": evidence.rule_set_version,
        "session_evaluated": evidence.session_evaluated,
        "session_exchange": evidence.session_exchange,
        "session_segment": evidence.session_segment,
        "stage": evidence.stage.value,
        "stage_status_code": evidence.stage_status_code,
        "venue": evidence.venue,
    }


def sequence_to_mapping(sequence: MarketCheckSequence) -> dict[str, object]:
    """Project an ordered evidence sequence into plain JSON-native values."""
    return {
        "blocking_check_id": sequence.blocking_check_id,
        "blocking_failure_code": sequence.blocking_failure_code,
        "entries": [market_evidence_to_mapping(entry) for entry in sequence.entries],
        "short_circuited": sequence.short_circuited,
    }


__all__ = [
    "MarketCheckEvidence",
    "MarketCheckFailureCode",
    "MarketCheckOutcome",
    "MarketCheckResult",
    "MarketCheckSequence",
    "MarketCheckStage",
    "MarketPolicyConfig",
    "MarketRuleCheckEvidence",
    "MarketSelection",
    "PlacedCheck",
    "PreTradeCheck",
    "RegionMarketPolicy",
    "SKIPPED_STAGE_STATUS_CODE",
    "UnclassifiedRegion",
    "UnknownMarketValue",
    "coerce_market_context",
    "contains_banned_text",
    "default_market_policy",
    "market_evidence_to_mapping",
    "normalize_market_context",
    "sanitize_public_reason",
    "select_market_policy",
    "sequence_to_mapping",
]
