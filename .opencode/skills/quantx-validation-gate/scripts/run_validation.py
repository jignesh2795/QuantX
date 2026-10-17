#!/usr/bin/env python3
"""Read-only QuantX validation gate runner.

Runs the repository validation commands, classifies every result as
PASS / FAIL / UNKNOWN (fail-closed), binds the evidence to the exact commit
SHA, and writes machine-readable JSON evidence outside the working tree.

The script never modifies the repository and never fixes anything. Missing
tools, timeouts, unparsed summaries, skipped checks, dirty tracked files, or
a HEAD change during the run are never reported as PASS.

Usage:
    python .opencode/skills/quantx-validation-gate/scripts/run_validation.py
    python ... run_validation.py --expected-head <sha> --base origin/main
    python ... run_validation.py --pytest-target tests/unit/execution/
    python ... run_validation.py --self-test

Every check record stores the actual argument vector (`argv`) it ran, and the
evidence stores the `base_rev` the changed-file scope was computed against.
A run produced with `--pytest-target` is a diagnostic: its recorded argv is
not the canonical full-suite invocation ["uv", "run", "pytest"], and the
release gate rejects it as mandatory full-suite evidence regardless of its
test counts or overall verdict. Scope is verified by the release gate from
recorded arguments, never by a self-declared label or the overall field.

Exit codes: 0 = PASS, 1 = FAIL, 2 = UNKNOWN, 3 = usage/internal error.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

SCHEMA = "quantx.validation-evidence.v1"
EVIDENCE_DIR_NAME = "quantx-validation"
OUTPUT_TAIL_CHARS = 4000

_PYTEST_COUNT_RE = re.compile(
    r"(\d+) (passed|failed|error|errors|skipped|xfailed|xpassed|deselected)"
)

# Canonical full-suite invocation. The release gate requires exactly this
# argv on a PASS pytest record; anything else (e.g. --pytest-target paths)
# is diagnostic-only evidence.
CANONICAL_PYTEST_ARGV = ("uv", "run", "pytest")


def pytest_argv(targets: list[str]) -> list[str]:
    """Build the actual pytest invocation; recorded verbatim in the evidence."""
    return [*CANONICAL_PYTEST_ARGV, *targets]


@dataclass
class RunOutcome:
    """Raw subprocess outcome before per-check classification."""

    kind: str  # completed | timeout | missing | error
    exit_code: int | None = None
    duration_s: float = 0.0
    notes: list[str] = field(default_factory=list)
    output_tail: str = ""


@dataclass
class Check:
    name: str
    argv: list[str]
    status: str
    exit_code: int | None = None
    duration_s: float | None = None
    summary: str = ""
    notes: list[str] = field(default_factory=list)
    output_tail: str = ""


def run_command(argv: list[str], cwd: Path, timeout: float) -> RunOutcome:
    """Execute one read-only command; never raises for command failures."""
    tool = shutil.which(argv[0])
    if tool is None:
        return RunOutcome("missing", notes=[f"tool not found on PATH: {argv[0]}"])
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [tool, *argv[1:]],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout if isinstance(exc.stdout, str) else ""
        return RunOutcome(
            "timeout",
            duration_s=time.monotonic() - started,
            notes=[f"timed out after {timeout:.0f}s"],
            output_tail=partial[-OUTPUT_TAIL_CHARS:],
        )
    except OSError as exc:
        return RunOutcome(
            "error",
            duration_s=time.monotonic() - started,
            notes=[f"launch failed: {exc}"],
        )
    output = (proc.stdout or "") + (proc.stderr or "")
    return RunOutcome(
        "completed",
        exit_code=proc.returncode,
        duration_s=time.monotonic() - started,
        output_tail=output[-OUTPUT_TAIL_CHARS:],
    )


def classify_pytest(exit_code: int, output: str) -> tuple[str, str, list[str]]:
    """Classify a pytest run; exit 0 without a parsed pass summary is UNKNOWN."""
    counts: dict[str, int] = {}
    for match in _PYTEST_COUNT_RE.finditer(output):
        key = match.group(2)
        if key == "error":
            key = "errors"
        counts[key] = max(counts.get(key, 0), int(match.group(1)))
    summary = ", ".join(f"{value} {key}" for key, value in sorted(counts.items()))
    if not summary:
        summary = "no pytest summary line parsed"
    if "no tests ran" in output:
        return FAIL, summary, ["pytest collected no tests"]
    if exit_code == 0:
        if counts.get("failed") or counts.get("errors"):
            return UNKNOWN, summary, ["exit 0 contradicts failure counts; evidence rejected"]
        if not counts.get("passed"):
            return UNKNOWN, summary, ["exit 0 without a parsed pass summary; incomplete evidence"]
        return PASS, summary, []
    return FAIL, summary, [f"pytest exit code {exit_code}"]


def classify_exit_zero(exit_code: int) -> tuple[str, list[str]]:
    """Classify a command whose only contract is zero/nonzero exit."""
    if exit_code == 0:
        return PASS, []
    return FAIL, [f"exit code {exit_code}"]


def classify_diff_check(outcome: RunOutcome) -> tuple[str, str, list[str]]:
    """Classify `git diff --check`: findings => FAIL, git errors => UNKNOWN."""
    if outcome.kind != "completed":
        return UNKNOWN, "diff check did not complete", outcome.notes
    if outcome.exit_code == 0:
        return PASS, "no whitespace errors", []
    output = outcome.output_tail
    if output.strip() and "fatal:" not in output:
        return FAIL, "whitespace errors found", ["git diff --check reported findings"]
    return UNKNOWN, "git diff --check failed without actionable output", ["git error"]


def classify_status(porcelain: str) -> tuple[str, list[str], list[str]]:
    """Classify worktree state: tracked modifications fail, untracked is noted."""
    tracked: list[str] = []
    untracked: list[str] = []
    for line in porcelain.splitlines():
        if not line.strip():
            continue
        if line.startswith("??"):
            untracked.append(line[3:].strip())
        else:
            tracked.append(line.strip())
    if tracked:
        return FAIL, tracked, untracked
    return PASS, tracked, untracked


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run a read-only git command; returns None when git is unavailable."""
    if shutil.which("git") is None:
        return None
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def resolve_head(repo: Path) -> str | None:
    proc = git(repo, "rev-parse", "HEAD")
    if proc is None or proc.returncode != 0:
        return None
    return proc.stdout.strip()


