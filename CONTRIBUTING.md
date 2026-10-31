# Contributing to QuantX

Thank you for considering a contribution to QuantX. This guide is the human entry point for making a focused, reviewable change. It complements rather than replaces the project’s implementation and architecture documentation.

## Before you start

QuantX is a modular, event-driven trading platform for Indian markets. Read the [project overview](README.md) and, before changing behavior, locate the relevant boundary in [the architecture documentation](docs/architecture/README.md).

Use the repository’s pinned toolchain:

- Python **3.12** (the version is recorded in `.python-version`).
- [uv](https://docs.astral.sh/uv/) for interpreter management, dependency synchronization, and running project tools.
- The committed `uv.lock` for reproducible dependency resolution.

On Windows, install uv with:

```powershell
winget install --id=astral-sh.uv -e
```

From the repository root, prepare the default development environment:

```powershell
.\scripts\setup.ps1
```

The setup script installs the pinned Python interpreter (unless asked not to) and runs `uv sync --dev`. To prepare it manually:

```powershell
uv python install
uv sync --dev --locked
```

The Dhan broker SDK is an optional extra. Contributors working on that adapter should also validate with the extra enabled:

```powershell
uv sync --dev --extra dhan --locked
```

Do not edit `uv.lock` for a documentation-only or code-only change unless dependencies actually change. When dependencies do change, update the lockfile intentionally and include it in the review.

## Contribution workflow

1. Start from an up-to-date `main` and create a focused branch for one issue or coherent change. Keep unrelated work out of the branch.
2. Read the relevant source, tests, and canonical documents before editing. Follow existing module boundaries and conventions; avoid introducing a second implementation of an existing contract.
3. Make the smallest change that satisfies the requirement. Add or update focused regression tests for behavior changes.
4. Run focused tests while iterating, then run the complete local validation gates described below.
5. Review the final diff for scope, accidental files, generated artifacts, secrets, and whitespace. Record the exact base and candidate commit SHAs.
6. Open a pull request with the problem, the solution, scope, test commands and results, exact SHAs, and any limitations or skipped checks.

The [implementation guide](docs/implementation/README.md) is the canonical reference for implementation discipline and build sequencing. The [local release-validation playbook](docs/implementation/local-release-validation-playbook.md) defines the reproducible, exact-SHA validation procedure and evidence requirements. Durable architecture rationale belongs in [architecture decisions](docs/decisions/README.md), with accepted ADR records linked there.

## Local validation gates

Use the locked environment and validate the exact candidate commit in a clean, isolated worktree. The canonical full-suite command is:

```powershell
uv run pytest
```

`pyproject.toml` already configures `addopts = "-q"`. Do not append another `-q` to full-suite or focused pytest commands: double-quiet mode suppresses the normal summary counts needed for validation evidence.

Useful focused commands during development include:

```powershell
uv run pytest tests/unit
uv run pytest tests/unit/execution
uv run pytest tests/unit/execution/paper
uv run pytest tests/unit/plugins/dhan
uv run pytest path/to/test_file.py::test_name
```

Focused runs help diagnose a change; they do **not** replace the full suite for candidate evidence.

For the complete candidate gate, use both locked dependency configurations, in order:

1. Default configuration: `uv sync --dev --locked`.
2. Run the validation producer immediately after that sync.
3. Dhan-enabled configuration: `uv sync --dev --extra dhan --locked`.
4. Run the validation producer immediately after that sync.

The exact producer invocation (replace the placeholders with the immutable candidate and base SHAs) is:

```powershell
python .opencode/skills/quantx-validation-gate/scripts/run_validation.py `
  --expected-head <candidate-sha> `
  --base <base-sha> `
  --output "$env:TEMP\quantx-validation\<task>\validation.json"
```

Each producer run checks the full pytest suite, Ruff lint and format for changed Python files, strict mypy over the `quantx` package, `git diff --check`, and tracked-worktree cleanliness. For the full two-configuration gate, inspect each evidence record and run the corresponding release checker as documented in the [local release-validation playbook](docs/implementation/local-release-validation-playbook.md). That playbook also defines the skill-integrity/self-tests, evidence retention, and PASS/FAIL/UNKNOWN rules. Do not treat a diagnostic focused run as a release candidate.

The underlying checks can also be run individually:

```powershell
uv run ruff check <changed-python-files>
uv run ruff format --check <changed-files>
uv run mypy
git diff --check
git status --porcelain
```

Ruff’s candidate gate is scoped to changed Python files against the stated base; it is not a claim that every historical repository file is lint-clean. Mypy uses the project’s strict configuration. The Dhan-disabled configuration may report optional SDK-dependent tests as skipped; report the exact count and reasons explicitly. A missing, skipped, timed-out, or SHA-mismatched mandatory check is not a PASS.

For a documentation-only contribution, still run the full suite and the documentation-relevant checks from the playbook where the environment is available. Report what was actually run; never infer that tests or static checks passed because no production code changed.

## Pull-request evidence

A useful pull request should make review reproducible. Include:

- The issue and acceptance criteria addressed, plus a concise summary of the change.
- Exact base SHA and final candidate SHA (not just branch names).
- Changed-file list and confirmation that the diff stays within scope.
- Focused test command/results and full-suite results, including counts and skips.
- Ruff lint/format and strict mypy results, with the configuration used (Dhan extra enabled or disabled).
- `git diff --check` and clean-worktree result.
- Any unavailable checks, environment limitations, unresolved risks, or acceptance criteria not met.

Keep local evidence separate from hosted checks. A local PASS means only that the recorded commands passed for the stated local commit and environment. It does not mean GitHub Actions ran or passed. Do not describe Actions as a passing gate unless there is an actual, independently observed result; this project’s contributor validation path is local-first.

## Engineering and safety assumptions

Contributions must preserve the project’s core invariants:

- **Fail closed:** missing, contradictory, stale, or unknown evidence must not be promoted to PASS or silently treated as zero. Unknown conditions remain explicit and block unsafe progression.
- **Deterministic replay:** event ordering and replay-sensitive behavior must remain deterministic. Tests should exercise stable outcomes rather than depend on wall-clock timing or external services.
- **Provenance:** claims that authorize or explain trading decisions must retain their source, identity, freshness, and completeness. Do not fabricate broker or market evidence.
- **No production LIVE readiness by implication:** passing local tests, paper/sandbox behavior, an adapter implementation, or a green validation report does not establish production-broker correctness or LIVE trading readiness. Never submit real broker orders or invoke production broker/API operations as part of development or validation.

Keep broker SDK imports behind their approved adapter boundary, use `Decimal` for financial values, and preserve the separation between domain contracts and integrations. Consult the architecture docs and accepted ADRs before proposing a change to a durable boundary.

## Scope and communication

Prefer small pull requests tied to a concrete issue. Explain trade-offs where a change alters a contract or invariant. If a requirement cannot be satisfied safely, state the blocker and leave the behavior fail-closed rather than weakening a guard to make a test pass.

Please do not add credentials, tokens, account data, generated environment files, or unrelated cleanup to a contribution. Never make a development claim that has not been verified against the exact candidate commit.
