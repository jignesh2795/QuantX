"""End-to-end paper execution session orchestration.

Connects approved execution, fill accounting, and explicit mark-to-market
valuation without inventing balances or market data.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantx.domain.deployment import ExecutionMode
from quantx.domain.execution_request import ApprovedExecutionRequest
from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.positions import Position
from quantx.domain.value_objects import Money
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.paper import PaperExecutionEngine
from quantx.execution.portfolio_valuation import PortfolioValuationResult, PortfolioValuator
from quantx.execution.valuation import Mark

from .market_data import MarketSnapshot


@dataclass(frozen=True, slots=True)
class PaperSessionResult:
    execution: object
    accounting_entry: PositionLedgerEntry
    valuation: PortfolioValuationResult


class PaperSession:
    """Run paper/replay/shadow execution through accounting and valuation."""

    def __init__(
        self,
        *,
        executor: PaperExecutionEngine,
        instrument_registry: InstrumentRegistry,
        accounting: FillAccounting | None = None,
        valuator: PortfolioValuator | None = None,
    ) -> None:
        self._executor = executor
        self._instrument_registry = instrument_registry
        self._accounting = accounting or FillAccounting()
        self._valuator = valuator or PortfolioValuator()

    def execute_and_value(
        self,
        request: ApprovedExecutionRequest,
        *,
        snapshot: MarketSnapshot,
        cash: Money,
        margin_used: Money,
        valuation_price: Decimal | None = None,
        realized_pnl_before: Decimal = Decimal("0"),
        fee: Decimal = Decimal("0"),
    ) -> PaperSessionResult:
        mode = request.execution_context.execution_mode
        if mode not in {ExecutionMode.PAPER, ExecutionMode.SHADOW, ExecutionMode.REPLAY}:
            raise ValueError("PaperSession requires PAPER, SHADOW, or REPLAY execution mode")
        if fee < 0:
            raise ValueError("fee cannot be negative")

        instrument = self._instrument_registry.resolve(snapshot.instrument)
        if instrument is None:
            raise ValueError(f"instrument metadata unavailable for {snapshot.instrument}")
        if instrument.instrument_id != request.order.instrument:
            raise ValueError("resolved instrument does not match the execution request")
        if instrument.market != request.execution_context.market:
            raise ValueError("resolved instrument market does not match the execution request")

        receipt = self._executor.execute(request, snapshot=snapshot)
        if not receipt.fills:
            raise ValueError("execution produced no fill")

        last_entry: PositionLedgerEntry | None = None
        per_fill_fee = fee / Decimal(len(receipt.fills))
        for fill in receipt.fills:
            last_entry = self._accounting.apply(fill, fee=per_fill_fee)

        assert last_entry is not None
        mark_price = valuation_price if valuation_price is not None else snapshot.last
        if mark_price is None and snapshot.bid is not None and snapshot.ask is not None:
            mark_price = (snapshot.bid + snapshot.ask) / Decimal("2")

        marks: tuple[Mark, ...] = () if mark_price is None else (
            Mark(
                instrument_id=str(last_entry.instrument),
                price=mark_price,
                source="paper-session-market-snapshot",
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
