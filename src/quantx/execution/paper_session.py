"""End-to-end paper execution session orchestration.

Connects approved execution, fill accounting, explicit cash accounting, and
mark-to-market valuation without inventing balances or market data.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantx.domain.deployment import ExecutionMode
from quantx.domain.finance import CapitalSourceType
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.positions import Position
from quantx.domain.value_objects import Money
from quantx.execution.account_financial_state import AccountFinancialSnapshot, AccountFinancialStateBuilder
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.cash_ledger import CashLedger, CashLedgerEntry
from quantx.execution.margin_ledger import MarginLedger, MarginReservation, MarginState
from quantx.execution.paper_engine import PaperExecutionEngine
from quantx.execution.portfolio_valuation import PortfolioValuationResult, PortfolioValuator
from quantx.execution.post_trade_enforcement import PostTradeRiskEnforcer, RiskEnforcementResult
from quantx.execution.valuation import Mark

from .market_data import MarketSnapshot


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
    ) -> PaperSessionResult:
        mode = request.execution_context.execution_mode
        if mode not in {ExecutionMode.PAPER, ExecutionMode.SHADOW, ExecutionMode.REPLAY}:
            raise ValueError("PaperSession requires PAPER, SHADOW, or REPLAY execution mode")

        instrument = self._instrument_registry.resolve(snapshot.instrument)
        if instrument is None:
            raise ValueError(f"instrument metadata unavailable for {snapshot.instrument}")
        if instrument.instrument_id != request.order.instrument:
            raise ValueError("resolved instrument does not match the execution request")
        if instrument.market != request.execution_context.market:
            raise ValueError("resolved instrument market does not match the execution request")

        if self._cash_ledger is None and cash is None:
            raise ValueError("cash is required when no cash ledger is configured")
        margin_reservation = None
        if self._margin_ledger is not None and request.required_margin > 0:
            existing = self._margin_ledger.reservation(request.order.client_order_id)
            if existing is None:
                margin_reservation = self._margin_ledger.reserve(
                    request.order.client_order_id,
                    request.required_margin,
                )
            elif existing.amount != request.required_margin:
                raise ValueError("existing margin reservation amount does not match request")
            else:
                margin_reservation = existing

        if margin_used is None:
            margin_used = Money.zero(
                cash.currency if cash is not None else self._cash_ledger.balance.currency
            )

        receipt = self._executor.execute(request, snapshot=snapshot)
        if not receipt.fills:
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
        account_cash = (
            self._cash_ledger.balance
            if self._cash_ledger is not None
            else cash
        )
        assert account_cash is not None
        if cash is not None and cash.currency != account_cash.currency:
            raise ValueError("cash currency does not match the paper account")

        mark_price = valuation_price if valuation_price is not None else snapshot.last
        if mark_price is None and snapshot.bid is not None and snapshot.ask is not None:
            mark_price = (snapshot.bid + snapshot.ask) / Decimal("2")

        marks: tuple[Mark, ...] = (
            ()
            if mark_price is None
            else (
                Mark(
                    instrument_id=str(last_entry.instrument),
                    price=mark_price,
                    source="paper-session-market-snapshot",
                ),
            )
        )

        position = Position(
            instrument=instrument,
            quantity=last_entry.quantity,
            average_price=last_entry.average_price,
            realized_pnl=last_entry.realized_pnl,
        )
        realized_total = (
            realized_pnl_before + last_entry.realized_pnl - last_entry.fees
        )
        valuation = self._valuator.value(
            portfolio_id=request.execution_context.portfolio_id,
            valuation_currency=account_cash.currency,
            cash=account_cash,
            margin_used=margin_used,
            positions=(position,),
            marks=marks,
            realized_pnl=realized_total,
        )

        margin_available_money = (
            margin_available
            if margin_available is not None
            else Money.zero(account_cash.currency)
        )
        gross_exposure = Money(
            sum(
                abs(result.market_value.amount)
                for result in valuation.valuations
            ),
            account_cash.currency,
        )
        financial_state = AccountFinancialStateBuilder().from_cash_and_margin(
            capital_source=capital_source,
            cash_balance=account_cash,
            margin_used=margin_used,
            margin_available=margin_available_money,
            daily_pnl=Money(
                daily_pnl_before
                + last_entry.realized_pnl
                - last_entry.fees
                + valuation.snapshot.unrealized_pnl.amount,
                account_cash.currency,
            ),
            realized_pnl=valuation.snapshot.realized_pnl,
            unrealized_pnl=valuation.snapshot.unrealized_pnl,
            gross_exposure=gross_exposure,
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
