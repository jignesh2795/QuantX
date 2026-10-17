#!/usr/bin/env python3
"""Static trigger-asset evaluator for the QuantX skill library.

IMPORTANT: this is a static keyword-overlap proxy, not ground truth. It
verifies that the trigger-eval assets (evals/triggers.json) are coherent with
the skill descriptions: each should_trigger prompt must share at least
MIN_OVERLAP significant tokens with the owning skill's description, and each
should_not_trigger prompt must discriminate toward its declared belongs_to
skill. It does NOT measure real model routing behavior; run an evaluation
against the target model before making any routing claim.

The evaluator validates itself before reporting: the built-in self-test runs
first and a self-test failure refuses to produce a verdict.

Usage:
    python .opencode/skills/quantx-skills-maintainer/scripts/check_trigger_assets.py
    python ... check_trigger_assets.py --self-test

Exit codes: 0 = PASS, 1 = FAIL, 2 = UNKNOWN, 3 = internal/usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

ASSETS_SCHEMA = "quantx.trigger-eval.v1"
REPORT_SCHEMA = "quantx.trigger-eval-report.v1"
ASSETS_RELPATH = Path("quantx-skills-maintainer") / "evals" / "triggers.json"
EVIDENCE_DIR_NAME = "quantx-validation"

MIN_OVERLAP = 2
MIN_TRIGGER_CASES = 3
MIN_NOT_CASES = 2

STOPWORDS = {
    "when",
    "working",
    "quantx",
    "work",
    "with",
    "that",
    "this",
    "from",
    "into",
    "also",
    "your",
    "under",
    "uses",
    "used",
}

NON_CLAIMS = [
    "Static proxy only: this result verifies asset/description keyword coherence "
    "and discrimination, not real model routing behavior.",
    "A PASS does not prove the target model would select these skills correctly; "
    "run an evaluation with the actual model before claiming trigger accuracy.",
]

_WORD_RE = re.compile(r"[a-z0-9]+")
_FRONTMATTER_FIELD_RE = re.compile(r"^(name|description):[ \t]+(.+?)\s*$", re.MULTILINE)


def check(name: str, status: str, summary: str, notes: list[str] | None = None) -> dict:
    return {"name": name, "status": status, "summary": summary, "notes": notes or []}


def aggregate(checks: list[dict]) -> str:
    if any(item["status"] == FAIL for item in checks):
        return FAIL
    if any(item["status"] == UNKNOWN for item in checks):
        return UNKNOWN
    return PASS


def tokenize(text: str) -> set[str]:
    return {
        word for word in _WORD_RE.findall(text.lower()) if len(word) >= 4 and word not in STOPWORDS
    }


def overlap(a: str, b: str) -> int:
    return len(tokenize(a) & tokenize(b))


def parse_description(text: str) -> tuple[str | None, str]:
    if not text.startswith("---"):
        return None, "file must start with the YAML frontmatter delimiter '---'"
    end = text.find("\n---", 3)
    if end == -1:
        return None, "unterminated YAML frontmatter"
    block = text[3:end]
    for match in _FRONTMATTER_FIELD_RE.finditer(block):
        if match.group(1) == "description":
            value = match.group(2).strip()
            if value in {"", ">", "|", ">-", "|-"}:
                return None, "description must be a single-line value"
            return value, ""
    return None, "frontmatter missing 'description'"


def load_skill_descriptions(root: Path) -> tuple[dict[str, str], list[str]]:
    descriptions: dict[str, str] = {}
    problems: list[str] = []
    dirs = sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []
    if not dirs:
        problems.append(f"no skill directories found under {root}")
        return descriptions, problems
    for skill_dir in dirs:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            problems.append(f"{skill_dir.name}: no SKILL.md")
            continue
        description, problem = parse_description(skill_md.read_text(encoding="utf-8"))
        if description is None:
            problems.append(f"{skill_dir.name}: {problem}")
            continue
        descriptions[skill_dir.name] = description
    return descriptions, problems


def load_assets(path: Path) -> tuple[list | None, str]:
    if not path.is_file():
        return None, f"trigger-eval assets not found: {path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"trigger-eval assets are not readable JSON: {exc}"
    if not isinstance(payload, dict) or payload.get("schema") != ASSETS_SCHEMA:
        return None, "unrecognized trigger-eval assets schema"
    cases = payload.get("cases")
    if not isinstance(cases, list):
        return None, "assets 'cases' must be a list"
    return cases, ""


def evaluate_case(case: dict, descriptions: dict[str, str]) -> tuple[dict, list[str]]:
    notes: list[str] = []
    skill = case.get("skill")
    if not isinstance(skill, str) or skill not in descriptions:
        return check(
            "eval:<unknown>", FAIL, "case references an unknown skill", [repr(skill)]
        ), notes
    description = descriptions[skill]
    triggers = case.get("should_trigger")
    not_trigger = case.get("should_not_trigger")
    if not isinstance(triggers, list) or len(triggers) < MIN_TRIGGER_CASES:
        notes.append(f"should_trigger must list at least {MIN_TRIGGER_CASES} prompts")
        triggers = triggers if isinstance(triggers, list) else []
    if not isinstance(not_trigger, list) or len(not_trigger) < MIN_NOT_CASES:
        notes.append(f"should_not_trigger must list at least {MIN_NOT_CASES} prompts")
        not_trigger = not_trigger if isinstance(not_trigger, list) else []
    trigger_hits = 0
    for prompt in triggers:
        if not isinstance(prompt, str) or not prompt.strip():
            notes.append("should_trigger prompt must be a non-empty string")
            continue
        shared = overlap(prompt, description)
        if shared >= MIN_OVERLAP:
            trigger_hits += 1
        else:
            notes.append(
                f"should_trigger prompt shares only {shared} significant token(s) "
                f"with the description: {prompt!r}"
            )
    for entry in not_trigger:
        if isinstance(entry, str):
            text, target = entry, None
        elif isinstance(entry, dict):
            text, target = entry.get("text"), entry.get("belongs_to")
        else:
            notes.append("should_not_trigger entry must be a string or {text, belongs_to}")
            continue
        if not isinstance(text, str) or not text.strip():
            notes.append("should_not_trigger text must be a non-empty string")
            continue
        own = overlap(text, description)
        if target is not None:
            if not isinstance(target, str) or target not in descriptions:
                notes.append(f"belongs_to '{target}' is not a known skill")
                continue
            if target == skill:
                notes.append("belongs_to must differ from the owning skill")
                continue
            other = overlap(text, descriptions[target])
            if other <= own:
                notes.append(
                    f"non-trigger prompt does not discriminate toward {target} "
                    f"({other} vs {own}): {text!r}"
                )
        elif own >= MIN_OVERLAP:
            notes.append(f"non-trigger prompt overlaps the owning description ({own}): {text!r}")
    status = FAIL if notes else PASS
    summary = (
        f"{trigger_hits}/{len(triggers)} trigger prompts, {len(not_trigger)} non-trigger prompts"
    )
    return check(f"eval:{skill}", status, summary, notes), notes


def evaluate(skills_root: Path, assets_path: Path) -> dict:
    checks: list[dict] = []
    descriptions, problems = load_skill_descriptions(skills_root)
    if problems:
        checks.append(check("skill-descriptions", FAIL, "cannot read all descriptions", problems))
    cases, problem = load_assets(assets_path)
    if cases is None:
        checks.append(check("trigger-assets", UNKNOWN, "cannot evaluate assets", [problem]))
    else:
        case_skills: list[str] = []
        for case in cases:
            if not isinstance(case, dict):
                checks.append(
                    check("eval:<malformed>", FAIL, "case must be an object", [repr(case)])
                )
                continue
            result, _ = evaluate_case(case, descriptions)
            checks.append(result)
            skill = case.get("skill")
            if isinstance(skill, str):
                if skill in case_skills:
                    checks.append(check(f"eval:{skill}", FAIL, "duplicate case for skill", []))
                case_skills.append(skill)
        missing = sorted(set(descriptions) - set(case_skills))
        if missing:
            checks.append(check("assets-coverage", FAIL, "skills without eval cases", missing))
        else:
            checks.append(
                check(
                    "assets-coverage",
                    PASS,
                    f"all {len(descriptions)} skills have eval cases",
                )
            )
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "skills_dir": str(skills_root),
        "assets": str(assets_path),
        "checks": checks,
        "non_claims": NON_CLAIMS,
        "overall": aggregate(checks),
    }


def print_report(report: dict) -> None:
    print(f"QuantX trigger-asset evaluation (static proxy)  {report['assets']}")
    for item in report["checks"]:
        print(f"[{item['status']}] {item['name']}  {item['summary']}")
        for note in item["notes"]:
            print(f"    note: {note}")
    print(f"OVERALL: {report['overall']}")
    for line in NON_CLAIMS:
        print(f"non-claim: {line}")


def _write_fixture(root: Path, description: str) -> None:
    (root / "SKILL.md").write_text(
        f"---\nname: {root.name}\ndescription: {description}\n---\n\n# {root.name}\n",
        encoding="utf-8",
    )


def _fixture_assets() -> dict:
    alpha = (
        "Use when handling alpha widgets and delta processing — alpha metrics, "
        "delta calibration, threshold review. Keywords: alpha, delta, fixture."
    )
    beta = (
        "Use when handling beta omicron zodiac epsilon items — beta catalog, "
        "zodiac alignment. Keywords: beta, omicron, zodiac, epsilon."
    )
    return alpha, beta


def _fixture_cases() -> list:
    return [
        {
            "skill": "quantx-fixture-alpha",
            "should_trigger": [
                "review the alpha metrics and calibrate the delta processing",
                "check the delta calibration threshold for this fixture",
                "alpha widget threshold review needed",
            ],
            "should_not_trigger": [
                {"text": "beta gamma omicron zodiac", "belongs_to": "quantx-fixture-beta"},
                {"text": "epsilon sigma tau upsilon", "belongs_to": "quantx-fixture-beta"},
            ],
        },
        {
            "skill": "quantx-fixture-beta",
            "should_trigger": [
                "align the zodiac catalog for the omicron beta items",
                "review beta catalog and zodiac alignment",
                "check the epsilon zodiac catalog",
            ],
            "should_not_trigger": [
                {"text": "alpha delta threshold", "belongs_to": "quantx-fixture-alpha"},
                {"text": "alpha widget calibration", "belongs_to": "quantx-fixture-alpha"},
            ],
        },
    ]


def _build_fixture(tmp: Path) -> tuple[Path, Path]:
    skills = tmp / "skills"
    alpha_desc, beta_desc = _fixture_assets()
    (skills / "quantx-fixture-alpha").mkdir(parents=True)
    (skills / "quantx-fixture-beta").mkdir(parents=True)
    _write_fixture(skills / "quantx-fixture-alpha", alpha_desc)
    _write_fixture(skills / "quantx-fixture-beta", beta_desc)
    assets = tmp / "triggers.json"
    assets.write_text(
        json.dumps({"schema": ASSETS_SCHEMA, "cases": _fixture_cases()}), encoding="utf-8"
    )
    return skills, assets


def self_test() -> int:
    failures: list[str] = []
    total = 0

    def check_case(name: str, condition: bool) -> None:
        nonlocal total
        total += 1
        if not condition:
            failures.append(name)

    tmp = Path(tempfile.mkdtemp(prefix="qx-trigger-selftest-"))
    try:
        skills, assets = _build_fixture(tmp)
        check_case("valid fixture PASSes", evaluate(skills, assets)["overall"] == PASS)

        cases = _fixture_cases()
        cases[0]["should_trigger"][0] = "totally unrelated vocabulary here"
        broken = tmp / "weak-trigger.json"
        broken.write_text(json.dumps({"schema": ASSETS_SCHEMA, "cases": cases}), encoding="utf-8")
        check_case("weak trigger prompt FAILs", evaluate(skills, broken)["overall"] == FAIL)

        cases = _fixture_cases()
        cases[0]["should_not_trigger"][0] = {
            "text": "alpha delta threshold review",
            "belongs_to": "quantx-fixture-beta",
        }
        confused = tmp / "confused.json"
        confused.write_text(json.dumps({"schema": ASSETS_SCHEMA, "cases": cases}), encoding="utf-8")
        check_case("bad discrimination FAILs", evaluate(skills, confused)["overall"] == FAIL)

        cases = _fixture_cases()[:1]
        missing = tmp / "missing-skill.json"
        missing.write_text(json.dumps({"schema": ASSETS_SCHEMA, "cases": cases}), encoding="utf-8")
        check_case("missing skill case FAILs", evaluate(skills, missing)["overall"] == FAIL)

        cases = _fixture_cases()
        cases[0]["skill"] = "quantx-fixture-ghost"
        ghost = tmp / "unknown-skill.json"
        ghost.write_text(json.dumps({"schema": ASSETS_SCHEMA, "cases": cases}), encoding="utf-8")
        check_case("unknown skill FAILs", evaluate(skills, ghost)["overall"] == FAIL)

        cases = _fixture_cases()
        cases[0]["should_not_trigger"][0] = {
            "text": "beta gamma omicron zodiac",
            "belongs_to": "quantx-fixture-alpha",
        }
        self_ref = tmp / "self-ref.json"
        self_ref.write_text(json.dumps({"schema": ASSETS_SCHEMA, "cases": cases}), encoding="utf-8")
        check_case("belongs_to self FAILs", evaluate(skills, self_ref)["overall"] == FAIL)

        missing_assets = tmp / "no-assets.json"
        check_case(
            "missing assets file is UNKNOWN",
            evaluate(skills, missing_assets)["overall"] == UNKNOWN,
        )

        wrong_schema = tmp / "wrong-schema.json"
        wrong_schema.write_text(json.dumps({"schema": "other", "cases": []}), encoding="utf-8")
        check_case(
            "wrong assets schema is UNKNOWN",
            evaluate(skills, wrong_schema)["overall"] == UNKNOWN,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print(f"SELF-TEST FAILED ({len(failures)}/{total} failing): {', '.join(failures)}")
        return 1
    print(f"SELF-TEST PASS: {total} checks")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QuantX static trigger-asset evaluator")
    parser.add_argument(
        "--skills-dir", default=".opencode/skills", help="skills root (default: .opencode/skills)"
    )
    parser.add_argument("--self-test", action="store_true", help="validate evaluator behavior only")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    try:
        status = self_test()
        if status != 0:
            print("evaluator self-test failed; refusing to report results", file=sys.stderr)
            return 3
        root = Path(args.skills_dir).resolve()
        report = evaluate(root, root / ASSETS_RELPATH)
        print_report(report)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        evidence = Path(tempfile.gettempdir()) / EVIDENCE_DIR_NAME / f"trigger-eval-{stamp}.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"evidence: {evidence}")
        return 0 if report["overall"] == PASS else (1 if report["overall"] == FAIL else 2)
    except Exception as exc:
        # Top-level guard: report the failure honestly; never attempt a fix.
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
