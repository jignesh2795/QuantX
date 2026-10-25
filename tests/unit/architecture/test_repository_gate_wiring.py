"""Repository gate wiring: the Ruff gate must cover lint *and* format.

The merge gate is "pytest green + changed-file Ruff lint and format clean +
``git diff --check`` clean". Both automated enforcement points -- the pre-push
hook and CI -- must run ``ruff format --check`` as well as ``ruff check``.
Pytest cannot detect either defect class, so a lint-only or path-scoped gate
lets an unformatted file reach a pull request unnoticed.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOOK = _REPO_ROOT / "scripts" / "hooks" / "pre-push"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "test.yml"


def _ruff_run_lines(workflow_text: str) -> tuple[str, ...]:
    """Return every ``run:`` command in the workflow that invokes Ruff."""

    return tuple(
        line.split("run:", 1)[1].strip()
        for line in workflow_text.splitlines()
        if line.strip().startswith("run:") and "ruff" in line
    )


def test_pre_push_hook_runs_ruff_lint_and_format_on_changed_files() -> None:
    hook = _HOOK.read_text(encoding="utf-8")

    assert "ruff check" in hook
    assert "ruff format --check" in hook
    assert "'@{push}...HEAD'" in hook


def test_ci_runs_ruff_lint_and_format_across_the_whole_tree() -> None:
    run_lines = _ruff_run_lines(_WORKFLOW.read_text(encoding="utf-8"))

    assert "uv run ruff check ." in run_lines
    assert "uv run ruff format --check src tests" in run_lines


def test_ci_ruff_steps_are_not_path_scoped_to_one_plugin() -> None:
    run_lines = _ruff_run_lines(_WORKFLOW.read_text(encoding="utf-8"))

    assert run_lines
    for run_line in run_lines:
        assert "plugins/dhan" not in run_line
