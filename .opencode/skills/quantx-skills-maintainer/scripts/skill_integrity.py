#!/usr/bin/env python3
"""QuantX skills integrity validator.

Validates the opencode skill library (.opencode/skills): SKILL.md frontmatter
contract, directory/name consistency, unique names, description budget, and a
SHA-256 manifest of every skill file (fail-closed).

Manifest hashes normalize CRLF to LF before hashing, because the repository
has no .gitattributes and Windows checkouts use core.autocrlf=true; byte
identity is otherwise checkout-dependent.

Usage:
    python .opencode/skills/quantx-skills-maintainer/scripts/skill_integrity.py --check
    python ... skill_integrity.py --update        # regenerate skills.lock.json
    python ... skill_integrity.py --self-test

Exit codes: 0 = PASS, 1 = FAIL, 2 = UNKNOWN, 3 = usage/internal error.
"""

from __future__ import annotations

import argparse
import hashlib
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

MANIFEST_NAME = "skills.lock.json"
SCHEMA = "quantx.skills-manifest.v1"
REPORT_SCHEMA = "quantx.skills-integrity.v1"
MAX_DESCRIPTION = 1024
EVIDENCE_DIR_NAME = "quantx-validation"

_FRONTMATTER_FIELD_RE = re.compile(r"^(name|description):[ \t]+(.+?)\s*$", re.MULTILINE)
_MULTILINE_SCALARS = {"", ">", "|", ">-", "|-", ">+", "|+"}


def check(name: str, status: str, summary: str, notes: list[str] | None = None) -> dict:
    return {"name": name, "status": status, "summary": summary, "notes": notes or []}


def aggregate(checks: list[dict]) -> str:
    if any(item["status"] == FAIL for item in checks):
        return FAIL
    if any(item["status"] == UNKNOWN for item in checks):
        return UNKNOWN
    return PASS


