"""Deterministic, credential-free paper execution smoke example.

Run with:
    uv run python examples/paper_smoke.py
"""

from decimal import Decimal

from quantx.execution.paper.broker import PaperBroker
from quantx.execution.paper.fills import MarketSnapshot
from quantx.execution.paper.order_types import PaperOrderSpec, PaperOrderType, PaperTimeInForce
from quantx.execution.paper.profile import ExecutionProfile, SlippageModel


def main() -> None:
    profile = ExecutionProfile(
        profile_id="paper-smoke",
        version="1",
        slippage_model=SlippageModel.SPREAD_AWARE,
        slippage_bps=Decimal("10"),
    )
    broker = PaperBroker(profile=profile)
    order = PaperOrderSpec(
        side="BUY",
        order_type=PaperOrderType.MARKET,
        quantity=Decimal("10"),
        time_in_force=PaperTimeInForce.IOC,
    )
    snapshot = MarketSnapshot(bid=Decimal("99"), ask=Decimal("100"), last=Decimal("99.5"))
    result = broker.execute(order, snapshot=snapshot, submitted_at_ns=0)

    print("paper smoke: OK")
    print(f"match executable: {result.match.executable}")
    print(f"evidence status: {result.evidence.status.value}")
    if result.fill is not None:
        print(f"fill price: {result.fill.price}")
        print(f"fill quantity: {result.fill.quantity}")


if __name__ == "__main__":
    main()
