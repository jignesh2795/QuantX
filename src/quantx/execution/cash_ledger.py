"""Deterministic cash accounting for paper and replay execution.

The ledger records the actual cash effect of fills separately from position
accounting. Trade P&L remains a position/accounting concern; this component
only answers how fills and fees change cash.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from quantx.domain.enums import OrderSide
from quantx.domain.orders import Fill
from quantx.domain.value_objects import InstrumentId, Money


@dataclass(frozen=True, slots=True)
class CashLedgerEntry:
    execution_id: UUID
    instrument: InstrumentId
    side: OrderSide
    quantity: Decimal
    price: Decimal
    notional: Money
    trade_cash_flow: Money
    fee: Money
    net_cash_flow: Money
    cash_after: Money


class CashLedger:
    """Stateful cash ledger for one paper/backtest account.

    BUY fills consume cash and SELL fills provide cash. Fees always consume
    cash. Short-sale proceeds therefore increase cash, while margin policy is
    intentionally enforced by a separate risk/margin layer.
    """

    def __init__(self, initial_cash: Money) -> None:
        if initial_cash.amount < 0:
            raise ValueError("initial cash cannot be negative")
        self._balance = initial_cash
        self._entries: list[CashLedgerEntry] = []

    @property
    def balance(self) -> Money:
        return self._balance

    def apply(
        self,
        fill: Fill,
        *,
        fee: Decimal = Decimal("0"),
        multiplier: Decimal = Decimal("1"),
    ) -> CashLedgerEntry:
        if fee < 0:
            raise ValueError("fee cannot be negative")
        if multiplier <= 0:
            raise ValueError("multiplier must be positive")

        notional_amount = fill.quantity * fill.price * multiplier
        notional = Money(notional_amount, self._balance.currency)
        trade_amount = -notional_amount if fill.side is OrderSide.BUY else notional_amount
        trade_cash_flow = Money(trade_amount, self._balance.currency)
        fee_money = Money(fee, self._balance.currency)
        net_amount = trade_amount - fee
        cash_after_amount = self._balance.amount + net_amount
        if cash_after_amount < 0:
            raise ValueError("fill would make cash balance negative")

        net_cash_flow = Money(net_amount, self._balance.currency)
        cash_after = Money(cash_after_amount, self._balance.currency)
        entry = CashLedgerEntry(
            execution_id=fill.execution_id,
            instrument=fill.instrument,
            side=fill.side,
            quantity=fill.quantity,
            price=fill.price,
            notional=notional,
            trade_cash_flow=trade_cash_flow,
            fee=fee_money,
            net_cash_flow=net_cash_flow,
            cash_after=cash_after,
        )
        self._balance = cash_after
        self._entries.append(entry)
        return entry

    def entries(self) -> tuple[CashLedgerEntry, ...]:
        return tuple(self._entries)