def resolve_rev(repo: Path, rev: str) -> bool:
    proc = git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return proc is not None and proc.returncode == 0


def changed_files(repo: Path, base: str) -> list[str] | None:
    """Tracked, added-or-modified files versus base; None when base is unknown."""
    if not resolve_rev(repo, base):
        return None
    proc = git(repo, "diff", "--name-only", "--diff-filter=ACMR", base)
    if proc is None or proc.returncode != 0:
        return None
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def build_checks(args: argparse.Namespace, repo: Path) -> list[Check]:
    checks: list[Check] = []

    if args.skip_pytest:
        checks.append(
            Check(
                "pytest",
                [*CANONICAL_PYTEST_ARGV],
                UNKNOWN,
                notes=["skipped by request"],
            )
        )
    else:
        argv = pytest_argv(args.pytest_target)
        outcome = run_command(argv, repo, args.timeout)
        if outcome.kind != "completed" or outcome.exit_code is None:
            checks.append(
                Check(
                    "pytest",
                    argv,
                    UNKNOWN,
                    duration_s=outcome.duration_s,
                    notes=outcome.notes,
                    output_tail=outcome.output_tail,
                )
            )
        else:
            status, summary, notes = classify_pytest(outcome.exit_code, outcome.output_tail)
            checks.append(
                Check(
                    "pytest",
                    argv,
                    status,
                    exit_code=outcome.exit_code,
                    duration_s=outcome.duration_s,
                    summary=summary,
                    notes=notes,
                    output_tail=outcome.output_tail,
                )
            )

    files = changed_files(repo, args.base)
    py_files = [path for path in files if path.endswith(".py")] if files is not None else None
    if args.skip_ruff:
        for name in ("ruff-check", "ruff-format"):
            checks.append(Check(name, [], UNKNOWN, notes=["skipped by request"]))
    elif py_files is None:
        note = [f"cannot resolve base rev '{args.base}'; changed-file scope unknown"]
        checks.append(Check("ruff-check", [], UNKNOWN, notes=note))
        checks.append(Check("ruff-format", [], UNKNOWN, notes=note))
    elif not py_files:
        note = [f"no changed Python files versus {args.base}"]
        checks.append(Check("ruff-check", [], PASS, summary="vacuous pass", notes=note))
        checks.append(Check("ruff-format", [], PASS, summary="vacuous pass", notes=note))
    else:
        for name, extra in (("ruff-check", []), ("ruff-format", ["--check"])):
            argv = ["uv", "run", "ruff", ("format" if extra else "check"), *extra, *py_files]
            outcome = run_command(argv, repo, args.timeout)
            if outcome.kind != "completed" or outcome.exit_code is None:
                checks.append(
                    Check(
                        name,
                        argv,
                        UNKNOWN,
                        duration_s=outcome.duration_s,
                        notes=outcome.notes,
                        output_tail=outcome.output_tail,
                    )
                )
            else:
                status, notes = classify_exit_zero(outcome.exit_code)
                checks.append(
                    Check(
                        name,
                        argv,
                        status,
                        exit_code=outcome.exit_code,
                        duration_s=outcome.duration_s,
                        summary=f"{len(py_files)} changed file(s)",
                        notes=notes,
                        output_tail=outcome.output_tail,
                    )
                )

    if args.skip_mypy:
        checks.append(Check("mypy", ["uv", "run", "mypy"], UNKNOWN, notes=["skipped by request"]))
    else:
        argv = ["uv", "run", "mypy"]
        outcome = run_command(argv, repo, args.timeout)
        if outcome.kind != "completed" or outcome.exit_code is None:
            checks.append(
                Check(
                    "mypy",
                    argv,
                    UNKNOWN,
                    duration_s=outcome.duration_s,
                    notes=outcome.notes,
                    output_tail=outcome.output_tail,
                )
            )
        else:
            status, notes = classify_exit_zero(outcome.exit_code)
            checks.append(
                Check(
                    "mypy",
                    argv,
                    status,
                    exit_code=outcome.exit_code,
                    duration_s=outcome.duration_s,
                    notes=notes,
                    output_tail=outcome.output_tail,
                )
            )

    if args.skip_diffcheck:
        checks.append(
            Check(
                "git-diff-check", ["git", "diff", "--check"], UNKNOWN, notes=["skipped by request"]
            )
        )
    else:
        argv = ["git", "diff", "--check"]
        outcome = run_command(argv, repo, args.timeout)
        status, summary, notes = classify_diff_check(outcome)
        checks.append(
            Check(
                "git-diff-check",
                argv,
                status,
                exit_code=outcome.exit_code,
                duration_s=outcome.duration_s,
                summary=summary,
                notes=notes,
                output_tail=outcome.output_tail,
            )
        )

    if args.skip_integrity:
        checks.append(
            Check(
                "worktree-integrity",
                ["git", "status", "--porcelain"],
                UNKNOWN,
                notes=["skipped by request"],
            )
        )
    else:
        proc = git(repo, "status", "--porcelain")
        argv = ["git", "status", "--porcelain"]
        if proc is None or proc.returncode != 0:
            checks.append(Check("worktree-integrity", argv, UNKNOWN, notes=["git status failed"]))
        else:
            status, tracked, untracked = classify_status(proc.stdout)
            notes = []
            if untracked:
                notes.append(f"untracked (not evidence): {', '.join(untracked[:10])}")
            if tracked:
                notes.append(f"tracked modifications: {', '.join(tracked[:10])}")
            checks.append(
                Check(
                    "worktree-integrity",
                    argv,
                    status,
                    summary="clean tracked tree" if status == PASS else "tracked modifications",
                    notes=notes,
                )
            )
    return checks


