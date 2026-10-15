"""Market-pack pre-trade check contracts (market-neutral).

A market pack contributes policy checks for its region; the application
orchestrator owns the ordered insertion points, short-circuit behavior,
and evidence collection. Packs never see broker adapters, credentials,
or submission permits, so registering a check cannot grant LIVE or
broker-submit capability.
"""

from __future__ import annotations

import importlib
import re
import types
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cache
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
    PACK_BLOCKED = "market-check.pack-blocked"
    PACK_UNAVAILABLE = "market-check.pack-unavailable"


SKIPPED_STAGE_STATUS_CODE = "market-check.stage-skipped-by-policy"
"""Status code marking runner-synthesized SKIPPED stage evidence.

SKIPPED entries never carry a failure code and never block; the code
exists so skipped optional stages stay explicitly visible instead of
masquerading as evaluated checks.
"""

_BATCH_CODE_PATTERN = re.compile(r"\bB\d+\b")
_CHECK_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_FAILURE_CODE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_RULE_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*")
_RULE_SET_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}")
_PROVENANCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _immutable_registry(entries: Mapping[str, frozenset[str]]) -> Mapping[str, frozenset[str]]:
    """Copy ``entries`` into a read-only mapping of read-only collections.

    The copy matters as much as the proxy: the caller's dictionary must not
    survive as a private alias that could still be mutated at runtime. Nested
    values are already frozensets, so nothing inside the registry is writable
    once this returns.
    """
    return types.MappingProxyType({key: frozenset(value) for key, value in entries.items()})


_TRUSTED_FAILURE_CODES: Mapping[str, frozenset[str]] = _immutable_registry(
    {
        "india.session-calendar": frozenset(
            {
                "india.session-calendar.evaluation-failed",
                "india.session-calendar.evidence-missing",
                "india.session-calendar.rejected",
            }
        ),
        "india.compatibility-rules": frozenset(
            {
                "india.compatibility.evaluation-failed",
                "india.compatibility.evidence-missing",
                "india.compatibility.rejected",
                "india.compatibility.malformed-evidence",
            }
        ),
    }
)
"""Core-owned registry of trusted public failure codes per check identity.

Only codes listed here may surface in ``blocking_failure_code`` or
serialized evidence. Codes from checks absent from this registry are
rewritten to the framework-owned ``PACK_BLOCKED``/``PACK_UNAVAILABLE``
codes; framework-produced codes (``EVALUATION_FAILED``,
``MALFORMED_RESULT``, ...) are runner-owned and never rewritten.
"""

TRUSTED_FAILURE_CODES: Mapping[str, frozenset[str]] = _TRUSTED_FAILURE_CODES
"""Read-only public view of the trusted failure-code registry.

The runner resolves codes through :func:`trusted_failure_codes`, which
reads the private immutable registry rather than this name, so rebinding
or mutating it cannot change what the runner authorizes.
"""


def trusted_failure_codes(check_id: object) -> frozenset[str] | None:
    """Return the immutable trusted code set for a check identity, or None.

    Untrusted identities have no trusted codes at all, so their declared
    codes are rewritten to framework-owned values.
    """
    if not isinstance(check_id, str):
        return None
    return _TRUSTED_FAILURE_CODES.get(check_id)


@dataclass(frozen=True, slots=True)
class TrustedCheckImplementation:
    """Core-owned reference to one approved implementation surface.

    ``module`` and ``attribute`` name where the approved class lives in
    reviewed source. They are resolved by the core, never supplied by a
    registering pack, and the resolved object must actually be defined in
    ``module`` — so pointing an approved name at a caller-defined class
    fails closed instead of granting trust.
    """

    module: str
    attribute: str


