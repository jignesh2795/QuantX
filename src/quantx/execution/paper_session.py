"""End-to-end paper execution session orchestration.

Connects approved execution, fill accounting, and explicit mark-to-market
valuation without inventing balances or instrument metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantx.domain.deployment import ExecutionMode
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instruments import Instrument
from quantx.domain.money import Money
from quantx.domain.positions import Position
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.paper import PaperExecutionEngine, QuoteSnapshot
from quantx.execution.portfolio_valuation import PortfolioValuationResult, PortfolioValuator
from quantx.execution.valuation import Mark


@dataclass(frozen=True, slots=True)
class PaperSessionResult:
    execution: object
    accounting_entry: PositionLedgerEntry
    valuation: PortfolioValuationResult


class PaperSession:
    """Run a paper execution through accounting and portfolio valuation."""

    def __init__(
        self,
        *,
        executor: PaperExecutionEngine,
        accounting: FillAccounting | None = None,
        valuator: PortfolioValuator | None = None,
    ) -> None:
        self._executor = executor
        self._accounting = accounting or FillAccounting()
        self._valuator = valuator or PortfolioValuator()

    def execute_and_value(
        self,
        request: ApprovedExecutionRequest,
        *,
        instrument: Instrument,
        quote: QuoteSnapshot,
        cash: Money,
        margin_used: Money,
        valuation_price: Decimal | None = None,
        realized_pnl_before: Decimal = Decimal("0"),
        fee: Decimal = Decimal("0"),
    ) -> PaperSessionResult:
        mode = request.execution_context.execution_mode
        if mode not in {ExecutionMode.PAPER, ExecutionMode.SHADOW, ExecutionMode.REPLAY}:
            raise ValueError("PaperSession requires PAPER, SHADOW, or REPLAY execution mode")
        if instrument.instrument_id != request.order.instrument:
            raise ValueError("instrument metadata does not match order instrument")
        if cash.currency != instrument.currency:
            raise ValueError("cash currency must match instrument currency until FX valuation is supplied")

        receipt = self._executor.execute(request, quote=quote)
        if not receipt.fills:
            raise ValueError("execution produced no fill")

        last_entry: PositionLedgerEntry | None = None
        per_fill_fee = fee / Decimal(len(receipt.fills))
        for fill in receipt.fills:
            last_entry = self._accounting.apply(fill, fee=per_fill_fee)

        assert last_entry is not None
        mark_price = valuation_price
        mark_source = "explicit-valuation-price"
        if mark_price is None:
            mark_price = quote.last
            mark_source = "observed-last"
        if mark_price is None and quote.bid is not None and quote.ask is not None:
            mark_price = (quote.bid + quote.ask) / Decimal("2")
            mark_source = "derived-quote-mid"

        marks: tuple[Mark, ...]
        if mark_price is None:
            marks = ()
        else:
            marks = (
                Mark(
                    instrument_id=str(last_entry.instrument),
                    price=mark_price,
                    source=mark_source,
                ),
            )

        position = Position(
            instrument=instrument,
            quantity=last_entry.quantity,
            average_price=last_entry.average_price,
            realized_pnl=last_entry.realized_pnl,
        )
        valuation = self._valuator.value(
            portfolio_id=request.execution_context.portfolio_id,
            valuation_currency=cash.currency,
            cash=cash,
            margin_used=margin_used,
            positions=(position,),
            marks=marks,
            realized_pnl=realized_pnl_before + last_entry.realized_pnl - last_entry.fees,
        )
        return PaperSessionResult(receipt, last_entry, valuation)
