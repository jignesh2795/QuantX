"""End-to-end paper execution session orchestration.

Connects approved execution, fill accounting, explicit cash accounting, and
mark-to-market valuation without inventing balances or market data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from decimal import Decimal
from uuid import uuid4

from quantx.domain.deployment import ExecutionMode
from quantx.domain.finance import CapitalSourceType
from quantx.domain.enums import OrderSide
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.orders import Fill
from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.positions import Position
from quantx.domain.value_objects import Money
from quantx.execution.account_financial_state import AccountFinancialSnapshot, AccountFinancialStateBuilder
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.cash_ledger import CashLedger, CashLedgerEntry
from quantx.execution.margin_ledger import MarginLedger, MarginReservation, MarginState
from quantx.execution.margin_policy import PositionMarginPolicy
from quantx.execution.paper_engine import PaperExecutionEngine
from quantx.execution.receipts.lifecycle import ExecutionLifecycle
from quantx.domain.risk import RiskResult
from quantx.execution.portfolio_valuation import PortfolioValuationResult, PortfolioValuator
from quantx.execution.post_trade_enforcement import PostTradeRiskEnforcer, RiskEnforcementResult
from quantx.execution.valuation import Mark

from .market_data import MarketSnapshot


class _ExecutionAdapter(Protocol):
    def execute(self, request: ApprovedExecutionRequest, *, snapshot: MarketSnapshot):
        ...


class _PartialContinuationAdapter:
    def __init__(
        self,
        executor: PaperExecutionEngine,
        lifecycle: ExecutionLifecycle,
        risk_result: RiskResult,
        requested_quantity: Decimal | None,
    ) -> None:
        self._executor = executor
        self._lifecycle = lifecycle
        self._risk_result = risk_result
        self._requested_quantity = requested_quantity

    def execute(self, request: ApprovedExecutionRequest, *, snapshot: MarketSnapshot):
        return self._executor.execute(request, snapshot=snapshot)


@dataclass(frozen=True, slots=True)
class PaperSessionResult:
    execution: object
    accounting_entry: PositionLedgerEntry
    valuation: PortfolioValuationResult
    cash: Money
    cash_entries: tuple[CashLedgerEntry, ...] = ()
    financial_state: AccountFinancialSnapshot | None = None
    risk_enforcement: RiskEnforcementResult | None = None
    margin_reservation: MarginReservation | None = None

    @property
    def margin_used(self) -> Money:
        """Expose the effective margin used by this session result."""
        return self.valuation.snapshot.margin_used


class PaperSession:
    """Run paper/replay/shadow execution through trading-state accounting.

    initial_cash or cash_ledger turns the session into a stateful paper
    account. The legacy cash argument remains supported for one-shot
    valuation when no ledger is configured.
    """

    def __init__(
        self,
        *,
        executor: PaperExecutionEngine,
        instrument_registry: InstrumentRegistry,
        accounting: FillAccounting | None = None,
        valuator: PortfolioValuator | None = None,
        initial_cash: Money | None = None,
        cash_ledger: CashLedger | None = None,
        post_trade_risk: PostTradeRiskEnforcer | None = None,
        margin_ledger: MarginLedger | None = None,
        position_margin_policy: PositionMarginPolicy | None = None,
    ) -> None:
        if initial_cash is not None and cash_ledger is not None:
            raise ValueError("provide either initial_cash or cash_ledger, not both")
        self._executor = executor
        self._instrument_registry = instrument_registry
        self._accounting = accounting or FillAccounting()
        self._valuator = valuator or PortfolioValuator()
        self._cash_ledger = cash_ledger or (
            CashLedger(initial_cash) if initial_cash is not None else None
        )
        self._post_trade_risk = post_trade_risk
        self._margin_ledger = margin_ledger
        self._position_margin_policy = position_margin_policy
        self._market_snapshots: dict[object, MarketSnapshot] = {}

    @property
    def margin_state(self) -> MarginState | None:
        return None if self._margin_ledger is None else self._margin_ledger.state

    def release_margin(self, reservation_id, amount: Decimal | None = None) -> MarginReservation:
        if self._margin_ledger is None:
            raise ValueError("no margin ledger is configured")
        return self._margin_ledger.release(reservation_id, amount)

    def execute_and_value(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot,
        cash: Money | None = None,
        margin_used: Money | None = None,
        valuation_price: Decimal | None = None,
        realized_pnl_before: Decimal = Decimal("0"),
        fee: Decimal | None = None,
        daily_pnl_before: Decimal = Decimal("0"),
        margin_available: Money | None = None,
        capital_source: CapitalSourceType = CapitalSourceType.PAPER_CONFIGURED,
        execution_adapter: _ExecutionAdapter | None = None,
    ) -> PaperSessionResult:
        mode = request.execution_context.execution_mode
        if mode not in {ExecutionMode.PAPER, ExecutionMode.SHADOW, ExecutionMode.REPLAY}:
            raise ValueError("PaperSession requires PAPER, SHADOW, or REPLAY execution mode")

        instrument = self._instrument_registry.resolve(snapshot.instrument)
        if instrument is None:
            raise ValueError(f"instrument metadata unavailable for {snapshot.instrument}")
        self._market_snapshots[snapshot.instrument] = snapshot
        if instrument.instrument_id != request.order.instrument:
            raise ValueError("resolved instrument does not match the execution request")
        if instrument.market != request.execution_context.market:
            raise ValueError("resolved instrument market does not match the execution request")

        if self._cash_ledger is None and cash is None:
            raise ValueError("cash is required when no cash ledger is configured")
        margin_reservation = None
        required_margin = request.required_margin
        if self._margin_ledger is not None and self._position_margin_policy is not None:
            reference_price = request.order.limit_price or request.order.stop_price
            if reference_price is None:
                if request.order.side is OrderSide.BUY:
                    reference_price = snapshot.ask or snapshot.last
                else:
                    reference_price = snapshot.bid or snapshot.last
            if reference_price is None:
                raise ValueError(
                    "position margin policy requires a reference price before execution"
                )
            if reference_price <= 0:
                raise ValueError("position margin reference price must be positive")
            projected_fill = Fill(
                client_order_id=request.order.client_order_id,
                instrument=instrument.instrument_id,
                side=request.order.side,
                quantity=request.order.quantity,
                price=reference_price,
                filled_at=snapshot.timestamp,
                execution_id=uuid4(),
            )
            projected_position = self._accounting.project(projected_fill)
            policy_margin = self._position_margin_policy.required_margin(projected_position)
            if policy_margin < 0:
                raise ValueError("position margin requirement cannot be negative")
            required_margin = max(required_margin, policy_margin)

        if self._margin_ledger is not None and required_margin > 0:
            existing = self._margin_ledger.reservation(request.order.client_order_id)
            if existing is not None:
                margin_reservation = self._margin_ledger.set_required_amount(
                    request.order.client_order_id,
                    required_margin,
                )
            else:
                if self._position_margin_policy is not None:
                    try:
                        updated = self._margin_ledger.set_required_amount_for_instrument(
                            instrument.instrument_id,
                            required_margin,
                        )
                    except KeyError:
                        updated = ()
                    if updated:
                        margin_reservation = updated[0]
                if margin_reservation is None:
                    margin_reservation = self._margin_ledger.reserve(
                        request.order.client_order_id,
                        required_margin,
                        instrument=instrument.instrument_id,
                        quantity=request.order.quantity,
                    )

        if self._margin_ledger is not None:
            ledger_state = self._margin_ledger.state
            margin_currency = (
                cash.currency
                if cash is not None
                else self._cash_ledger.balance.currency
                if self._cash_ledger is not None
                else None
            )
            if margin_currency is None:
                raise ValueError("cash is required when a margin ledger is configured")
            margin_used = Money(ledger_state.used, margin_currency)
            margin_available = Money(ledger_state.available, margin_currency)
        elif margin_used is None:
            margin_used = Money.zero(
                cash.currency if cash is not None else self._cash_ledger.balance.currency
            )

        try:
            adapter = execution_adapter or self._executor
            receipt = adapter.execute(request, snapshot=snapshot)
        except Exception:
            if margin_reservation is not None:
                self._margin_ledger.release(margin_reservation.reservation_id)
            raise
        if not receipt.fills:
            if margin_reservation is not None:
                self._margin_ledger.release(margin_reservation.reservation_id)
            raise ValueError("execution produced no fill")

        applied_fee = receipt.fee if fee is None else fee
        if applied_fee < 0:
            raise ValueError("fee cannot be negative")

        last_entry: PositionLedgerEntry | None = None
        cash_entries: list[CashLedgerEntry] = []
        per_fill_fee = applied_fee / Decimal(len(receipt.fills))
        for fill in receipt.fills:
            last_entry = self._accounting.apply(fill, fee=per_fill_fee)
            if self._cash_ledger is not None:
                cash_entries.append(
                    self._cash_ledger.apply(
                        fill,
                        fee=per_fill_fee,
                        multiplier=instrument.multiplier,
                    )
                )

        assert last_entry is not None
        if self._margin_ledger is not None and self._position_margin_policy is not None:
            required = self._position_margin_policy.required_margin(last_entry)
            if required < 0:
                raise ValueError("position margin requirement cannot be negative")
            target_required = max(
                required,
                request.required_margin,
            )
            linked = self._margin_ledger.reservation(request.order.client_order_id)
            if linked is not None:
                margin_reservation = self._margin_ledger.set_required_amount(
                    request.order.client_order_id,
                    target_required,
                )
            elif target_required > 0:
                updated = self._margin_ledger.set_required_amount_for_instrument(
                    last_entry.instrument,
                    target_required,
                )
                margin_reservation = updated[0] if updated else None
        if self._margin_ledger is not None and last_entry.quantity == 0:
            self._margin_ledger.release_for_flat_position(last_entry.instrument)
            margin_reservation = self._margin_ledger.reservation(request.order.client_order_id)

        # Refresh after post-fill margin resizing/release so valuation sees final state.
        if self._margin_ledger is not None:
            ledger_state = self._margin_ledger.state
            margin_currency = (
                cash.currency
                if cash is not None
                else self._cash_ledger.balance.currency
                if self._cash_ledger is not None
                else None
            )
            if margin_currency is None:
                raise ValueError("cash is required when a margin ledger is configured")
            margin_used = Money(ledger_state.used, margin_currency)
            margin_available = Money(ledger_state.available, margin_currency)

        account_cash = (
            self._cash_ledger.balance
            if self._cash_ledger is not None
            else cash
        )
        assert account_cash is not None
        if cash is not None and cash.currency != account_cash.currency:
            raise ValueError("cash currency does not match the paper account")

        positions: list[Position] = []
        marks: list[Mark] = []
        entries = self._accounting.snapshot()
        for entry in entries:
            entry_instrument = self._instrument_registry.resolve(entry.instrument)
            if entry_instrument is None:
                raise ValueError(f"instrument metadata unavailable for {entry.instrument}")
            position = Position(
                instrument=entry_instrument,
                quantity=entry.quantity,
                average_price=entry.average_price,
                realized_pnl=entry.realized_pnl,
            )
            positions.append(position)
            entry_snapshot = self._market_snapshots.get(entry.instrument)
            if entry.instrument == snapshot.instrument and valuation_price is not None:
                mark_price = valuation_price
            elif entry_snapshot is not None:
                mark_price = entry_snapshot.last
                if mark_price is None and entry_snapshot.bid is not None and entry_snapshot.ask is not None:
                    mark_price = (entry_snapshot.bid + entry_snapshot.ask) / Decimal("2")
            else:
                mark_price = None
            if mark_price is not None and not position.is_flat:
                marks.append(
                    Mark(
                        instrument_id=str(entry.instrument),
                        price=mark_price,
                        source="paper-session-market-snapshot",
                    )
                )

        realized_total = (
            realized_pnl_before
            + sum(entry.realized_pnl for entry in entries)
            - sum(entry.fees for entry in entries)
        )
        valuation = self._valuator.value(
            portfolio_id=request.execution_context.portfolio_id,
            valuation_currency=account_cash.currency,
            cash=account_cash,
            margin_used=margin_used,
            positions=tuple(positions),
            marks=tuple(marks),
            realized_pnl=realized_total,
        )

        margin_available_money = (
            margin_available
            if margin_available is not None
            else Money.zero(account_cash.currency)
        )
        gross_exposure = Money(
            sum(abs(result.market_value) for result in valuation.valuations),
            account_cash.currency,
        )
        financial_state = AccountFinancialStateBuilder().from_cash_and_margin(
            capital_source=capital_source,
            cash_balance=account_cash,
            margin_used=margin_used,
            margin_available=margin_available_money,
            daily_pnl=Money(
                daily_pnl_before
                + sum(entry.realized_pnl for entry in entries)
                - sum(entry.fees for entry in entries)
                + valuation.snapshot.unrealized_pnl.amount,
                account_cash.currency,
            ),
            realized_pnl=valuation.snapshot.realized_pnl,
            unrealized_pnl=valuation.snapshot.unrealized_pnl,
            gross_exposure=gross_exposure,
            position_exposures=tuple(
                Money(abs(result.market_value), account_cash.currency)
                for result in valuation.valuations
            ),
        )
        risk_enforcement = (
            self._post_trade_risk.evaluate_snapshot(financial_state)
            if self._post_trade_risk is not None
            else None
        )
        return PaperSessionResult(
            receipt,
            last_entry,
            valuation,
            account_cash,
            tuple(cash_entries),
            financial_state,
            risk_enforcement,
            margin_reservation,
        )

    def _check_continuation_projection(
        self,
        continuation: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot,
        margin_used: Money | None,
        margin_available: Money | None,
    ) -> None:
        if self._post_trade_risk is None:
            return
        instrument = self._instrument_registry.resolve(snapshot.instrument)
        if instrument is None:
            raise ValueError("instrument metadata unavailable for projected continuation")
        reference_price = continuation.order.limit_price or continuation.order.stop_price
        if reference_price is None:
            reference_price = (
                snapshot.ask or snapshot.last
                if continuation.order.side is OrderSide.BUY
                else snapshot.bid or snapshot.last
            )
        if reference_price is None or reference_price <= 0:
            raise ValueError("projected continuation requires a positive reference price")
        projected_fill = Fill(
            client_order_id=continuation.order.client_order_id,
            instrument=instrument.instrument_id,
            side=continuation.order.side,
            quantity=continuation.order.quantity,
            price=reference_price,
            filled_at=snapshot.timestamp,
            execution_id=uuid4(),
        )
        projected_position = self._accounting.project(projected_fill)
        entries = [
            projected_position if entry.instrument == instrument.instrument_id else entry
            for entry in self._accounting.snapshot()
        ]
        if not any(entry.instrument == instrument.instrument_id for entry in entries):
            entries.append(projected_position)
        exposures: list[Money] = []
        for entry in entries:
            if entry.quantity == 0:
                continue
            if entry.instrument == instrument.instrument_id:
                mark = reference_price
                multiplier = instrument.multiplier
            else:
                stored = self._market_snapshots.get(entry.instrument)
                if stored is None:
                    raise ValueError("projected continuation requires marks for open positions")
                mark = stored.last
                if mark is None and stored.bid is not None and stored.ask is not None:
                    mark = (stored.bid + stored.ask) / Decimal("2")
                if mark is None:
                    raise ValueError("projected continuation requires marks for open positions")
                entry_instrument = self._instrument_registry.resolve(entry.instrument)
                if entry_instrument is None:
                    raise ValueError("instrument metadata unavailable for projected continuation")
                multiplier = entry_instrument.multiplier
            exposures.append(
                Money(abs(entry.quantity) * mark * multiplier, instrument.currency)
            )
        if self._margin_ledger is not None:
            state = self._margin_ledger.state
            existing = sum(
                reservation.outstanding
                for reservation in self._margin_ledger.reservations
                if reservation.instrument == instrument.instrument_id
            )
            policy_amount = (
                self._position_margin_policy.required_margin(projected_position)
                if self._position_margin_policy is not None
                else Decimal("0")
            )
            target = max(continuation.required_margin, policy_amount)
            projected_used = state.used - existing + target
            capacity = state.used + state.available
            projected_margin_used = Money(projected_used, instrument.currency)
            projected_margin_available = Money(
                max(Decimal("0"), capacity - projected_used),
                instrument.currency,
            )
        else:
            projected_margin_used = margin_used or Money.zero(instrument.currency)
            projected_margin_available = margin_available or Money.zero(instrument.currency)
        result = self._post_trade_risk.evaluate_projected_limits(
            margin_used=projected_margin_used,
            margin_available=projected_margin_available,
            gross_exposure=Money(sum(x.amount for x in exposures), instrument.currency),
            position_exposures=tuple(exposures),
        )
        if not result.allowed:
            raise ValueError("projected account constraint: " + "; ".join(result.reasons))

    def continue_partial(
        self,
        request: ApprovedExecutionRequest,
        lifecycle: ExecutionLifecycle,
        *,
        risk_result: RiskResult,
        snapshot: MarketSnapshot,
        requested_quantity: Decimal | None = None,
        cash: Money | None = None,
        margin_used: Money | None = None,
        valuation_price: Decimal | None = None,
        realized_pnl_before: Decimal = Decimal("0"),
        fee: Decimal | None = None,
        daily_pnl_before: Decimal = Decimal("0"),
        margin_available: Money | None = None,
        capital_source: CapitalSourceType = CapitalSourceType.PAPER_CONFIGURED,
    ) -> PaperSessionResult:
        """Continue a partial execution through the full account pipeline."""
        authoritative_lifecycle = self._executor.rebuild_lifecycle(request, lifecycle)
        continuation = authoritative_lifecycle.continuation_request(
            request,
            risk_result=risk_result,
            requested_quantity=requested_quantity,
        )
        self._check_continuation_projection(
            continuation,
            snapshot=snapshot,
            margin_used=margin_used,
            margin_available=margin_available,
        )
        adapter = _PartialContinuationAdapter(
            self._executor,
            authoritative_lifecycle,
            risk_result,
            requested_quantity,
        )
        return self.execute_and_value(
            continuation,
            snapshot=snapshot,
            cash=cash,
            margin_used=margin_used,
            valuation_price=valuation_price,
            realized_pnl_before=realized_pnl_before,
            fee=fee,
            daily_pnl_before=daily_pnl_before,
            margin_available=margin_available,
            capital_source=capital_source,
            execution_adapter=adapter,
        )

