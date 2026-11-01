#!/usr/bin/env python3
"""Enforce measured package-specific line and branch coverage floors.

The aggregate suite percentage is not a package guarantee. This gate measures
`quantx.domain`, `quantx.execution` and `quantx.persistence` independently and
fails when either the line or the branch coverage of any measured package falls
below its reviewed floor.

A new package cannot silently bypass the gate: every importable package under
`src/quantx/` discovered in the coverage JSON must appear in the explicit
package inventory below as either ``measured`` (with an enforced floor) or
``excluded`` (with a documented reason). Any discovered package absent from the
inventory fails closed.

Measurement rules:

* the full pytest suite runs in the locked project environment;
* coverage is collected with branch measurement enabled;
* every module under each measured package is included, whether or not a test
  imports it, because the source is the package (no static file allowlist);
* the coverage JSON must prove `branch_coverage: true`; otherwise the result is
  UNKNOWN, never PASS;
* a missing package, a non-positive statement/branch count, malformed data, a
  missing tool, a timeout, or a failed measurement is UNKNOWN, never PASS;
* exit codes are 0 = PASS, 1 = FAIL (test failure or floor breach),
  2 = UNKNOWN, 3 = usage/internal error.

The floors are derived from the measured baseline at base SHA
`9841ae361e3612341cdc728c66ccf47d6ebcbd79`: each floor is at least one full
percentage point below the truncated measured value. The canonical policy and
evidence are recorded in `docs/implementation/package-coverage-floors.md`.

Usage:
    python .opencode/skills/quantx-validation-gate/scripts/package_coverage.py
    python ... package_coverage.py --analyze <coverage-json>
    python ... package_coverage.py --self-test

The default command runs the full suite through the current Python
interpreter, so invoke it through `uv run python ...` to use the locked
environment. The coverage JSON is written outside the repository under the
system temp directory; no tracked or untracked repository file is created.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

EVIDENCE_DIR_NAME = "quantx-validation"
SUMMARY_PREFIX = "SUMMARY: "
DEFAULT_TIMEOUT = 3600.0
COVERAGE_JSON_NAME = "package-coverage.json"


@dataclass(frozen=True)
class PackageFloor:
    """Reviewed minimum percentages for one measured package."""

    line: int
    branch: int


# Explicit package inventory. Every importable package discovered in the
# coverage JSON must be present here. Measured packages are checked against
# floors. Excluded packages are accepted only with a documented reason. Any
# discovered package absent from this mapping fails closed so a new package
# cannot silently bypass the gate.
#
# Status values:
#   "measured" -> floor is enforced
#   "excluded" -> reason is recorded; coverage is not enforced
PACKAGE_INVENTORY: dict[str, tuple[str, str]] = {
    "domain": (
        "measured",
        "safety-critical domain money/risk contracts",
    ),
    "execution": (
        "measured",
        "safety-critical execution control path",
    ),
    "persistence": (
        "measured",
        "safety-critical durable execution and recovery state",
    ),
    "application": (
        "excluded",
        "application-layer orchestration; correctness verified by integration tests",
    ),
    "india": (
        "excluded",
        "India-market data adapter; coverage tracked by separate market-pack checks",
    ),
    "plugins": (
        "excluded",
        "broker plugin boundary; Dhan transport coverage tracked in issue #202",
    ),
    "ports": (
        "excluded",
        "interface definitions without direct business logic",
    ),
    "research": (
        "excluded",
        "research utilities; not safety-critical for coverage floors",
    ),
    "strategy": (
        "excluded",
        "strategy implementations; correctness covered by confidence-contract tests",
    ),
}

# Baseline at 9841ae361e3612341cdc728c66ccf47d6ebcbd79, full suite, locked
# Python 3.12 environment, branch measurement enabled:
#   domain       line 88.77% (2078/2341)  branch 74.66% (775/1038)
#   execution    line 89.30% (3062/3429)  branch 75.41% (1003/1330)
#   persistence  line 93.16% (872/936)    branch 81.48% (220/270)
# Each floor is floor(measured) - 1, i.e. at least one full percentage point
# below the measured baseline. The same rule is applied to every measured
# package, so the floors are measured and reproducible rather than aspirational
# targets.
PACKAGE_FLOORS: dict[str, PackageFloor] = {
    "domain": PackageFloor(line=87, branch=73),
    "execution": PackageFloor(line=88, branch=74),
    "persistence": PackageFloor(line=92, branch=80),
}
MEASURED_PACKAGES: tuple[str, ...] = (
    "domain",
    "execution",
    "persistence",
)

_SUMMARY_FIELDS = (
    "num_statements",
    "covered_lines",
    "num_branches",
    "covered_branches",
)


@dataclass(frozen=True)
class PackageMeasurement:
    """Aggregated line and branch coverage for one measured package."""

    package: str
    line_covered: int
    line_total: int
    branch_covered: int
    branch_total: int

    @property
    def line_percent(self) -> Decimal:
        return _percent(self.line_covered, self.line_total)

    @property
    def branch_percent(self) -> Decimal:
        return _percent(self.branch_covered, self.branch_total)

    def line_pass(self, floor: PackageFloor) -> bool:
        return self.line_covered * 100 >= floor.line * self.line_total

    def branch_pass(self, floor: PackageFloor) -> bool:
        return self.branch_covered * 100 >= floor.branch * self.branch_total


def _percent(covered: int, total: int) -> Decimal:
    return (Decimal(covered) * Decimal(100) / Decimal(total)).quantize(Decimal("0.01"))


def _belongs(path: str, package: str) -> bool:
    """Return True when a coverage file path is under ``quantx.<package>``."""
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if part == "quantx" and parts[index + 1] == package:
            return True
    return False


def _package_from_path(path: str) -> str | None:
    """Extract the ``quantx.<package>`` name from a coverage file path."""
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if part == "quantx" and index + 1 < len(parts):
            candidate = parts[index + 1]
            if candidate:
                return candidate
    return None


def _read_coverage(path: Path) -> tuple[dict[str, object] | None, str]:
    """Load and validate the coverage JSON envelope."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"coverage JSON is not readable: {exc}"
    if not isinstance(payload, dict):
        return None, "coverage JSON is not an object"
    meta = payload.get("meta")
    if not isinstance(meta, dict) or meta.get("branch_coverage") is not True:
        return None, "coverage JSON does not prove branch measurement was enabled"
    files = payload.get("files")
    if not isinstance(files, dict):
        return None, "coverage JSON has no files object"
    return files, ""


