"""Deterministic refresh of unresolved reconciliation evidence.

The canonical reconcilers stay pure comparison components and the order-state
workflow stays the single place where evidence becomes a normalized result.
This application-layer coordinator re-observes broker evidence through an
explicit provider seam and re-runs the workflow. Definitive outcomes require
explicitly required evidence; UNKNOWN can never become definitive without it.
No sleeps, threads, timers, background jobs, or network behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from quantx.domain.value_objects import AccountId, BrokerConnectionId
from quantx.execution.idempotency import IdempotencyStore
from quantx.execution.ports import ExecutionReceipt
from quantx.integrations.reconciliation.account import AccountFinancialState
from quantx.integrations.reconciliation.broker_evidence import (
    BrokerOrderEvidence,
    BrokerOrderEvidenceStatus,
)
from quantx.integrations.reconciliation.orders import (
    OrderObservation,
    OrderReconciliationStatus,
)
from quantx.integrations.reconciliation.positions import (
    PositionState,
    ReconciliationPolicy,
)

from .not_found_policy import (
    NotFoundResolution,
    NotFoundResolutionPolicy,
    evaluate_not_found_resolution,
)
from .reconciliation import (
    OrderStateReconciliationResult,
    OrderStateReconciliationWorkflow,
    OrderWorkflowStatus,
)


class ReconciliationEvidenceProvider(Protocol):
    """Explicit seam for re-observing broker evidence, offline-testable.

    Broker-order lookup returns explicit FOUND/NOT_FOUND/UNKNOWN evidence so
    that authoritative absence can never be conflated with lookup failure.
    """

    def fetch_broker_order(
        self,
        *,
        account_id: AccountId | None,
        connection_id: BrokerConnectionId | None,
        order_id: UUID | None,
    ) -> BrokerOrderEvidence: ...

    def fetch_broker_position(
        self,
        *,
        account_id: AccountId | None,
        connection_id: BrokerConnectionId | None,
        instrument_id: str,
    ) -> PositionState | None: ...

    def fetch_broker_account(
        self,
        *,
        account_id: AccountId | None,
        connection_id: BrokerConnectionId | None,
    ) -> AccountFinancialState | None: ...


@dataclass(frozen=True, slots=True)
class RefreshPolicy:
    """Explicit budget for evidence refresh attempts."""

    max_attempts: int = 3

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")


@dataclass(frozen=True, slots=True)
class DefinitiveEvidencePolicy:
    """Which evidence domains must match for a definitive reconciliation.

    The default is conservative: order, position, and account evidence must
    all be definitively matched, and broker-order evidence must carry matching
    account/connection scope. Narrower workflows opt out explicitly.

    ``advisory_account_amounts`` keeps account evidence collected and visible
    while treating pure balance deltas (cash/equity/margin amounts that differ
    on both sides) as contextual rather than resolution-blocking. Account
    identity, availability, and staleness findings still block. The semantic
    basis is that balances are not order-identity evidence: intraday cash
    movement, fees, or margin drift must not veto an otherwise definitively
    identified broker order.
    """

    require_position: bool = True
    require_account: bool = True
    require_order_scope: bool = True
    advisory_account_amounts: bool = False

    @classmethod
    def all_required(cls) -> DefinitiveEvidencePolicy:
        return cls(
            require_position=True,
            require_account=True,
            require_order_scope=True,
        )

    @classmethod
    def order_and_position(cls) -> DefinitiveEvidencePolicy:
        return cls(require_position=True, require_account=False)

    @classmethod
    def order_only(cls) -> DefinitiveEvidencePolicy:
        return cls(require_position=False, require_account=False)

    @classmethod
    def live_recovery(cls) -> DefinitiveEvidencePolicy:
        return cls(
            require_position=True,
            require_account=True,
            require_order_scope=True,
            advisory_account_amounts=True,
        )


@dataclass(frozen=True, slots=True)
class EvidenceRefreshOutcome:
    """Latest canonical result plus the refresh trail that produced it.

    ``not_found_eligibility`` surfaces the conservative NOT_FOUND policy
    verdict when broker absence was observed. It is informational only:
    eligibility never resolves anything by itself.
    """

    result: OrderStateReconciliationResult
    attempts: int
    refreshed_domains: tuple[str, ...]
    definitive: bool
    reasons: tuple[str, ...] = ()
    broker_order: OrderObservation | None = None
    broker_position: PositionState | None = None
    broker_account: AccountFinancialState | None = None
    not_found_eligibility: NotFoundResolution | None = None


_ADVISORY_ACCOUNT_AMOUNT_FIELDS = frozenset(
    {"available_cash", "equity", "margin_used", "margin_available"}
)


class ReconciliationIdempotencyResolver:
    """Resolve a pending reservation only from a definitive canonical receipt."""

    @staticmethod
    def resolve(
        outcome: EvidenceRefreshOutcome,
        receipt: ExecutionReceipt,
        *,
        request_fingerprint: str,
        idempotency: IdempotencyStore,
    ) -> bool:
        if not outcome.definitive:
            return False
        if outcome.result.order_id is not None and receipt.order_id != outcome.result.order_id:
            raise ValueError("reconciliation order identity does not match receipt")
        if not isinstance(receipt.client_order_id, UUID):
            raise ValueError("receipt client_order_id must be a UUID for idempotency resolution")
        idempotency.resolve_pending(
            receipt.client_order_id,
            request_fingerprint,
            receipt.receipt_id,
        )
        return True


class ReconciliationEvidenceRefresher:
    """Refresh unresolved evidence and re-run the canonical workflow.

    Only refreshable uncertainty (UNKNOWN, missing, stale, incomplete,
    unavailable evidence) is re-observed. Definitive mismatches are never
    retried into a different interpretation, and an exhausted budget leaves
    the last unresolved result non-definitive.
    """

    def __init__(
        self,
        *,
        workflow: OrderStateReconciliationWorkflow | None = None,
        refresh_policy: RefreshPolicy | None = None,
        evidence_policy: DefinitiveEvidencePolicy | None = None,
    ) -> None:
        self._workflow = workflow or OrderStateReconciliationWorkflow()
        self._refresh = refresh_policy or RefreshPolicy()
        self._evidence = evidence_policy or DefinitiveEvidencePolicy.all_required()

    def refresh(
        self,
        receipt: ExecutionReceipt,
        *,
        local_order: OrderObservation | None,
        broker_order: OrderObservation | None,
        local_position: PositionState | None = None,
        broker_position: PositionState | None = None,
        local_account: AccountFinancialState | None = None,
        broker_account: AccountFinancialState | None = None,
        checked_at: datetime,
        position_policy: ReconciliationPolicy | None = None,
        instrument_id: str | None = None,
        provider: ReconciliationEvidenceProvider,
        pending_age: timedelta | None = None,
        secondary_absence_confirmed: bool | None = None,
        not_found_policy: NotFoundResolutionPolicy | None = None,
    ) -> EvidenceRefreshOutcome:
        """Refresh evidence; optionally surface NOT_FOUND policy eligibility.

        ``pending_age`` is the age of the pending reservation and
        ``secondary_absence_confirmed`` reports an adapter-level secondary
        absence check (``None`` when the adapter exposes none). Both feed
        only the informational ``not_found_eligibility`` verdict; they never
        resolve anything.
        """
        policy = position_policy or ReconciliationPolicy(timedelta(seconds=30))
        refreshed: list[str] = []
        absence_notes: list[str] = []
        attempts = 0
        current_broker_order = broker_order
        current_broker_position = broker_position
        current_broker_account = broker_account

        def absence_eligibility() -> NotFoundResolution | None:
            if not absence_notes:
                return None
            return evaluate_not_found_resolution(
                evidence_status=BrokerOrderEvidenceStatus.NOT_FOUND,
                pending_age=pending_age or timedelta(0),
                secondary_absence_confirmed=secondary_absence_confirmed,
                policy=not_found_policy,
            )

        while True:
            result = self._workflow.reconcile(
                receipt,
                local_order=local_order,
                broker_order=current_broker_order,
                local_position=local_position,
                broker_position=current_broker_position,
                local_account=local_account,
                broker_account=current_broker_account,
                checked_at=checked_at,
                position_policy=policy,
                require_order_scope=self._evidence.require_order_scope,
            )
            if self._is_definitive(result):
                return EvidenceRefreshOutcome(
                    result,
                    attempts,
                    tuple(refreshed),
                    True,
                    (),
                    current_broker_order,
                    current_broker_position,
                    current_broker_account,
                )
            if self._is_definitive_mismatch(result):
                return EvidenceRefreshOutcome(
                    result,
                    attempts,
                    tuple(refreshed),
                    False,
                    ("definitive mismatch; evidence not refreshed",),
                    current_broker_order,
                    current_broker_position,
                    current_broker_account,
                    absence_eligibility(),
                )
            if attempts >= self._refresh.max_attempts:
                return EvidenceRefreshOutcome(
                    result,
                    attempts,
                    tuple(refreshed),
                    False,
                    (
                        "refresh budget exhausted; last unresolved evidence preserved",
                        *absence_notes,
                    ),
                    current_broker_order,
                    current_broker_position,
                    current_broker_account,
                    absence_eligibility(),
                )
            targets = self._refresh_targets(result)
            if not targets:
                return EvidenceRefreshOutcome(
                    result,
                    attempts,
                    tuple(refreshed),
                    False,
                    ("no refreshable evidence",),
                    current_broker_order,
                    current_broker_position,
                    current_broker_account,
                    absence_eligibility(),
                )
            for domain in targets:
                fetched_any = False
                if domain == "order":
                    fetched = provider.fetch_broker_order(
                        account_id=receipt.account_id,
                        connection_id=receipt.connection_id,
                        order_id=result.order_id,
                    )
                    fetched_any = True
                    if fetched.status is BrokerOrderEvidenceStatus.FOUND:
                        assert fetched.observation is not None
                        current_broker_order = fetched.observation
                    elif fetched.status is BrokerOrderEvidenceStatus.NOT_FOUND:
                        if "broker reports order absent" not in absence_notes:
                            absence_notes.append("broker reports order absent")
                elif domain == "position":
                    instrument_id_for_refresh = self._position_instrument(
                        instrument_id,
                        local_position,
                        current_broker_position,
                        receipt,
                    )
                    if instrument_id_for_refresh is not None:
                        fetched_position = provider.fetch_broker_position(
                            account_id=receipt.account_id,
                            connection_id=receipt.connection_id,
                            instrument_id=instrument_id_for_refresh,
                        )
                        fetched_any = True
                        if fetched_position is not None:
                            current_broker_position = fetched_position
                elif domain == "account":
                    fetched_account = provider.fetch_broker_account(
                        account_id=receipt.account_id,
                        connection_id=receipt.connection_id,
                    )
                    fetched_any = True
                    if fetched_account is not None:
                        current_broker_account = fetched_account
                if fetched_any and domain not in refreshed:
                    refreshed.append(domain)
            attempts += 1

    def _is_definitive(self, result: OrderStateReconciliationResult) -> bool:
        if result.status is OrderWorkflowStatus.MATCHED:
            if self._evidence.require_position and (
                result.position is None or result.position.status.value != "MATCHED"
            ):
                return False
            if self._evidence.require_account and not self._account_satisfies(result):
                return False
            return True
        # With advisory account amounts, a MISMATCH aggregate caused solely by
        # balance deltas (order and position matched, no identity failure)
        # still permits a definitive outcome. Identity failures always block.
        if result.status is not OrderWorkflowStatus.MISMATCH:
            return False
        if not self._evidence.advisory_account_amounts:
            return False
        if result.identity_error is not None:
            return False
        if result.order is None or result.order.status is not OrderReconciliationStatus.MATCHED:
            return False
        if self._evidence.require_position and (
            result.position is None or result.position.status.value != "MATCHED"
        ):
            return False
        return self._account_satisfies(result)

    def _account_satisfies(self, result: OrderStateReconciliationResult) -> bool:
        """Decide whether account evidence permits a definitive outcome.

        Exact MATCHED always satisfies. Otherwise only pure balance deltas
        are advisory, and only when the policy opts in: every finding must
        concern a both-sides-present amount field. Identity, availability,
        currency, and staleness findings always block.
        """
        account = result.account
        if account is None:
            return False
        if account.status.value == "MATCHED":
            return True
        if not self._evidence.advisory_account_amounts:
            return False
        if not account.findings:
            return False
        return all(
            finding.field in _ADVISORY_ACCOUNT_AMOUNT_FIELDS
            and finding.observed is not None
            for finding in account.findings
        )

    @staticmethod
    def _is_definitive_mismatch(result: OrderStateReconciliationResult) -> bool:
        return result.status is OrderWorkflowStatus.MISMATCH

    def _refresh_targets(self, result: OrderStateReconciliationResult) -> tuple[str, ...]:
        targets: list[str] = []
        if result.order is not None and result.order.status.value != "MATCHED":
            targets.append("order")
        if self._evidence.require_position and (
            result.position is None or result.position.status.value != "MATCHED"
        ):
            targets.append("position")
        if self._evidence.require_account and (
            result.account is None or result.account.status.value != "MATCHED"
        ):
            targets.append("account")
        return tuple(targets)

    @staticmethod
    def _position_instrument(
        explicit_instrument_id: str | None,
        local_position: PositionState | None,
        broker_position: PositionState | None,
        receipt: ExecutionReceipt,
    ) -> str | None:
        if explicit_instrument_id is not None and explicit_instrument_id.strip():
            return explicit_instrument_id
        if local_position is not None:
            return local_position.instrument_id
        if broker_position is not None:
            return broker_position.instrument_id
        instruments = {str(fill.instrument) for fill in receipt.fills}
        if len(instruments) == 1:
            return next(iter(instruments))
        return None
