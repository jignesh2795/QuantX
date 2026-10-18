# Environment & Command Reference (quantx-dev-workflow)

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

## Hook, CI, and policy notes

- The repository gate is *changed-file* Ruff (repo-wide Ruff may have pre-existing findings — inspect before claiming counts), enforced by `scripts/hooks/pre-push`. Enable with: `git config core.hooksPath scripts/hooks`.
- The pre-push hook runs `uv run ruff check` over `.py` files in `git diff --name-only '@{push}...HEAD'` (fallback `origin/main...HEAD`).
- Validation-gate policy (whether GitHub Actions counts as evidence, and the current execution gate) is authoritative in `docs/STATUS.md` — verify there instead of assuming.
- The full CI sequence (`.github/workflows/test.yml`): `uv sync --locked --dev --extra dhan` → ruff check/format on Dhan paths → pytest dhan → pytest paper → full pytest.

## Executable gates

- Validation: `python .opencode/skills/quantx-validation-gate/scripts/run_validation.py --expected-head <sha>` runs the gate read-only and writes machine-readable evidence.
- Release: `python .opencode/skills/quantx-release-gate/scripts/release_check.py --expected-head <sha>` binds that evidence to the exact merge candidate. See those skills for exit codes and PASS/FAIL/UNKNOWN semantics.