def _summary_value(summary: object, field: str) -> tuple[int | None, str]:
    if not isinstance(summary, dict):
        return None, f"file summary is not an object for {field!r}"
    value = summary.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None, f"file summary field {field!r} is not a non-negative integer"
    return value, ""


def _discover_packages(files: dict[str, object]) -> set[str]:
    """Return the set of ``quantx.<package>`` names present in the coverage JSON."""
    discovered: set[str] = set()
    for key in files:
        if not isinstance(key, str):
            continue
        package = _package_from_path(key)
        if package is not None:
            discovered.add(package)
    return discovered


def _check_inventory(discovered: set[str]) -> list[str]:
    """Validate discovered packages against the explicit inventory."""
    problems: list[str] = []
    unknown = discovered - set(PACKAGE_INVENTORY.keys())
    if unknown:
        problems.append(
            "unknown quantx package(s) discovered in coverage JSON but absent "
            f"from the explicit inventory: {', '.join(sorted(unknown))}"
        )
    for package, (status, reason) in sorted(PACKAGE_INVENTORY.items()):
        if status not in ("measured", "excluded"):
            problems.append(
                f"package inventory entry for quantx.{package} has unsupported status {status!r}"
            )
        if status == "excluded" and not reason:
            problems.append(
                f"package inventory entry for quantx.{package} is excluded "
                f"without a documented reason"
            )
    return problems


