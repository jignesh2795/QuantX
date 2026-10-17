#!/usr/bin/env python3
"""QuantX release gate: bind validation evidence to the exact merge candidate.

Consumes the machine-readable evidence produced by the validation gate
(`quantx-validation-gate/scripts/run_validation.py`), verifies that it was
produced in this repository, belongs to the current HEAD, and satisfies the
mandatory check contract of the `quantx.validation-evidence.v1` schema: every
check record emitted by the validation gate (pytest, ruff-check, ruff-format,
mypy, git-diff-check, worktree-integrity) must be present exactly once as a
well-formed record, and the overall verdict is recomputed from those records
and never trusted as a summary field. Recomputing verifies internal
consistency only; it does not prove the evidence was genuinely produced by a
test run. Checks tracked-worktree cleanliness and diff-range whitespace, and
reports PASS / FAIL / UNKNOWN (fail-closed).

This script authorizes nothing by itself and never modifies the repository.
It does not fix, retry, or re-run validation; missing, incomplete, or
mismatched evidence is never reported as PASS.

Usage:
    python .opencode/skills/quantx-release-gate/scripts/release_check.py
    python ... release_check.py --evidence <validation-json> --expected-head <sha>
    python ... release_check.py --self-test

Exit codes: 0 = PASS, 1 = FAIL, 2 = UNKNOWN, 3 = usage/internal error.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

SCHEMA = "quantx.release-gate.v1"
EVIDENCE_SCHEMA = "quantx.validation-evidence.v1"
EVIDENCE_DIR_NAME = "quantx-validation"

MANDATORY_CHECKS: tuple[str, ...] = (
    "pytest",
    "ruff-check",
    "ruff-format",
    "mypy",
    "git-diff-check",
    "worktree-integrity",
)

CHECK_RECORD_FIELDS: tuple[str, ...] = (
    "name",
    "argv",
    "status",
    "exit_code",
    "duration_s",
    "summary",
    "notes",
    "output_tail",
)

NON_CLAIMS = [
    "PASS confirms: complete, internally consistent validation evidence for this repository and "
    "this exact HEAD, with every mandatory check (pytest, ruff-check, ruff-format, mypy, "
    "git-diff-check, worktree-integrity) present exactly once and reporting PASS; the tracked "
    "worktree is clean, and the diff range has no whitespace errors.",
    "PASS does NOT authenticate the evidence: it is an editable local JSON file, and recomputation "
    "verifies internal consistency only, not that the checks were truly executed. This schema has "
    "no cryptographic or trusted-runner attestation.",
    "PASS does NOT prove: production readiness, broker correctness, LIVE trading safety, "
    "or that GitHub Actions executed.",
]


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
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


def find_latest_evidence() -> Path | None:
    directory = Path(tempfile.gettempdir()) / EVIDENCE_DIR_NAME
    if not directory.is_dir():
        return None
    candidates = sorted(
        directory.glob("validation-*.json"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    return candidates[0] if candidates else None


def check(name: str, status: str, summary: str, notes: list[str] | None = None) -> dict:
    return {"name": name, "status": status, "summary": summary, "notes": notes or []}


def normalized_path(value: str) -> str:
    return os.path.normcase(os.path.realpath(value))


def check_record_problems(index: int, entry: object) -> list[str]:
    """Validate one evidence check record against the run_validation.py contract."""
    if not isinstance(entry, dict):
        return [f"check #{index} is not an object"]
    name = entry.get("name")
    label = name if isinstance(name, str) and name else f"#{index}"
    problems: list[str] = []
    for field_name in CHECK_RECORD_FIELDS:
        if field_name not in entry:
            problems.append(f"check {label!r} is missing field {field_name!r}")
    if not isinstance(name, str) or not name:
        problems.append(f"check {label!r} has an empty or non-string name")
    if entry.get("status") not in (PASS, FAIL, UNKNOWN):
        problems.append(f"check {label!r} has unsupported status {entry.get('status')!r}")
    if not isinstance(entry.get("summary"), str):
        problems.append(f"check {label!r} has a non-string summary")
    notes = entry.get("notes")
    if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
        problems.append(f"check {label!r} has malformed notes")
    argv = entry.get("argv")
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        problems.append(f"check {label!r} has malformed argv")
    exit_code = entry.get("exit_code")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int | None):
        problems.append(f"check {label!r} has a malformed exit_code")
    duration = entry.get("duration_s")
    if isinstance(duration, bool) or not isinstance(duration, int | float | None):
        problems.append(f"check {label!r} has a malformed duration_s")
    if not isinstance(entry.get("output_tail"), str):
        problems.append(f"check {label!r} has a non-string output_tail")
    return problems


def load_evidence(path: Path | None) -> tuple[dict | None, str]:
    """Return (evidence, problem); problem is empty when loaded and recognized."""
    if path is None:
        return None, "no validation evidence file found"
    if not path.is_file():
        return None, f"evidence file does not exist: {path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"evidence is not readable JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "evidence JSON is not an object"
    if payload.get("schema") != EVIDENCE_SCHEMA:
        return None, f"unrecognized evidence schema: {payload.get('schema')!r}"
    return payload, ""


def classify_range_whitespace(proc: subprocess.CompletedProcess[str] | None) -> dict:
    if proc is None:
        return check("range-whitespace", UNKNOWN, "git unavailable")
    if proc.returncode == 0:
        return check("range-whitespace", PASS, "no whitespace errors in range")
    output = (proc.stdout or "") + (proc.stderr or "")
    if output.strip() and "fatal:" not in output:
        return check(
            "range-whitespace",
            FAIL,
            "whitespace errors in committed range",
            [line for line in output.splitlines() if line.strip()][:10],
        )
    return check("range-whitespace", UNKNOWN, "git diff --check failed without findings")


def evaluate(
    repo: Path,
    evidence_path: Path | None,
    expected_head: str | None,
    base: str,
) -> dict:
    checks: list[dict] = []
    head = resolve_head(repo)

    evidence, problem = load_evidence(evidence_path)
    if evidence is None:
        checks.append(
            check("evidence-present", UNKNOWN, "missing or unreadable evidence", [problem])
        )
    else:
        checks.append(
            check(
                "evidence-present",
                PASS,
                f"validation evidence loaded (overall={evidence.get('overall')!r})",
            )
        )
        raw_checks = evidence.get("checks")
        reported = evidence.get("overall")
        statuses: dict[str, str] = {}
        integrity_problems: list[str] = []
        if not isinstance(raw_checks, list) or not raw_checks:
            integrity_problems.append("evidence has no checks list to verify")
        else:
            for index, entry in enumerate(raw_checks):
                problems = check_record_problems(index, entry)
                if problems:
                    integrity_problems.extend(problems)
                    continue
                name = entry["name"]
                if name not in MANDATORY_CHECKS:
                    integrity_problems.append(f"check {name!r} is not part of the current schema")
                elif name in statuses:
                    integrity_problems.append(f"mandatory check {name!r} is duplicated")
                else:
                    statuses[name] = entry["status"]
            for name in MANDATORY_CHECKS:
                if name not in statuses:
                    integrity_problems.append(f"mandatory check {name!r} is missing")
        recomputed: str | None = None
        if not integrity_problems:
            values = list(statuses.values())
            if FAIL in values:
                recomputed = FAIL
            elif UNKNOWN in values:
                recomputed = UNKNOWN
            else:
                recomputed = PASS
            if recomputed != reported:
                integrity_problems.append(
                    f"reported overall {reported!r} does not match recomputed "
                    f"{recomputed!r} from {len(values)} mandatory checks"
                )
        if integrity_problems:
            checks.append(
                check(
                    "evidence-integrity",
                    FAIL,
                    "evidence does not satisfy the mandatory check contract",
                    integrity_problems[:12],
                )
            )
            checks.append(
                check("evidence-overall", FAIL, "validation overall could not be verified")
            )
        else:
            checks.append(
                check(
                    "evidence-integrity",
                    PASS,
                    "all mandatory checks present exactly once; recomputed overall "
                    f"{recomputed} matches reported",
                )
            )
            if recomputed == PASS:
                checks.append(check("evidence-overall", PASS, "validation overall is PASS"))
            elif recomputed == UNKNOWN:
                checks.append(
                    check(
                        "evidence-overall",
                        UNKNOWN,
                        "validation overall is UNKNOWN; release gate cannot conclude",
                    )
                )
            else:
                checks.append(check("evidence-overall", FAIL, "validation overall is FAIL"))
        evidence_repo = evidence.get("repo")
        if not isinstance(evidence_repo, str) or not evidence_repo:
            checks.append(
                check(
                    "evidence-repo-binding",
                    FAIL,
                    "evidence does not record which repository it belongs to",
                )
            )
        elif normalized_path(evidence_repo) == normalized_path(str(repo)):
            checks.append(
                check("evidence-repo-binding", PASS, "evidence belongs to this repository")
            )
        else:
            checks.append(
                check(
                    "evidence-repo-binding",
                    FAIL,
                    "evidence belongs to a different repository path",
                    [f"evidence repo {evidence_repo}; this repo {repo}"],
                )
            )
        if head is None:
            checks.append(check("evidence-head-binding", UNKNOWN, "cannot resolve repository HEAD"))
        elif evidence.get("head_sha") == head:
            checks.append(check("evidence-head-binding", PASS, f"evidence bound to {head[:12]}"))
        else:
            checks.append(
                check(
                    "evidence-head-binding",
                    FAIL,
                    "evidence belongs to a different commit",
                    [f"evidence HEAD {evidence.get('head_sha')}; repository HEAD {head}"],
                )
            )

    if expected_head is not None:
        if head is None:
            checks.append(check("expected-head", UNKNOWN, "cannot resolve repository HEAD"))
        elif head == expected_head:
            checks.append(
                check("expected-head", PASS, f"HEAD matches requested {expected_head[:12]}")
            )
        else:
            checks.append(
                check(
                    "expected-head",
                    FAIL,
                    "repository HEAD does not match the requested SHA",
                    [f"requested {expected_head}; repository {head}"],
                )
            )

    proc = git(repo, "status", "--porcelain", "--untracked-files=no")
    if proc is None or proc.returncode != 0:
        checks.append(check("tracked-worktree-clean", UNKNOWN, "git status failed"))
    elif proc.stdout.strip():
        tracked = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        checks.append(
            check(
                "tracked-worktree-clean",
                FAIL,
                "tracked modifications present; evidence does not cover them",
                tracked[:10],
            )
        )
    else:
        checks.append(check("tracked-worktree-clean", PASS, "no tracked modifications"))

    if resolve_rev(repo, base):
        ws = classify_range_whitespace(git(repo, "diff", "--check", f"{base}...HEAD"))
        checks.append(ws)
        scope_proc = git(repo, "diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD")
        if scope_proc is not None and scope_proc.returncode == 0:
            scope = [line.strip() for line in scope_proc.stdout.splitlines() if line.strip()]
            checks.append(check("changed-scope", PASS, f"{len(scope)} file(s) vs {base}"))
            scope_list = scope
        else:
            checks.append(check("changed-scope", UNKNOWN, "cannot list changed files"))
            scope_list = []
    else:
        checks.append(
            check(
                "range-whitespace",
                UNKNOWN,
                f"cannot resolve base rev '{base}'; range evidence unknown",
            )
        )
        checks.append(check("changed-scope", UNKNOWN, f"cannot resolve base rev '{base}'"))
        scope_list = []

    if any(item["status"] == FAIL for item in checks):
        overall = FAIL
    elif any(item["status"] == UNKNOWN for item in checks):
        overall = UNKNOWN
    else:
        overall = PASS

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "repo": str(repo),
        "head_sha": head,
        "expected_head": expected_head,
        "base_rev": base,
        "evidence_path": str(evidence_path) if evidence_path else None,
        "evidence_head_sha": evidence.get("head_sha") if evidence else None,
        "checks": checks,
        "scope": scope_list,
        "non_claims": NON_CLAIMS,
        "overall": overall,
    }


def print_report(report: dict) -> None:
    print(f"QuantX release gate  HEAD={report['head_sha']}  base={report['base_rev']}")
    if report["evidence_path"]:
        print(f"evidence: {report['evidence_path']}")
    for item in report["checks"]:
        print(f"[{item['status']}] {item['name']}  {item['summary']}")
        for note in item["notes"]:
            print(f"    note: {note}")
    if report["scope"]:
        print("changed scope:")
        for path in report["scope"]:
            print(f"    {path}")
    print(f"OVERALL: {report['overall']}")
    for line in NON_CLAIMS:
        print(f"non-claim: {line}")
    if report["overall"] == PASS:
        print(f"merge-candidate HEAD: {report['head_sha']}")


def write_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def self_test() -> int:
    failures: list[str] = []
    total = 0

    def check_case(name: str, condition: bool) -> None:
        nonlocal total
        total += 1
        if not condition:
            failures.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="qx-release-selftest-"))
    try:
        init = git(tmp, "init", "-q")
        if init is None or init.returncode != 0:
            print("SELF-TEST FAILED: git init failed")
            return 1
        sample = tmp / "sample.py"
        sample.write_text("VALUE = 1\n", encoding="utf-8")
        git(tmp, "add", "sample.py")
        commit = git(
            tmp,
            "-c",
            "user.name=QuantX SelfTest",
            "-c",
            "user.email=selftest@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-q",
            "-m",
            "init",
        )
        if commit is None or commit.returncode != 0:
            print("SELF-TEST FAILED: git commit failed")
            return 1
        head = resolve_head(tmp)
        check_case("head resolved", head is not None)
        assert head is not None

        def record(name: str, status: str, summary: str = "") -> dict:
            return {
                "name": name,
                "argv": ["fixture"],
                "status": status,
                "exit_code": 0 if status == PASS else None,
                "duration_s": 0.1,
                "summary": summary,
                "notes": [],
                "output_tail": "",
            }

        def payload(**overrides: object) -> dict:
            data: dict = {
                "schema": EVIDENCE_SCHEMA,
                "overall": PASS,
                "head_sha": head,
                "repo": str(tmp),
                "checks": [record(name, PASS, "fixture pass") for name in MANDATORY_CHECKS],
            }
            data.update(overrides)
            return data

        def write_case(filename: str, data: dict) -> Path:
            path = tmp / filename
            path.write_text(json.dumps(data), encoding="utf-8")
            return path

        valid = write_case("valid.json", payload())
        report = evaluate(tmp, valid, None, head)
        check_case("complete mandatory inventory passes", report["overall"] == PASS)

        single = write_case(
            "single-check.json", payload(checks=[record("pytest", PASS, "2045 passed")])
        )
        report = evaluate(tmp, single, None, head)
        check_case("single-check evidence fails", report["overall"] == FAIL)

        for missing in MANDATORY_CHECKS:
            partial = [record(name, PASS) for name in MANDATORY_CHECKS if name != missing]
            path = write_case(f"missing-{missing}.json", payload(checks=partial))
            report = evaluate(tmp, path, None, head)
            check_case(f"omitted {missing} fails", report["overall"] == FAIL)

        duplicated = [record(name, PASS) for name in MANDATORY_CHECKS] + [record("pytest", PASS)]
        path = write_case("duplicated.json", payload(checks=duplicated))
        report = evaluate(tmp, path, None, head)
        check_case("duplicate mandatory check fails", report["overall"] == FAIL)

        swapped = [record(name, PASS) for name in MANDATORY_CHECKS if name != "ruff-format"]
        swapped.append(record("deploy-check", PASS))
        path = write_case("unsupported-name.json", payload(checks=swapped))
        report = evaluate(tmp, path, None, head)
        check_case("unsupported check name fails", report["overall"] == FAIL)

        malformed_cases: list[tuple[str, dict]] = []
        empty_name = [record(name, PASS) for name in MANDATORY_CHECKS]
        empty_name[0]["name"] = ""
        malformed_cases.append(("empty check name fails", payload(checks=empty_name)))
        non_string_name = [record(name, PASS) for name in MANDATORY_CHECKS]
        non_string_name[0]["name"] = 42
        malformed_cases.append(("non-string check name fails", payload(checks=non_string_name)))
        non_object = [record(name, PASS) for name in MANDATORY_CHECKS]
        non_object[0] = "pytest"
        malformed_cases.append(("non-object check record fails", payload(checks=non_object)))
        bad_status = [record(name, PASS) for name in MANDATORY_CHECKS]
        bad_status[0]["status"] = "OK"
        malformed_cases.append(("unsupported check status fails", payload(checks=bad_status)))
        missing_field = [record(name, PASS) for name in MANDATORY_CHECKS]
        del missing_field[0]["summary"]
        malformed_cases.append(("missing record field fails", payload(checks=missing_field)))
        bad_field_type = [record(name, PASS) for name in MANDATORY_CHECKS]
        bad_field_type[0]["notes"] = "none"
        malformed_cases.append(("malformed record field fails", payload(checks=bad_field_type)))
        for case_name, data in malformed_cases:
            path = write_case("malformed-case.json", data)
            report = evaluate(tmp, path, None, head)
            check_case(case_name, report["overall"] == FAIL)

        failed_checks = [record(name, PASS) for name in MANDATORY_CHECKS]
        failed_checks[0] = record("pytest", FAIL, "3 failed")
        path = write_case("failed-check.json", payload(overall=FAIL, checks=failed_checks))
        report = evaluate(tmp, path, None, head)
        check_case("consistent FAIL evidence fails", report["overall"] == FAIL)

        unknown_checks = [record(name, PASS) for name in MANDATORY_CHECKS]
        unknown_checks[3] = record("mypy", UNKNOWN, "tool missing")
        path = write_case("unknown-check.json", payload(overall=UNKNOWN, checks=unknown_checks))
        report = evaluate(tmp, path, None, head)
        check_case("consistent UNKNOWN evidence is UNKNOWN", report["overall"] == UNKNOWN)

        unknown_reported_pass = [record(name, PASS) for name in MANDATORY_CHECKS]
        unknown_reported_pass[3] = record("mypy", UNKNOWN)
        path = write_case("unknown-reported-pass.json", payload(checks=unknown_reported_pass))
        report = evaluate(tmp, path, None, head)
        check_case("UNKNOWN check behind PASS summary fails", report["overall"] == FAIL)

        tampered = [record(name, PASS) for name in MANDATORY_CHECKS]
        tampered[0] = record("pytest", FAIL)
        path = write_case("tampered.json", payload(checks=tampered))
        report = evaluate(tmp, path, None, head)
        check_case("tampered overall summary fails", report["overall"] == FAIL)

        path = write_case("empty-checks.json", payload(checks=[]))
        report = evaluate(tmp, path, None, head)
        check_case("evidence without checks fails", report["overall"] == FAIL)

        path = write_case("foreign-repo.json", payload(repo=str(tmp) + "-elsewhere"))
        report = evaluate(tmp, path, None, head)
        check_case("foreign-repo evidence fails", report["overall"] == FAIL)

        path = write_case("other-head.json", payload(head_sha="0" * 40))
        report = evaluate(tmp, path, None, head)
        check_case("head mismatch fails", report["overall"] == FAIL)

        sample.write_text("VALUE = 2\n", encoding="utf-8")
        report = evaluate(tmp, valid, None, head)
        check_case("tracked modification fails", report["overall"] == FAIL)
        git(tmp, "checkout", "--", "sample.py")

        report = evaluate(tmp, tmp / "missing.json", None, head)
        check_case("missing evidence is UNKNOWN", report["overall"] == UNKNOWN)

        broken = tmp / "broken.json"
        broken.write_text("not json", encoding="utf-8")
        report = evaluate(tmp, broken, None, head)
        check_case("unparseable evidence is UNKNOWN", report["overall"] == UNKNOWN)

        wrong_schema = tmp / "wrong-schema.json"
        wrong_schema.write_text(json.dumps({"schema": "other", "overall": PASS}), encoding="utf-8")
        report = evaluate(tmp, wrong_schema, None, head)
        check_case("wrong schema is UNKNOWN", report["overall"] == UNKNOWN)

        report = evaluate(tmp, valid, "1" * 40, head)
        check_case("expected-head mismatch fails", report["overall"] == FAIL)

        report = evaluate(tmp, valid, None, "no-such-rev")
        check_case("unresolvable base is UNKNOWN", report["overall"] == UNKNOWN)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print(f"SELF-TEST FAILED ({len(failures)}/{total} failing): {', '.join(failures)}")
        return 1
    print(f"SELF-TEST PASS: {total} checks")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QuantX release gate (read-only)")
    parser.add_argument("--repo", default=".", help="repository path (default: cwd)")
    parser.add_argument("--base", default="origin/main", help="diff range base rev")
    parser.add_argument("--expected-head", default=None, help="required exact merge-candidate SHA")
    parser.add_argument("--evidence", default=None, help="validation evidence JSON path")
    parser.add_argument("--output", default=None, help="report JSON path (default: temp dir)")
    parser.add_argument("--self-test", action="store_true", help="validate evaluator behavior only")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()

    try:
        repo = Path(args.repo).resolve()
        evidence_path = Path(args.evidence) if args.evidence else find_latest_evidence()
        report = evaluate(repo, evidence_path, args.expected_head, args.base)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        head = report["head_sha"] or "unknown"
        output = (
            Path(args.output)
            if args.output
            else (
                Path(tempfile.gettempdir())
                / EVIDENCE_DIR_NAME
                / f"release-{head[:12]}-{stamp}.json"
            )
        )
        write_report(report, output)
        print_report(report)
        print(f"report: {output}")
        return 0 if report["overall"] == PASS else (1 if report["overall"] == FAIL else 2)
    except Exception as exc:
        # Top-level guard: report the failure honestly; never attempt a fix.
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