@cache
def _approved_implementation(implementation: TrustedCheckImplementation) -> type | None:
    """Resolve and validate one approved class object (cached, fail closed).

    Returns None when the module cannot be imported, the attribute is
    missing or not a class, or the class is not defined in the approved
    module. Callers compare by identity, never by the class' ``__module__``
    string, which any caller-defined class can set.
    """
    try:
        module = importlib.import_module(implementation.module)
        candidate = getattr(module, implementation.attribute, None)
    except Exception:
        return None
    if not isinstance(candidate, type) or candidate.__module__ != implementation.module:
        return None
    return candidate


@dataclass(frozen=True, slots=True)
class TrustedCheckBinding:
    """Core-owned association between a trusted check identity and the
    exact approved implementation that may carry it.

    Trust requires all three bindings to hold at execution time:

    - ``implementation``: the placed check's class object must be the very
      same object the core resolves from the approved surface. A
      caller-defined class — even one registered under a trusted identity,
      subclassing the approved class, or spoofing ``__module__`` — never
      matches, because object identity cannot be asserted from outside.
    - ``regions``: the placement region must be one of these.
    - ``stage``: the placement insertion point must be exactly this one.
    """

    implementation: TrustedCheckImplementation
    regions: frozenset[MarketRegion]
    stage: MarketCheckStage


_TRUSTED_CHECK_BINDINGS: Mapping[str, TrustedCheckBinding] = types.MappingProxyType(
    {
        "india.session-calendar": TrustedCheckBinding(
            implementation=TrustedCheckImplementation(
                "quantx.india.market_checks", "IndiaSessionCheck"
            ),
            regions=frozenset({MarketRegion.INDIA}),
            stage=MarketCheckStage.PRE_DISPATCH,
        ),
        "india.compatibility-rules": TrustedCheckBinding(
            implementation=TrustedCheckImplementation(
                "quantx.india.market_checks", "IndiaCompatCheck"
            ),
            regions=frozenset({MarketRegion.INDIA}),
            stage=MarketCheckStage.PRE_SUBMIT,
        ),
    }
)
"""Core-owned binding of trusted identities to approved implementations.

A caller-controlled check ID grants nothing: an implementation is trusted
only when it *is* the approved class, and its placement region and
insertion stage both match this registry. Membership is decided by
repository review of the producing code, never by a check's
self-declaration. Impersonating checks are treated as generic (static
fallback reasons, framework-owned rewritten codes).
"""

TRUSTED_CHECK_BINDINGS: Mapping[str, TrustedCheckBinding] = _TRUSTED_CHECK_BINDINGS
"""Read-only public view of the trusted implementation bindings.

The runner resolves trust through :func:`is_trusted_check`, which reads
the private immutable registry rather than this name.
"""


def trusted_check_binding(check_id: object) -> TrustedCheckBinding | None:
    """Return the immutable core-owned binding for a check identity, or None."""
    if not isinstance(check_id, str):
        return None
    return _TRUSTED_CHECK_BINDINGS.get(check_id)


def is_trusted_check(
    check_id: object,
    check: object,
    *,
    region: MarketRegion,
    stage: MarketCheckStage,
) -> bool:
    """Decide trust for one placed check entirely inside the core.

    Trust holds only when a core-owned binding exists for the identity,
    the check's class object is the exact approved implementation (identity
    comparison, so no caller metadata can impersonate it), and the
    placement region and stage both match. Anything else is untrusted.
    """
    binding = trusted_check_binding(check_id)
    if binding is None or region not in binding.regions or stage is not binding.stage:
        return False
    approved = _approved_implementation(binding.implementation)
    return approved is not None and type(check) is approved


def contains_banned_text(text: str) -> bool:
    """Detect batch codenames, tracebacks, or file fragments in user text."""
    return _BATCH_CODE_PATTERN.search(text) is not None or "Traceback" in text or 'File "' in text


def is_valid_check_id(check_id: object) -> bool:
    """Enforce the narrow check-identifier grammar plus the banned-text rule.

    Compatible with existing identifiers such as ``india.session-calendar``
    and ``NORTH_AMERICA.pre-a``; rejects spaces, newlines, control
    characters, arbitrary punctuation, and diagnostic fragments.
    """
    return (
        isinstance(check_id, str)
        and _CHECK_ID_PATTERN.fullmatch(check_id) is not None
        and not contains_banned_text(check_id)
    )


