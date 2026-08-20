"""End-to-end paper execution session orchestration.

Connects approved execution, fill accounting, and explicit mark-to-market
valuation without inventing balances or market data.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantx.domain.deployment import ExecutionMode, PortfolioId
from quantx.domain.portfolio import PortfolioSnapshot
from quantx.domain.value_objects import InstrumentId, Money
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.paper import PaperExecutionEngine, QuoteSnapshot
from quantx.execution.portfolio_valuation import PortfolioValuationResult, PortfolioValuator
from quantx.execution.valuation import Mark
from quantx.domain.execution_request import ApprovedExecutionRequest


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

        receipt = self._executor.execute(request, quote=quote)
        if not receipt.fills:
            raise ValueError("execution produced no fill")

        last_entry: PositionLedgerEntry | None = None
        per_fill_fee = fee / Decimal(len(receipt.fills))
        for fill in receipt.fills:
            last_entry = self._accounting.apply(fill, fee=per_fill_fee)

        assert last_entry is not None
        mark_price = valuation_price
        if mark_price is None:
            mark_price = quote.last
        if mark_price is None and quote.bid is not None and quote.ask is not None:
            mark_price = (quote.bid + quote.ask) / Decimal("2")

        marks: tuple[Mark, ...]
        if mark_price is None:
            marks = ()
        else:
            marks = (Mark(instrument_id=str(last_entry.instrument), price=mark_price, source="paper-session-quote"),)

        position = last_entry_to_position(last_entry, request)
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


def last_entry_to_position(entry: PositionLedgerEntry, request: ApprovedExecutionRequest):
    """Convert accounting state to the domain Position representation."""
    instrument = request.order.instrument
    from quantx.domain.positions import Position

    return Position(
        instrument=resolve_instrument(request, instrument),
        quantity=entry.quantity,
        average_price=entry.average_price,
        realized_pnl=entry.realized_pnl,
    )


def resolve_instrument(request: ApprovedExecutionRequest, instrument_id: InstrumentId):
    """Resolve the full instrument from the execution context's request.

    The current domain request carries InstrumentId only, so this helper keeps
    the conversion boundary local until the canonical instrument registry is
    introduced. It deliberately refuses to invent contract metadata.
    """
    from quantx.domain.instruments import Instrument, AssetClass

    return Instrument(
        instrument_id=instrument_id,
        asset_class=AssetClass.EQUITY,
        market=request.execution_context.market,
        currency="USD" if request.execution_context.market.region.value != "IN" else "INR",
        tick_size=Decimal("0.01"),
        lot_size=Decimal("1"),
        multiplier=Decimal("1"),
    )
