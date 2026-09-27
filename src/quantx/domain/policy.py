"""Deterministic execution policy gates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .capabilities import Capability
from .order_intents import TradeIntent


class PolicyDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True, slots=True)
class PolicyContext:
    granted_capabilities: frozenset[str] = frozenset()
    live_trading_enabled: bool = False
    manual_approval: bool = False


@dataclass(frozen=True, slots=True)
class PolicyResult:
    decision: PolicyDecision
    reason: str
    missing_capabilities: tuple[str, ...] = ()

    @property
    def approved(self) -> bool:
        return self.decision is PolicyDecision.APPROVE


class ExecutionPolicyEngine:
    """Fail-closed policy evaluation for normalized trade intents."""

    _live_required = frozenset(
        {
            Capability.CREATE_LIVE_ORDER.value,
            Capability.EXECUTE_LIVE.value,
            Capability.ACCESS_BROKER.value,
        }
    )

    def evaluate(self, intent: TradeIntent, context: PolicyContext) -> PolicyResult:
        if intent.execution_context is None:
            return PolicyResult(PolicyDecision.REJECT, "execution context is required")

        requested = frozenset(intent.required_capabilities)
        if intent.execution_context.execution_mode.value == "live":
            if not context.live_trading_enabled:
                return PolicyResult(
                    PolicyDecision.REJECT,
                    "live trading is disabled by execution policy",
                )
            requested |= self._live_required

        missing = tuple(sorted(requested - context.granted_capabilities))
        if missing:
            return PolicyResult(
                PolicyDecision.REJECT,
                "required execution capabilities are not granted",
                missing,
            )

        if intent.approval_required and not context.manual_approval:
            return PolicyResult(
                PolicyDecision.APPROVAL_REQUIRED,
                "explicit manual approval is required",
            )

        return PolicyResult(PolicyDecision.APPROVE, "execution policy approved")
