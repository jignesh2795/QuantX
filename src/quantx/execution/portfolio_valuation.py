"""Portfolio valuation using explicit marks and accounting inputs."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quantx.domain.portfolio import PortfolioSnapshot
from quantx.domain.value_objects import Money

from .valuation import Mark, MarkToMarketValuator, ValuationResult
from quantx.domain.positions import Position


@dataclass(frozen=True, slots=True)
class PortfolioValuationResult:
    """Valuation output with completeness and per-position provenance."""

    snapshot: PortfolioSnapshot
    completeness: str
    valuations: tuple[ValuationResult, ...]
    unavailable_instruments: tuple[str, ...] = ()


class PortfolioValuator:
    """Build a portfolio snapshot without inventing missing market marks."""

    def __init__(self, mark_to_market: MarkToMarketValuator | None = None) -> None:
        self._mtm = mark_to_market or MarkToMarketValuator()

    def value(
        self,
        *,
        portfolio_id,
        valuation_currency: str,
        cash: Money,
        margin_used: Money,
        positions: tuple[Position, ...],
        marks: tuple[Mark, ...],
        realized_pnl: Decimal,
    ) -> PortfolioValuationResult:
        marks_by_instrument = {mark.instrument_id: mark for mark in marks}
        results: list[ValuationResult] = []
        market_value = Decimal("0")
        unrealized = Decimal("0")
        unavailable: list[str] = []

        for position in positions:
            mark = marks_by_instrument.get(str(position.instrument.instrument_id))
            if mark is None:
                unavailable.append(str(position.instrument.instrument_id))
                continue
            result = self._mtm.value(position=position, mark=mark)
            results.append(result)
            market_value += result.market_value.amount
            unrealized += result.unrealized_pnl.amount

        snapshot = PortfolioSnapshot(
            portfolio_id=portfolio_id,
            valuation_currency=valuation_currency,
            cash=cash,
            market_value=Money(market_value, valuation_currency),
            realized_pnl=Money(realized_pnl, valuation_currency),
            unrealized_pnl=Money(unrealized, valuation_currency),
            margin_used=margin_used,
        )
        completeness = "COMPLETE" if not unavailable else "INCOMPLETE"
        return PortfolioValuationResult(snapshot, completeness, tuple(results), tuple(unavailable))