def is_valid_failure_code(code: object) -> bool:
    """Enforce the narrow failure-code grammar plus the banned-text rule."""
    return (
        isinstance(code, str)
        and _FAILURE_CODE_PATTERN.fullmatch(code) is not None
        and not contains_banned_text(code)
    )


APPROVED_RULE_CHECK_NAMES: frozenset[str] = frozenset(
    {
        "derivative_metadata",
        "evaluation_timestamp",
        "india-rule",
        "instrument_identity",
        "order_type",
        "order_type_snapshot",
        "price_band",
        "price_tick",
        "product",
        "product_snapshot",
        "quantity",
        "quantity_freeze",
        "rule_scope",
        "segment",
        "tick",
        "time_in_force",
    }
)
"""Core-owned finite vocabulary of rule names allowed in public evidence.

A name must be a rule this repository actually evaluates: an arbitrary
snake_case word is still unreviewed text that a pack chose, so it never
reaches serialized evidence. ``india-rule`` is the fixed collapse target
for unapproved names; ``tick`` is retained as an approved alias for the
price-tick rule.
"""

FALLBACK_RULE_CHECK_NAME = "india-rule"
"""Fixed rule name used when a pack reports an unapproved rule name."""

RULE_CHECK_PASSED_REASON = "india rule check passed"
"""Framework-owned fixed reason for a rule fact that passed."""

RULE_CHECK_WITHHELD_REASON = "india rule check failed (details withheld)"
"""Framework-owned fixed reason for a rule fact whose text is not approved."""


def is_valid_rule_check_name(name: object) -> bool:
    """Accept only reviewed rule names from the core-owned vocabulary."""
    return isinstance(name, str) and name in APPROVED_RULE_CHECK_NAMES


def is_valid_rule_set_version(version: object) -> bool:
    """Accept a bounded, token-shaped rule-set version identifier.

    Versioned venue/rule data uses opaque version tokens (``rules-v1``,
    ``NSE-EQ-2026-01``). Free text, paths, and quoted diagnostics are
    rejected even when they carry no banned fragment.
    """
    return (
        isinstance(version, str)
        and _RULE_SET_VERSION_PATTERN.fullmatch(version) is not None
        and not contains_banned_text(version)
    )


def is_valid_provenance(provenance: object) -> bool:
    """Accept a bounded, token-shaped provenance identifier.

    Provenance names the source of evaluated rule data. Only an opaque
    identifier token is public; a readable sentence about where the data
    came from is unreviewed text and never serializes.
    """
    return (
        isinstance(provenance, str)
        and _PROVENANCE_PATTERN.fullmatch(provenance) is not None
        and not contains_banned_text(provenance)
    )


def _split_rule_segments(reason: str) -> tuple[tuple[str, str], ...] | None:
    """Split ``CODE: text`` segments joined by ``"; "``, else None.

    Aggregate rule rejections join their violations with ``"; "``, so the
    structure is validated segment by segment rather than by trusting the
    leading code alone. A message that cannot be split this way is not an
    approved aggregate reason.
    """
    segments: list[tuple[str, str]] = []
    for part in reason.split("; "):
        code, separator, text = part.partition(": ")
        if not separator or _RULE_CODE_PATTERN.fullmatch(code) is None:
            return None
        if contains_banned_text(part):
            return None
        segments.append((code, text))
    return tuple(segments) if segments else None


def is_valid_aggregate_rule_reason(reason: object) -> bool:
    """Accept a ``CODE: text`` aggregate reason with bounded segment text.

    Structure, code grammar, and banned-text rules are enforced here; the
    per-code trusted-message contract is applied by the producing pack,
    which owns the reviewed templates for its own vocabulary.
    """
    if not isinstance(reason, str) or not reason.strip():
        return False
    segments = _split_rule_segments(reason)
    if segments is None:
        return False
    return all(text.strip() and len(text) <= 256 for _, text in segments)


