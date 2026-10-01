from quantx.execution.preconditions.evaluator import ExecutionPrecondition, PreconditionEvaluator
from quantx.execution.preconditions.models import PreconditionsStatus


def test_unknown_precondition_does_not_pass() -> None:
    result = PreconditionEvaluator().evaluate([
        ExecutionPrecondition("broker_state", lambda: None),
    ])
    assert result.status is PreconditionsStatus.UNKNOWN
    assert not result.can_execute


def test_false_precondition_blocks() -> None:
    result = PreconditionEvaluator().evaluate([
        ExecutionPrecondition("position_fresh", lambda: False),
    ])
    assert result.status is PreconditionsStatus.BLOCKED
    assert not result.can_execute


def test_all_true_preconditions_ready() -> None:
    result = PreconditionEvaluator().evaluate([
        ExecutionPrecondition("account", lambda: True),
        ExecutionPrecondition("position", lambda: True),
    ])
    assert result.status is PreconditionsStatus.READY
    assert result.can_execute