def _aggregate(
    files: dict[str, object],
) -> tuple[list[PackageMeasurement], list[str]]:
    measurements: list[PackageMeasurement] = []
    problems: list[str] = []

    discovered = _discover_packages(files)
    problems.extend(_check_inventory(discovered))

    for package in MEASURED_PACKAGES:
        rows = [
            value for key, value in files.items() if isinstance(key, str) and _belongs(key, package)
        ]
        if not rows:
            problems.append(f"no measured files for quantx.{package}")
            continue
        totals = {field: 0 for field in _SUMMARY_FIELDS}
        malformed = False
        for row in rows:
            summary = row.get("summary") if isinstance(row, dict) else None
            for field in _SUMMARY_FIELDS:
                value, problem = _summary_value(summary, field)
                if problem:
                    problems.append(f"quantx.{package}: {problem}")
                    malformed = True
                    break
                assert value is not None
                totals[field] += value
            if malformed:
                break
        if malformed:
            continue
        statements = totals["num_statements"]
        covered_lines = totals["covered_lines"]
        branches = totals["num_branches"]
        covered_branches = totals["covered_branches"]
        if statements <= 0:
            problems.append(f"quantx.{package}: no measurable statements")
            continue
        if branches <= 0:
            problems.append(f"quantx.{package}: no measurable branches")
            continue
        if covered_lines > statements:
            problems.append(f"quantx.{package}: covered lines exceed statements")
            continue
        if covered_branches > branches:
            problems.append(f"quantx.{package}: covered branches exceed branches")
            continue
        measurements.append(
            PackageMeasurement(
                package=package,
                line_covered=covered_lines,
                line_total=statements,
                branch_covered=covered_branches,
                branch_total=branches,
            )
        )
    return measurements, problems


def _statuses(measurement: PackageMeasurement) -> tuple[str, str]:
    floor = PACKAGE_FLOORS[measurement.package]
    line_status = PASS if measurement.line_pass(floor) else FAIL
    branch_status = PASS if measurement.branch_pass(floor) else FAIL
    return line_status, branch_status


def _overall(measurements: list[PackageMeasurement], problems: list[str]) -> str:
    if problems:
        return UNKNOWN
    if len(measurements) != len(MEASURED_PACKAGES):
        return UNKNOWN
    for measurement in measurements:
        if FAIL in _statuses(measurement):
            return FAIL
    return PASS


def _summary(measurements: list[PackageMeasurement]) -> str:
    parts: list[str] = []
    for measurement in measurements:
        floor = PACKAGE_FLOORS[measurement.package]
        line_status, branch_status = _statuses(measurement)
        parts.append(
            f"{measurement.package} line={measurement.line_percent:.2f}% "
            f"req={floor.line}% {line_status} "
            f"branch={measurement.branch_percent:.2f}% req={floor.branch}% {branch_status}"
        )
    return SUMMARY_PREFIX + "; ".join(parts)


def _print_measurements(measurements: list[PackageMeasurement]) -> None:
    for measurement in measurements:
        floor = PACKAGE_FLOORS[measurement.package]
        line_status, branch_status = _statuses(measurement)
        print(
            f"{measurement.package}: "
            f"line {measurement.line_covered}/{measurement.line_total} = "
            f"{measurement.line_percent:.2f}% (required {floor.line}%) {line_status}; "
            f"branch {measurement.branch_covered}/{measurement.branch_total} = "
            f"{measurement.branch_percent:.2f}% (required {floor.branch}%) {branch_status}"
        )


def _coverage_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    return Path(tempfile.gettempdir()) / EVIDENCE_DIR_NAME / COVERAGE_JSON_NAME


