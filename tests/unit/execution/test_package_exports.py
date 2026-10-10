import quantx.execution
from quantx.execution import ExecutionContinuationChain
from quantx.execution.continuation import ExecutionContinuationChain as ContinuationChain


def test_package_export_resolves_to_defining_module_class() -> None:
    assert ExecutionContinuationChain is ContinuationChain


def test_package_all_declares_continuation_chain() -> None:
    assert "ExecutionContinuationChain" in quantx.execution.__all__
