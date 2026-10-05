---
name: quantx-dev-workflow
description: Use when running validation, tests, lint, typecheck, commits, branches, or making any code change in the QuantX repo. Covers the 7-step implementation discipline, uv/pytest/ruff/mypy commands, the git hook gate, branching and commit conventions, and where documentation belongs (docs/STATUS.md, docs/implementation, docs/decisions, docs/roadmap).
---

# QuantX Developer Workflow

QuantX is a Python 3.12 modular trading platform managed with **uv**. There is no pip/venv workflow — always use `uv run ...` from the repository root.

## Implementation discipline (mandatory, 7 steps)

From `docs/implementation/README.md`. Follow for every change:

1. Inspect existing code before changing it.
2. Identify one concrete integrity gap.
3. Make the smallest non-duplicative production change.
4. Add a focused regression test.
5. Run focused and full validation.
6. Run Ruff/format/mypy where applicable.
7. Leave no unintended content changes.

Rules of thumb:

- One concrete gap per change. Do not start a broad package migration or UI/AI subsystem while an existing boundary can be hardened incrementally.
- Current priorities are authoritative in `docs/STATUS.md` and `docs/roadmap/`. Use the repository documents to determine the active milestone.
- Do not create one permanent document per batch unless it introduces a durable architectural decision.

## Environment setup

```powershell
.\scripts\setup.ps1          # bootstrap: uv python install + uv sync --dev
uv python install
uv sync --dev
uv sync --dev --extra dhan    # optional Dhan SDK (version authoritative in pyproject.toml/uv.lock)
uv lock                       # regenerate lockfile after dependency changes; commit uv.lock
```

## Validation commands

```powershell
uv run pytest -q                                    # full suite (also: python scripts/test_all.py)
uv run pytest tests/unit -q                         # fast unit layer (also: scripts/test_fast.py)
uv run pytest tests/unit/execution -q               # execution-focused (also: scripts/test_execution.py)
uv run pytest tests/unit/execution/paper -q         # paper venue
uv run pytest tests/unit/plugins/dhan -q            # Dhan plugin slice
uv run ruff check                                   # lint
uv run ruff format --check                          # format check
uv run mypy                                         # strict typecheck (package quantx)
git diff --check                                    # whitespace errors
```

Repository gate (must pass before push):

```
pytest green + changed-file Ruff clean + git diff --check clean
```

Notes:

- The repository gate is *changed-file* Ruff (repo-wide Ruff may have pre-existing findings — inspect before claiming counts), enforced by `scripts/hooks/pre-push`. Enable with: `git config core.hooksPath scripts/hooks`.
- The pre-push hook runs `uv run ruff check` over `.py` files in `git diff --name-only '@{push}...HEAD'` (fallback `origin/main...HEAD`).
- Validation-gate policy (whether GitHub Actions counts as evidence, and the current execution gate) is authoritative in `docs/STATUS.md` — verify there instead of assuming.
- The full CI sequence (`.github/workflows/test.yml`): `uv sync --locked --dev --extra dhan` → ruff check/format on Dhan paths → pytest dhan → pytest paper → full pytest.

## Branching and commits

- Branches: `main`, `feat/<slug>-v1`, `fix/<slug>-v1`, `test/<slug>-v1`, `docs/<slug>`. Major implementation must **not** start on `main`; a feature branch must reference an architecture decision or roadmap item (`docs/architecture/03-branching-strategy.md`).
- Commit subjects must follow Conventional Commits. Use the appropriate established type for the change — do not treat any hardcoded prefix list as an allowlist.
- Commit `uv.lock` after any dependency change.

## Documentation policy

One source of truth. Update the existing canonical doc; never create duplicates.

| Content | Location |
|---|---|
| Current state / validation baseline | `docs/STATUS.md` |
| Architecture rules & boundaries | `docs/architecture/` (start at `README.md`) |
| Sequencing, build order, discipline | `docs/implementation/` |
| Durable architecture decisions (ADRs) | `docs/decisions/` |
| Future milestones / decision gates | `docs/roadmap/` |
| Research & tech evaluation | `docs/research/` |

- Process order: **Research → Compare → Decide → Document → Build**.
- Architecture docs must distinguish *implemented/current* vs *target* vs *roadmap/future*.
- Historical batch records are not current state unless marked historical.
- Temporary execution notes do not belong in the permanent architecture set.

## Implementation rules

- Before editing: read the current canonical docs and the source/tests for the target boundary; **search all consumers of changed types and fields**.
- Make the smallest coherent change; do not change unrelated files.
- Preserve backwards compatibility when practical; identify intentional breaking changes explicitly.
- Do not add dependencies unless necessary and approved by repository architecture.
- Preserve Decimal and timezone invariants; preserve UNKNOWN/fail-closed behavior.
- Add regression tests for every changed invariant.
- Update canonical docs rather than proliferating batch-specific documents.
- Never claim a test result that was not actually run.

### Completion report

Include: branch, commit(s), changed files, exact commands actually run, test/lint/type results, safety review when applicable, explicit non-claims, and remaining issues.

## Current restrictions (authoritative source: `docs/STATUS.md`)

Verify active restrictions in `docs/STATUS.md` and `docs/roadmap/` before acting — use the repository documents to determine the active milestone, not this skill. As historically stated there: no UI/AI execution/broad broker matrix while the focus is elsewhere, no production-broker end-to-end execution claims, no second LIVE execution path, no background recovery daemon, no generic process entrypoint.