def _run_pytest(repo: Path, output: Path, timeout: float) -> tuple[str, int | None, str]:
    """Run the full suite under coverage; return (kind, exit_code, output)."""
    missing = [
        module
        for module in ("pytest", "pytest_cov", "coverage")
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        return "missing", None, f"required test tooling not installed: {', '.join(missing)}"
    output.parent.mkdir(parents=True, exist_ok=True)
    data_file = output.with_suffix(".data")
    for stale in (output, data_file):
        try:
            stale.unlink()
        except FileNotFoundError:
            pass
    argv = [
        sys.executable,
        "-m",
        "pytest",
        "--cov=quantx.domain",
        "--cov=quantx.execution",
        "--cov=quantx.persistence",
        "--cov-branch",
        f"--cov-report=json:{output.as_posix()}",
        "--cov-report=",
    ]
    env = dict(os.environ)
    env["COVERAGE_FILE"] = str(data_file)
    try:
        proc = subprocess.run(
            argv,
            cwd=str(repo),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout if isinstance(exc.stdout, str) else ""
        return "timeout", None, partial
    except OSError as exc:
        return "error", None, f"failed to launch coverage run: {exc}"
    return "completed", proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _report(measurements: list[PackageMeasurement], status: str) -> int:
    print("QuantX package coverage gate")
    _print_measurements(measurements)
    print(f"OVERALL: {status}")
    print(_summary(measurements))
    return 0 if status == PASS else (1 if status == FAIL else 2)


def _analyze(path: Path) -> int:
    files, problem = _read_coverage(path)
    if files is None:
        print(f"[{UNKNOWN}] {problem}")
        print("OVERALL: UNKNOWN")
        return 2
    measurements, problems = _aggregate(files)
    if problems:
        for problem in problems:
            print(f"[{UNKNOWN}] {problem}")
        print("OVERALL: UNKNOWN")
        return 2
    status = _overall(measurements, problems)
    return _report(measurements, status)


def self_test() -> int:
    failures: list[str] = []
    total = 0
    unset = object()

    def check_case(name: str, condition: bool) -> None:
        nonlocal total
        total += 1
        if not condition:
            failures.append(name)

    def summary(
        statements: int, covered: int, branches: int, covered_branches: int
    ) -> dict[str, object]:
        return {
            "summary": {
                "num_statements": statements,
                "covered_lines": covered,
                "num_branches": branches,
                "covered_branches": covered_branches,
            }
        }

    def payload(
        *,
        domain: object = unset,
        execution: object = unset,
        persistence: object = unset,
        branch_coverage: bool = True,
        extra_files: dict[str, object] | None = None,
    ) -> dict[str, object]:
        entries = {
            "domain": (domain, summary(2341, 2078, 1038, 775)),
            "execution": (execution, summary(3429, 3062, 1330, 1003)),
            "persistence": (persistence, summary(936, 872, 270, 220)),
        }
        files: dict[str, object] = {}
        for package, (value, default) in entries.items():
            if value is unset:
                files[f"src/quantx/{package}/a.py"] = default
            elif value is not None:
                files[f"src/quantx/{package}/a.py"] = value
        if extra_files is not None:
            files.update(extra_files)
        return {"meta": {"branch_coverage": branch_coverage}, "files": files}

    def analyze(data: dict[str, object]) -> tuple[list[PackageMeasurement], list[str]]:
        files = data.get("files")
        if not isinstance(files, dict):
            return [], ["missing files"]
        return _aggregate(files)

    check_case("windows domain path", _belongs(r"E:\repo\src\quantx\domain\a.py", "domain"))
    check_case("relative execution path", _belongs("quantx/execution/a.py", "execution"))
    check_case(
        "sibling package is not matched",
        not _belongs("src/quantx/persistence/a.py", "execution"),
    )

    measurements, problems = analyze(payload())
    check_case("valid fixture aggregates three packages", len(measurements) == 3 and not problems)
    check_case("valid fixture passes", _overall(measurements, problems) == PASS)

    measurements, problems = analyze(payload(domain=summary(2341, 2000, 1038, 775)))
    check_case("line floor breach fails", not problems and _overall(measurements, problems) == FAIL)

    measurements, problems = analyze(payload(execution=summary(3429, 3062, 1330, 500)))
    check_case(
        "branch floor breach fails",
        not problems and _overall(measurements, problems) == FAIL,
    )

    measurements, problems = analyze(payload(persistence=None))
    check_case(
        "missing package is unknown",
        bool(problems) and _overall(measurements, problems) == UNKNOWN,
    )

    measurements, problems = analyze(payload(domain=summary(2341, 3000, 1038, 775)))
    check_case("covered lines above statements is unknown", bool(problems))
    check_case("invalid totals do not report pass", _overall(measurements, problems) == UNKNOWN)

    measurements, problems = analyze(payload(domain=summary(0, 0, 1038, 775)))
    check_case("zero statements is unknown", bool(problems))

    measurements, problems = analyze(payload(domain=summary(2341, 2078, 0, 0)))
    check_case("zero branches is unknown", bool(problems))

    # ---- new-package bypass regression ------------------------------------
    measurements, problems = analyze(
        payload(
            extra_files={
                "src/quantx/newpkg/a.py": summary(100, 0, 50, 0),
            }
        )
    )
    check_case(
        "unknown quantx.newpkg fails closed",
        any("newpkg" in problem for problem in problems)
        and _overall(measurements, problems) == UNKNOWN,
    )

    # ---- missing measured package -----------------------------------------
    measurements, problems = analyze(
        {
            "meta": {"branch_coverage": True},
            "files": {
                "src/quantx/domain/a.py": summary(2341, 2078, 1038, 775),
                "src/quantx/execution/a.py": summary(3429, 3062, 1330, 1003),
            },
        }
    )
    check_case(
        "omitted persistence package is unknown",
        bool(problems) and _overall(measurements, problems) == UNKNOWN,
    )

    # ---- malformed coverage data ------------------------------------------
    measurements, problems = analyze(
        {
            "meta": {"branch_coverage": True},
            "files": {
                "src/quantx/domain/a.py": {"summary": "not-a-dict"},
            },
        }
    )
    check_case(
        "malformed summary is unknown",
        bool(problems) and _overall(measurements, problems) == UNKNOWN,
    )

    # ---- changed coverage scope (only 1 of 3 measured packages) -----------
    measurements, problems = analyze(
        {
            "meta": {"branch_coverage": True},
            "files": {
                "src/quantx/domain/a.py": summary(2341, 2078, 1038, 775),
            },
        }
    )
    check_case(
        "partial measured scope is unknown",
        bool(problems) and _overall(measurements, problems) == UNKNOWN,
    )

    temp = Path(tempfile.mkdtemp(prefix="qx-coverage-selftest-"))
    try:
        path = temp / "coverage.json"
        path.write_text(json.dumps(payload()), encoding="utf-8")
        files, problem = _read_coverage(path)
        check_case("valid coverage JSON loads", files is not None and not problem)
        assert files is not None
        measurements, problems = _aggregate(files)
        check_case(
            "loaded fixture passes",
            not problems and _overall(measurements, problems) == PASS,
        )

        path.write_text(json.dumps(payload(branch_coverage=False)), encoding="utf-8")
        files, problem = _read_coverage(path)
        check_case("missing branch proof is unknown", files is None and bool(problem))

        path.write_text("not json", encoding="utf-8")
        files, problem = _read_coverage(path)
        check_case("unreadable JSON is unknown", files is None and bool(problem))

        path.write_text(json.dumps({"meta": {"branch_coverage": True}}), encoding="utf-8")
        files, problem = _read_coverage(path)
        check_case("missing files object is unknown", files is None and bool(problem))
    finally:
        for child in temp.iterdir():
            child.unlink()
        temp.rmdir()

    if failures:
        print(f"SELF-TEST FAILED ({len(failures)}/{total} failing): {', '.join(failures)}")
        return 1
    print(f"SELF-TEST PASS: {total} checks")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QuantX package coverage floors")
    parser.add_argument("--repo", default=".", help="repository path (default: cwd)")
    parser.add_argument("--analyze", default=None, help="analyze an existing coverage JSON")
    parser.add_argument("--output", default=None, help="coverage JSON path")
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT, help="pytest timeout seconds"
    )
    parser.add_argument("--self-test", action="store_true", help="validate analysis behavior only")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    try:
        if args.analyze:
            return _analyze(Path(args.analyze))
        repo = Path(args.repo).resolve()
        output = _coverage_path(args.output)
        kind, exit_code, text = _run_pytest(repo, output, args.timeout)
        if kind != "completed":
            print(f"[{UNKNOWN}] coverage run did not complete ({kind})")
            if text:
                print(text[-4000:])
            print("OVERALL: UNKNOWN")
            return 2
        if exit_code != 0:
            print(text[-4000:])
            print(f"OVERALL: {FAIL}")
            print("coverage pytest exited nonzero; no floor verdict is claimed")
            return 1
        files, problem = _read_coverage(output)
        if files is None:
            print(f"[{UNKNOWN}] {problem}")
            print("OVERALL: UNKNOWN")
            return 2
        measurements, problems = _aggregate(files)
        if problems:
            for problem in problems:
                print(f"[{UNKNOWN}] {problem}")
            print("OVERALL: UNKNOWN")
            return 2
        return _report(measurements, _overall(measurements, problems))
    except Exception as exc:
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