def is_valid_rule_check_reason(reason: object) -> bool:
    """Accept one public rule-fact reason.

    A reason is either a framework-owned fixed text (a passed fact, or a
    failed fact whose detail was withheld) or a single-segment ``CODE: text``
    value that satisfies the aggregate structure.
    """
    if reason in (RULE_CHECK_PASSED_REASON, RULE_CHECK_WITHHELD_REASON):
        return True
    return is_valid_aggregate_rule_reason(reason)


def sanitize_public_reason(reason: object, *, check_id: str, blocked: bool, trusted: bool) -> str:
    """Return a user-safe reason under the core-owned trust policy.

    A reason passes through only when the producing check is trusted
    (its vocabulary is reviewed: static messages or an allow-listed
    rule-code contract) and the text itself is a clean non-empty string
    without banned content. Everything else becomes a fixed per-outcome
    message naming only the registered check identity.
    """
    if trusted and isinstance(reason, str) and reason.strip() and not contains_banned_text(reason):
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
    """One market-pack policy check evaluated against an approved request.

    Trust is never self-declared: :func:`is_trusted_check` decides whether
    a placed check may return trusted public reasons and codes by comparing
    its class object against the core-owned ``TRUSTED_CHECK_BINDINGS``
    registry plus its placement. All other checks get static fallback
    reasons and framework-owned rewritten codes.
    """

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
    """One check bound to a region and insertion point, in plan order.

    ``validated_check_id`` snapshots the identifier validated at
    registration; the runner uses this snapshot instead of re-reading the
    live object, so a check whose identifier changes or turns invalid
    after registration fails closed against the registered identity.
    """

    region: MarketRegion
    stage: MarketCheckStage
    check: PreTradeCheck
    validated_check_id: str = ""

    def __post_init__(self) -> None:
        check_id = getattr(self.check, "check_id", None)
        if not isinstance(check_id, str) or not is_valid_check_id(check_id):
            raise ValueError("check id must use the identifier grammar and be codename-free")
        object.__setattr__(self, "validated_check_id", check_id)


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
            (placed.region, placed.stage, placed.validated_check_id) for placed in self.checks
        ]
        if len(set(seen_checks)) != len(seen_checks):
            raise ValueError("duplicate check identity for region and stage")

    def policy_for(self, region: MarketRegion) -> RegionMarketPolicy:
        """Return the classification for a region (always present)."""
        for policy in self.regions:
            if policy.region is region:
                return policy
        raise UnclassifiedRegion(f"unclassified region fails closed: {region.value}")

    def checks_for(self, region: MarketRegion, stage: MarketCheckStage) -> tuple[PlacedCheck, ...]:
        """Return placements for a region and stage in registration order."""
        return tuple(
            placed for placed in self.checks if placed.region is region and placed.stage is stage
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
    "APPROVED_RULE_CHECK_NAMES",
    "FALLBACK_RULE_CHECK_NAME",
    "RULE_CHECK_PASSED_REASON",
    "RULE_CHECK_WITHHELD_REASON",
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
    "TRUSTED_CHECK_BINDINGS",
    "TRUSTED_FAILURE_CODES",
    "TrustedCheckBinding",
    "TrustedCheckImplementation",
    "UnclassifiedRegion",
    "UnknownMarketValue",
    "coerce_market_context",
    "contains_banned_text",
    "default_market_policy",
    "is_trusted_check",
    "is_valid_aggregate_rule_reason",
    "is_valid_check_id",
    "is_valid_failure_code",
    "is_valid_provenance",
    "is_valid_rule_check_name",
    "is_valid_rule_check_reason",
    "is_valid_rule_set_version",
    "market_evidence_to_mapping",
    "normalize_market_context",
    "sanitize_public_reason",
    "select_market_policy",
    "sequence_to_mapping",
    "trusted_check_binding",
    "trusted_failure_codes",
]
