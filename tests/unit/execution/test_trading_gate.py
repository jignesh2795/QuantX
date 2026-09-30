from types import SimpleNamespace

from quantx.application.execution import ExecutionDispatchStatus, ExecutionOrchestrator
from quantx.execution.trading_gate import (
    DurableTradingGate,
    InMemoryTradingGateStateStore,
    TradingGate,
    TradingGateState,
)


def _paper_request() -> object:
    return SimpleNamespace(
        execution_context=SimpleNamespace(execution_mode="paper"),
    )


def test_gate_blocks_and_reports_reason() -> None:
    gate = TradingGate()
    state = gate.block("operator emergency stop")

    assert state.enabled is False
    assert state.reason == "operator emergency stop"
    assert gate.allow() is False

    gate.enable()
    assert gate.allow() is True
    assert gate.state().reason == ""


def test_orchestrator_fails_closed_before_adapter_submission() -> None:
    gate = TradingGate()
    gate.block("risk limit reached")
    called = False

    class Adapter:
        def execute(self, request, *, snapshot):
            nonlocal called
            called = True
            raise AssertionError("adapter must not be called")

    result = ExecutionOrchestrator(
        paper_executor=Adapter(),
        trading_gate=gate,
    ).execute(_paper_request())

    assert result.status is ExecutionDispatchStatus.BLOCKED
    assert result.reason == "trading is blocked: risk limit reached"
    assert called is False


def test_empty_kill_switch_reason_is_rejected() -> None:
    gate = TradingGate()

    try:
        gate.block(" ")
    except ValueError as exc:
        assert str(exc) == "kill-switch reason must not be empty"
    else:
        raise AssertionError("expected ValueError")



def test_durable_gate_state_survives_gate_recreation() -> None:
    store = InMemoryTradingGateStateStore()
    first = DurableTradingGate(store)
    first.block("operator emergency stop")

    second = DurableTradingGate(store)

    assert second.allow() is False
    assert second.state() == TradingGateState(False, "operator emergency stop")