def normalized_sha256(path: Path) -> str:
    """SHA-256 over file bytes with CRLF normalized to LF (checkout-independent)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk.replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if "__pycache__" in rel_parts or path.suffix == ".pyc":
            continue
        if path.name == MANIFEST_NAME:
            continue
        files.append(path)
    return files


def manifest_key(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, "file must start with the YAML frontmatter delimiter '---'"
    end = text.find("\n---", 3)
    if end == -1:
        return {}, "unterminated YAML frontmatter"
    block = text[3:end]
    fields: dict[str, str] = {}
    for match in _FRONTMATTER_FIELD_RE.finditer(block):
        key, value = match.group(1), match.group(2).strip()
        if key in fields:
            return {}, f"duplicate frontmatter field '{key}'"
        fields[key] = value
    if "name" not in fields:
        return {}, "frontmatter missing 'name'"
    if "description" not in fields:
        return {}, "frontmatter missing 'description'"
    if fields["description"] in _MULTILINE_SCALARS:
        return {}, "description must be a single-line value"
    return fields, ""


def validate_skills(root: Path) -> list[dict]:
    results: list[dict] = []
    seen: dict[str, str] = {}
    dirs = sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []
    if not dirs:
        results.append(check("skills-present", FAIL, "no skill directories found", [str(root)]))
        return results
    for skill_dir in dirs:
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            results.append(check("skill:" + skill_dir.name, FAIL, "directory has no SKILL.md"))
            continue
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError as exc:
            results.append(check("skill:" + skill_dir.name, FAIL, f"unreadable: {exc}"))
            continue
        fields, problem = parse_frontmatter(text)
        if problem:
            results.append(check("skill:" + skill_dir.name, FAIL, problem))
            continue
        notes: list[str] = []
        status = PASS
        if fields["name"] != skill_dir.name:
            status = FAIL
            notes.append(
                f"frontmatter name '{fields['name']}' does not match directory '{skill_dir.name}'"
            )
        if len(fields["description"]) > MAX_DESCRIPTION:
            status = FAIL
            notes.append(
                f"description is {len(fields['description'])} chars (max {MAX_DESCRIPTION})"
            )
        if fields["name"] in seen:
            status = FAIL
            notes.append(f"duplicate skill name, also declared in '{seen[fields['name']]}'")
        else:
            seen[fields["name"]] = skill_dir.name
        results.append(check("skill:" + skill_dir.name, status, "frontmatter valid", notes))
    return results


def load_manifest(path: Path) -> tuple[dict[str, str] | None, str]:
    if not path.is_file():
        return None, f"manifest not found: {path} (run --update)"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"manifest is not readable JSON: {exc}"
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        schema = payload.get("schema") if isinstance(payload, dict) else type(payload).__name__
        return None, f"unrecognized manifest schema: {schema!r}"
    files = payload.get("files")
    if not isinstance(files, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in files.items()
    ):
        return None, "manifest 'files' must map relative paths to hex digests"
    return files, ""


def check_manifest(root: Path, manifest: dict[str, str]) -> list[dict]:
    on_disk = {manifest_key(root, path): normalized_sha256(path) for path in iter_files(root)}
    missing = sorted(set(manifest) - set(on_disk))
    extra = sorted(set(on_disk) - set(manifest))
    modified = sorted(key for key in set(on_disk) & set(manifest) if on_disk[key] != manifest[key])
    checks: list[dict] = []
    if missing:
        checks.append(
            check(
                "manifest-missing-files",
                FAIL,
                "entries present in manifest but absent on disk",
                missing[:10],
            )
        )
    if extra:
        checks.append(
            check(
                "manifest-unlisted-files",
                FAIL,
                "files on disk that the manifest does not cover (stale manifest)",
                extra[:10],
            )
        )
    if modified:
        checks.append(
            check(
                "manifest-modified-files",
                FAIL,
                "files whose content differs from the manifest",
                modified[:10],
            )
        )
    if not checks:
        checks.append(check("manifest", PASS, f"all {len(on_disk)} skill files match the manifest"))
    return checks


def evaluate(root: Path) -> dict:
    checks = validate_skills(root)
    manifest, problem = load_manifest(root / MANIFEST_NAME)
    if manifest is None:
        checks.append(check("manifest", UNKNOWN, "file integrity cannot be verified", [problem]))
    else:
        checks.extend(check_manifest(root, manifest))
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "skills_dir": str(root),
        "checks": checks,
        "overall": aggregate(checks),
    }


def build_manifest(root: Path) -> dict:
    files = {manifest_key(root, path): normalized_sha256(path) for path in iter_files(root)}
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": dict(sorted(files.items())),
    }


def run_update(root: Path) -> int:
    checks = validate_skills(root)
    if any(item["status"] == FAIL for item in checks):
        for item in checks:
            if item["status"] == FAIL:
                print(f"[{FAIL}] {item['name']}  {item['summary']}")
                for note in item["notes"]:
                    print(f"    note: {note}")
        print("manifest not written: fix frontmatter failures first")
        return 1
    manifest = build_manifest(root)
    target = root / MANIFEST_NAME
    target.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[PASS] manifest written: {target} ({len(manifest['files'])} files)")
    return 0


def print_report(report: dict) -> None:
    print(f"QuantX skills integrity  {report['skills_dir']}")
    for item in report["checks"]:
        print(f"[{item['status']}] {item['name']}  {item['summary']}")
        for note in item["notes"]:
            print(f"    note: {note}")
    print(f"OVERALL: {report['overall']}")


def self_test() -> int:
    failures: list[str] = []
    total = 0

    def check_case(name: str, condition: bool) -> None:
        nonlocal total
        total += 1
        if not condition:
            failures.append(name)

    def write_skill(root: Path, name: str) -> None:
        skill_dir = root / name
        (skill_dir / "references").mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Use when testing the integrity validator.\n"
            f"---\n\n# {name}\n",
            encoding="utf-8",
        )
        (skill_dir / "references" / "notes.md").write_text("notes\n", encoding="utf-8")

    tmp = Path(tempfile.mkdtemp(prefix="qx-skills-selftest-"))
    try:
        root = tmp / "skills"
        write_skill(root, "quantx-alpha")

        missing = evaluate(root)
        check_case("missing manifest is UNKNOWN", missing["overall"] == UNKNOWN)

        check_case("update succeeds on valid fixture", run_update(root) == 0)
        check_case("clean fixture PASSes", evaluate(root)["overall"] == PASS)

        notes = root / "quantx-alpha" / "references" / "notes.md"
        notes.write_text("changed\n", encoding="utf-8")
        check_case("modified file FAILs", evaluate(root)["overall"] == FAIL)

        notes.write_bytes(b"notes\r\n")
        check_case("CRLF variant still PASSes", evaluate(root)["overall"] == PASS)

        extra = root / "quantx-alpha" / "extra.md"
        extra.write_text("x\n", encoding="utf-8")
        check_case("unlisted file FAILs", evaluate(root)["overall"] == FAIL)
        extra.unlink()

        notes.unlink()
        check_case("missing listed file FAILs", evaluate(root)["overall"] == FAIL)
        notes.write_text("notes\n", encoding="utf-8")

        skill_md = root / "quantx-alpha" / "SKILL.md"
        good = skill_md.read_text(encoding="utf-8")
        skill_md.write_text(
            good.replace("name: quantx-alpha", "name: quantx-beta"), encoding="utf-8"
        )
        check_case("name/directory mismatch FAILs", evaluate(root)["overall"] == FAIL)

        skill_md.write_text("---\nname: quantx-alpha\n---\n", encoding="utf-8")
        check_case("missing description FAILs", evaluate(root)["overall"] == FAIL)
        skill_md.write_text(good, encoding="utf-8")

        bad_root = tmp / "bad-skills"
        write_skill(bad_root, "quantx-gamma")
        (bad_root / "quantx-gamma" / "SKILL.md").write_text("no frontmatter\n", encoding="utf-8")
        check_case("update refuses invalid frontmatter", run_update(bad_root) == 1)
        check_case(
            "refused update leaves no manifest",
            not (bad_root / MANIFEST_NAME).exists(),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print(f"SELF-TEST FAILED ({len(failures)}/{total} failing): {', '.join(failures)}")
        return 1
    print(f"SELF-TEST PASS: {total} checks")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QuantX skills integrity validator")
    parser.add_argument(
        "--skills-dir", default=".opencode/skills", help="skills root (default: .opencode/skills)"
    )
    parser.add_argument("--update", action="store_true", help="regenerate the manifest")
    parser.add_argument(
        "--check", action="store_true", help="verify frontmatter and manifest (default)"
    )
    parser.add_argument("--self-test", action="store_true", help="validate evaluator behavior only")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.update and args.check:
        parser.error("choose one of --update or --check")
    try:
        root = Path(args.skills_dir).resolve()
        if args.update:
            return run_update(root)
        report = evaluate(root)
        print_report(report)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        name = f"skills-integrity-{stamp}.json"
        evidence = Path(tempfile.gettempdir()) / EVIDENCE_DIR_NAME / name
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
