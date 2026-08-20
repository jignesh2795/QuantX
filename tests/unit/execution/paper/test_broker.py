from decimal import Decimal

from quantx.execution.paper.broker import PaperBroker
from quantx.execution.paper.evidence import SimulationEvidenceStatus
from quantx.execution.paper.fills import MarketSnapshot
from quantx.execution.paper.order_types import PaperOrderSpec, PaperOrderType
from quantx.execution.paper.profile import ExecutionProfile, SlippageModel


def profile() -> ExecutionProfile:
    return ExecutionProfile(
        profile_id="test",
        version="1",
        slippage_model=SlippageModel.NONE,
        fee_rate=Decimal("0.001"),
    )


def test_missing_market_evidence_is_not_filled() -> None:
    broker = PaperBroker(profile())
    order = PaperOrderSpec("BUY", PaperOrderType.MARKET, Decimal("2"))

    result = broker.execute(order, snapshot=None, submitted_at_ns=10)

    assert result.evidence.status is SimulationEvidenceStatus.INSUFFICIENT
    assert result.fill is None


def test_market_buy_uses_ask_and_fee() -> None:
    broker = PaperBroker(profile())
    order = PaperOrderSpec("BUY", PaperOrderType.MARKET, Decimal("2"))
    snapshot = MarketSnapshot(Decimal("99"), Decimal("100"), Decimal("99.5"))

    result = broker.execute(order, snapshot=snapshot, submitted_at_ns=10)

    assert result.evidence.status is SimulationEvidenceStatus.CONFIRMED
    assert result.fill is not None
    assert result.fill.price == Decimal("100")
    assert result.fill.quantity == Decimal("2")
    assert result.fill.fee == Decimal("0.200")
    assert result.fill_at_ns == 10


def test_non_marketable_limit_does_not_fill() -> None:
    broker = PaperBroker(profile())
    order = PaperOrderSpec("BUY", PaperOrderType.LIMIT, Decimal("2"), limit_price=Decimal("99"))
    snapshot = MarketSnapshot(Decimal("99.5"), Decimal("100"), Decimal("99.7"))

    result = broker.execute(order, snapshot=snapshot, submitted_at_ns=10)

    assert result.fill is None
    assert result.match.executable is False
    assert result.evidence.status is SimulationEvidenceStatus.CONFIRMED