def aggregate(checks: list[Check]) -> str:
    if any(check.status == FAIL for check in checks):
        return FAIL
    if any(check.status == UNKNOWN for check in checks):
        return UNKNOWN
    return PASS


def evidence_path(output: str | None, head: str) -> Path:
    if output:
        return Path(output)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path(tempfile.gettempdir()) / EVIDENCE_DIR_NAME / f"validation-{head[:12]}-{stamp}.json"


def print_report(report: dict, json_path: Path) -> None:
    print(f"QuantX validation evidence  HEAD={report['head_sha']}  base={report['base_rev']}")
    if report.get("expected_head"):
        print(f"expected_head={report['expected_head']}")
    for check in report["checks"]:
        exit_code = "" if check["exit_code"] is None else f" exit={check['exit_code']}"
        duration = "" if check["duration_s"] is None else f" {check['duration_s']:.1f}s"
        summary = f"  {check['summary']}" if check["summary"] else ""
        print(f"[{check['status']}] {check['name']}{exit_code}{duration}{summary}")
        if check["status"] != PASS:
            for note in check["notes"]:
                print(f"    note: {note}")
            if check["output_tail"]:
                for line in check["output_tail"].splitlines()[-12:]:
                    print(f"    | {line}")
    print(f"OVERALL: {report['overall']}")
    print(f"evidence: {json_path}")


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_validation(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    head = resolve_head(repo)
    if head is None:
        print("error: cannot resolve HEAD (is this a git repository?)", file=sys.stderr)
        return 3
    if args.expected_head and head != args.expected_head:
        report = {
            "schema": SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "repo": str(repo),
            "head_sha": head,
            "expected_head": args.expected_head,
            "base_rev": args.base,
            "checks": [],
            "overall": UNKNOWN,
            "reason": f"requested HEAD {args.expected_head} does not match repository HEAD {head}",
        }
        path = evidence_path(args.output, head)
        write_report(report, path)
        print_report(report, path)
        return 2

    checks = build_checks(args, repo)
    head_after = resolve_head(repo)
    if head_after != head:
        checks.append(
            Check(
                "head-stability",
                ["git", "rev-parse", "HEAD"],
                FAIL,
                notes=[f"HEAD changed during validation: {head} -> {head_after}"],
            )
        )
    report = {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "repo": str(repo),
        "head_sha": head,
        "expected_head": args.expected_head,
        "base_rev": args.base,
        "checks": [asdict(check) for check in checks],
        "overall": aggregate(checks),
    }
    path = evidence_path(args.output, head)
    write_report(report, path)
    print_report(report, path)
    return 0 if report["overall"] == PASS else (1 if report["overall"] == FAIL else 2)


def self_test() -> int:
    failures: list[str] = []
    total = 0

    def check(name: str, condition: bool) -> None:
        nonlocal total
        total += 1
        if not condition:
            failures.append(name)

    check("pytest pass", classify_pytest(0, "2027 passed, 1 skipped in 12.3s")[0] == PASS)
    check(
        "canonical full-suite argv",
        pytest_argv([]) == list(CANONICAL_PYTEST_ARGV)
        and pytest_argv([]) == ["uv", "run", "pytest"],
    )
    check(
        "targeted argv recorded verbatim",
        pytest_argv(["tests/unit/execution/"]) == ["uv", "run", "pytest", "tests/unit/execution/"],
    )
    check(
        "targeted argv is not canonical",
        tuple(pytest_argv(["tests/"])) != CANONICAL_PYTEST_ARGV,
    )
    check("pytest fail", classify_pytest(1, "3 failed, 10 passed in 4s")[0] == FAIL)
    check("pytest no tests", classify_pytest(5, "no tests ran in 0.01s")[0] == FAIL)
    check("pytest contradiction", classify_pytest(0, "2 failed, 5 passed in 1s")[0] == UNKNOWN)
    check("pytest missing summary", classify_pytest(0, "collected something")[0] == UNKNOWN)
    check("exit zero pass", classify_exit_zero(0)[0] == PASS)
    check("exit nonzero fail", classify_exit_zero(1)[0] == FAIL)
    check(
        "diff check clean",
        classify_diff_check(RunOutcome("completed", exit_code=0))[0] == PASS,
    )
    check(
        "diff check findings",
        classify_diff_check(
            RunOutcome("completed", exit_code=2, output_tail="a.py:1: trailing whitespace.")
        )[0]
        == FAIL,
    )
    check(
        "diff check git error",
        classify_diff_check(
            RunOutcome("completed", exit_code=128, output_tail="fatal: not a git repository")
        )[0]
        == UNKNOWN,
    )
    check(
        "diff check timeout",
        classify_diff_check(RunOutcome("timeout", notes=["timed out"]))[0] == UNKNOWN,
    )
    check("status clean", classify_status("")[0] == PASS)
    check("status untracked only", classify_status("?? log.txt\n")[0] == PASS)
    check("status tracked dirty", classify_status(" M src/quantx/x.py\n")[0] == FAIL)
    check("aggregate fail wins", aggregate([Check("a", [], UNKNOWN), Check("b", [], FAIL)]) == FAIL)
    check(
        "aggregate unknown", aggregate([Check("a", [], PASS), Check("b", [], UNKNOWN)]) == UNKNOWN
    )
    check("aggregate pass", aggregate([Check("a", [], PASS), Check("b", [], PASS)]) == PASS)

    ok = run_command([sys.executable, "-c", "print('2027 passed in 0.01s')"], Path.cwd(), 30)
    check("run_command completed", ok.kind == "completed" and ok.exit_code == 0)
    bad = run_command([sys.executable, "-c", "raise SystemExit(1)"], Path.cwd(), 30)
    check("run_command nonzero", bad.kind == "completed" and bad.exit_code == 1)
    missing = run_command(["__qx_missing_tool__", "--help"], Path.cwd(), 5)
    check("run_command missing", missing.kind == "missing")
    slow = run_command([sys.executable, "-c", "import time; time.sleep(3)"], Path.cwd(), 1)
    check("run_command timeout", slow.kind == "timeout")

    if failures:
        print(f"SELF-TEST FAILED ({len(failures)}/{total} failing): {', '.join(failures)}")
        return 1
    print(f"SELF-TEST PASS: {total} checks")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only QuantX validation gate runner")
    parser.add_argument("--repo", default=".", help="repository path (default: cwd)")
    parser.add_argument("--base", default="origin/main", help="changed-file base rev")
    parser.add_argument("--expected-head", default=None, help="required exact HEAD SHA")
    parser.add_argument(
        "--pytest-target",
        action="append",
        default=[],
        help="pytest path selector (repeatable); default full suite. A targeted "
        "run is diagnostic evidence only: its recorded argv cannot satisfy "
        "the release gate's canonical full-suite contract.",
    )
    parser.add_argument("--timeout", type=float, default=3600.0, help="per-check timeout seconds")
    parser.add_argument("--output", default=None, help="evidence JSON path (default: temp dir)")
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--skip-ruff", action="store_true")
    parser.add_argument("--skip-mypy", action="store_true")
    parser.add_argument("--skip-diffcheck", action="store_true")
    parser.add_argument("--skip-integrity", action="store_true")
    parser.add_argument("--self-test", action="store_true", help="validate evaluator behavior only")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    try:
        return run_validation(args)
    except Exception as exc:
        # Top-level guard: report the failure honestly; never attempt a fix.
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
