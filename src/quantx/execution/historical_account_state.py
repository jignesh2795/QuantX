"""Deterministic account-state evolution for historical replay and backtests.

This boundary derives simulated account state only from explicitly configured
starting capital, simulated execution receipts and fills, modeled fees,
canonical position accounting, and supplied historical market marks. It never
queries a broker or fabricates a valuation when evidence is missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from quantx.domain.finance import AccountFinancialState, CapitalSourceType
from quantx.domain.instrument_registry import InstrumentRegistry
from quantx.domain.market_data import Candle
from quantx.domain.positions import Position
from quantx.domain.value_objects import InstrumentId, Money
from quantx.execution.accounting import FillAccounting, PositionLedgerEntry
from quantx.execution.cash_ledger import CashLedger
from quantx.execution.market_data import MarketSnapshot
from quantx.execution.receipts.models import ExecutionReceipt
from quantx.execution.valuation import Mark, MarkToMarketValuator


class AccountStateCompleteness(StrEnum):
    """Whether the complete account valuation is established by supplied evidence."""

    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


@dataclass(frozen=True, slots=True)
class HistoricalAccountStateSnapshot:
    """One immutable post-event simulated account-state observation.

    Market valuation fields are withheld when any open position lacks an
    explicit mark. This avoids presenting a partially valued portfolio as
    complete.
    """

    timestamp: datetime
    capital_source: CapitalSourceType
    cash: Money | None
    market_value: Money | None
    equity: Money | None
    realized_pnl: Money
    unrealized_pnl: Money | None
    gross_exposure: Money | None
    fees: Money
    positions: tuple[PositionLedgerEntry, ...]
    completeness: AccountStateCompleteness
    unavailable_instruments: tuple[str, ...] = ()
    issue: str | None = None

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        if self.fees.currency != self.realized_pnl.currency:
            raise ValueError("fees must use the realized_pnl currency")

        values = tuple(
            value
            for value in (
                self.cash,
                self.market_value,
                self.equity,
                self.unrealized_pnl,
                self.gross_exposure,
            )
            if value is not None
        )
        if any(value.currency != self.realized_pnl.currency for value in values):
            raise ValueError("all account-state money values must use one currency")

        if self.completeness is AccountStateCompleteness.COMPLETE:
            if (
                self.cash is None
                or self.market_value is None
                or self.equity is None
                or self.unrealized_pnl is None
            ):
                raise ValueError("complete account state requires a complete valuation")
            if self.unavailable_instruments or self.issue is not None:
                raise ValueError("complete account state cannot carry incompleteness evidence")

        if self.completeness is AccountStateCompleteness.INCOMPLETE and not (
            self.unavailable_instruments or self.issue is not None
        ):
            raise ValueError("incomplete account state requires explicit evidence")

    @property
    def net_pnl(self) -> Money | None:
        """Return realized + unrealized P&L less modeled fees when valuation is complete."""

        if self.unrealized_pnl is None:
            return None
        return Money(
            self.realized_pnl.amount + self.unrealized_pnl.amount - self.fees.amount,
            self.realized_pnl.currency,
        )


class HistoricalAccountStateTracker:
    """Derive deterministic account state from explicit simulated evidence."""

    def __init__(
        self,
        starting_financial_state: AccountFinancialState,
        *,
        accounting: FillAccounting,
        instrument_registry: InstrumentRegistry,
    ) -> None:
        if starting_financial_state.capital_source is CapitalSourceType.LIVE_BROKER:
            raise ValueError(
                "historical account-state tracking requires configured "
                "paper/backtest capital"
            )

        self._capital_source = starting_financial_state.capital_source
        self._currency = starting_financial_state.cash_balance.currency
        self._cash = CashLedger(starting_financial_state.cash_balance)
        self._accounting = accounting
        self._instrument_registry = instrument_registry
        self._valuator = MarkToMarketValuator()
        self._marks: dict[InstrumentId, Mark] = {}
        self._fees = Decimal("0")
        self._cash_available = True
        self._issue: str | None = None
        self._snapshots: dict[UUID, HistoricalAccountStateSnapshot] = {}

    def observe_mark(self, snapshot: MarketSnapshot | Candle) -> None:
        """Store an explicit mark from the supplied historical observation."""

        if isinstance(snapshot, Candle):
            price = snapshot.close
            source = "historical-replay-candle-close"
        elif isinstance(snapshot, MarketSnapshot):
            if snapshot.last is not None:
                price = snapshot.last
                source = "historical-replay-last"
            elif snapshot.bid is not None and snapshot.ask is not None:
                price = (snapshot.bid + snapshot.ask) / Decimal("2")
                source = "historical-replay-mid"
            else:
                price = None
                source = "historical-replay-no-price"
        else:
            raise TypeError(
                f"unsupported historical snapshot type: {type(snapshot).__name__}"
            )

        self._marks[snapshot.instrument] = Mark(
            instrument_id=str(snapshot.instrument),
            price=price,
            source=source,
            observed_at=snapshot.timestamp,
        )

    def record(
        self,
        receipt: ExecutionReceipt,
        *,
        snapshot: MarketSnapshot | Candle,
    ) -> HistoricalAccountStateSnapshot:
        """Apply one receipt and return the resulting immutable account state."""

        existing = self._snapshots.get(receipt.receipt_id)
        if existing is not None:
            return existing

        self.observe_mark(snapshot)
        if receipt.fee < 0:
            raise ValueError("receipt fee cannot be negative")

        per_fill_fee = (
            receipt.fee / Decimal(len(receipt.fills))
            if receipt.fills
            else Decimal("0")
        )

        for fill in receipt.fills:
            self._accounting.apply(fill, fee=per_fill_fee)

        self._fees += receipt.fee

        if receipt.fills and self._cash_available:
            for fill in receipt.fills:
                instrument = self._instrument_registry.resolve(fill.instrument)
                if instrument is None:
                    self._cash_available = False
                    self._issue = (
                        "instrument metadata unavailable for cash accounting: "
                        f"{fill.instrument}"
                    )
                    break
                try:
                    self._cash.apply(
                        fill,
                        fee=per_fill_fee,
                        multiplier=instrument.multiplier,
                    )
                except ValueError as exc:
                    self._cash_available = False
                    self._issue = f"cash accounting unavailable: {exc}"
                    break
        elif receipt.fee != 0:
            self._cash_available = False
            self._issue = (
                "receipt fee cannot be allocated because the receipt has no fills"
            )

        result = self._snapshot(receipt.executed_at)
        self._snapshots[receipt.receipt_id] = result
        return result

    def snapshot_at(
        self,
        timestamp: datetime,
        *,
        require_current_marks: bool = False,
    ) -> HistoricalAccountStateSnapshot:
        """Return the current simulated state at a deterministic timestamp.

        When require_current_marks is true, every open position must have
        an explicit mark observed at exactly timestamp. Older marks are not
        reused for a time-indexed research sample, preventing stale
        valuation from masquerading as current market evidence.
        """
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return self._snapshot(
            timestamp,
            require_current_marks=require_current_marks,
        )

    def _snapshot(
        self,
        timestamp: datetime,
        *,
        require_current_marks: bool = False,
    ) -> HistoricalAccountStateSnapshot:
        positions = self._accounting.snapshot()
        realized = Money(
            sum((entry.realized_pnl for entry in positions), Decimal("0")),
            self._currency,
        )
        fees = Money(self._fees, self._currency)
        cash = self._cash.balance if self._cash_available else None

        unavailable: list[str] = []
        signed_market_value = Decimal("0")
        unrealized = Decimal("0")
        gross_exposure = Decimal("0")

        for entry in positions:
            instrument = self._instrument_registry.resolve(entry.instrument)
            mark = self._marks.get(entry.instrument)
            mark_unusable = (
                mark is None
                or mark.price is None
                or mark.observed_at is None
                or mark.observed_at > timestamp
                or (require_current_marks and mark.observed_at != timestamp)
            )
            if instrument is None or mark_unusable:
                unavailable.append(str(entry.instrument))
                continue

            position = Position(
                instrument=instrument,
                quantity=entry.quantity,
                average_price=entry.average_price,
                realized_pnl=entry.realized_pnl,
            )
            valuation = self._valuator.value(position, mark)
            signed_market_value += (
                entry.quantity * mark.price * instrument.multiplier
            )
            unrealized += valuation.unrealized_pnl
            gross_exposure += abs(entry.quantity) * mark.price * instrument.multiplier

        issue = self._issue
        if unavailable:
            issue = issue or "one or more positions lack an explicit mark"

        if cash is None or unavailable:
            return HistoricalAccountStateSnapshot(
                timestamp=timestamp,
                capital_source=self._capital_source,
                cash=cash,
                market_value=None,
                equity=None,
                realized_pnl=realized,
                unrealized_pnl=None,
                gross_exposure=None,
                fees=fees,
                positions=positions,
                completeness=AccountStateCompleteness.INCOMPLETE,
                unavailable_instruments=tuple(unavailable),
                issue=issue,
            )

        market_value = Money(signed_market_value, self._currency)
        equity = Money(cash.amount + signed_market_value, self._currency)
        return HistoricalAccountStateSnapshot(
            timestamp=timestamp,
            capital_source=self._capital_source,
            cash=cash,
            market_value=market_value,
            equity=equity,
            realized_pnl=realized,
            unrealized_pnl=Money(unrealized, self._currency),
            gross_exposure=Money(gross_exposure, self._currency),
            fees=fees,
            positions=positions,
            completeness=AccountStateCompleteness.COMPLETE,
        )


__all__ = [
    "AccountStateCompleteness",
    "HistoricalAccountStateSnapshot",
    "HistoricalAccountStateTracker",
]
