# Package coverage floors

Status: implemented/current validation policy (2026-10-31).

This document is the canonical record for the independently enforced line and
branch coverage floors of `quantx.domain`, `quantx.execution` and
`quantx.persistence`. It implements the local-validation requirements of issue
[#182](https://github.com/jignesh2795/QuantX/issues/182) without claiming
production readiness or replacing adversarial correctness tests.

## Context

An aggregate suite percentage can hide a weak package. The three packages below
carry domain money/risk contracts, the execution control path, and durable
persistence/recovery state, so each is measured and enforced separately. Dhan
transport coverage and unreferenced modules are a separate concern tracked in
issue [#202](https://github.com/jignesh2795/QuantX/issues/202); see
[Relationship to #202](#relationship-to-202).

## Baseline measurement

Measured at base SHA
`9841ae361e3612341cdc728c66ccf47d6ebcbd79` on 2026-10-31 with the locked
Python 3.12 environment (`uv sync --dev --locked`; Python 3.12.12, coverage
7.16.1, pytest-cov 7.1.0), full suite, branch measurement enabled.

The default and Dhan-extra configurations produced identical package figures
at that SHA.

| Package | Line covered / statements | Line | Branch covered / branches | Branch |
|---|---:|---:|---:|---:|
| `quantx.domain` | 2078 / 2341 | 88.77% | 775 / 1038 | 74.66% |
| `quantx.execution` | 3062 / 3429 | 89.30% | 1003 / 1330 | 75.41% |
| `quantx.persistence` | 872 / 936 | 93.16% | 220 / 270 | 81.48% |

Measurement command (the gate runs the same selection):

```powershell
uv run pytest -q `
  --cov=quantx.domain --cov=quantx.execution --cov=quantx.persistence `
  --cov-branch --cov-report=json:<temp-path> --cov-report=
```

Line coverage and branch coverage are reported and enforced separately. They
are not interchangeable, and neither is a mutation score.

## Required floors

| Package | Required line | Required branch | Line headroom vs baseline | Branch headroom vs baseline |
|---|---:|---:|---:|---:|
| `quantx.domain` | 87% | 73% | 1.77 points | 1.66 points |
| `quantx.execution` | 88% | 74% | 1.30 points | 1.41 points |
| `quantx.persistence` | 92% | 80% | 1.16 points | 1.48 points |

The floors are not round-number targets. Each floor is derived from the
measured baseline by taking the truncated measured percentage and subtracting
one full percentage point: `floor(measured) - 1`. That uniform rule is applied
to both line and branch coverage for every package, so the thresholds are
reproducible from the table above.

The floors are deliberately below the measured baseline rather than equal to
it. This tolerates ordinary small refactors and environment variation while
still failing on a material regression. The execution package is the
safety-critical control path, so its floor is not softened below the uniform
rule; the persistence package protects durable execution/idempotency state and
is held to the highest measured floors because its baseline supports them.
Passing a floor is a regression alarm, not proof that the package is correct or
safe.

## Command and output

Run the gate directly:

```powershell
uv run python .opencode/skills/quantx-validation-gate/scripts/package_coverage.py
```

The script runs the full suite through the current locked interpreter, writes
its coverage JSON outside the repository under the system temp directory, and
prints measured and required line/branch percentages for all three packages.
Exit codes are `0` = PASS, `1` = FAIL, `2` = UNKNOWN, `3` = usage/internal
error. A missing package, missing branch proof, malformed data, missing tool,
timeout, or test-run failure is never PASS.

The documented local validation producer runs it automatically as the
`package-coverage` mandatory check:

```powershell
python .opencode/skills/quantx-validation-gate/scripts/run_validation.py `
  --expected-head <sha> --base <base-sha> --output <evidence.json>
```

The evidence record's summary identifies each package's measured and required
line/branch percentages. `--skip-coverage` records UNKNOWN, never PASS. The
release gate requires the `package-coverage` record exactly once, validates its
canonical invocation, and pins the package order and required floors.

## Failure demonstration

Before the candidate commit, a temporary untested module
(`src/quantx/domain/_coverage_floor_probe.py`, 15 small functions with one
branch each) was added and left unimported. The gate measured:

```text
domain: line 2078/2390 = 86.49% (required 87%) FAIL; branch 775/1064 = 72.46% (required 73%) FAIL
OVERALL: FAIL
```

The module was removed, and the same command returned:

```text
domain: line 2078/2341 = 88.77% (required 87%) PASS; branch 775/1038 = 74.66% (required 73%) PASS
OVERALL: PASS
```

This demonstrates both directions: a new untested module breaches the floors,
and removing it restores the measured baseline. The probe was never committed.

## New-module inclusion policy

Coverage is measured over each package as a source tree, not from a static file
allowlist. Every current and future module under `quantx.domain`,
`quantx.execution` and `quantx.persistence` is included, whether or not a test
imports it. A new module with no tests therefore lowers its package percentage
and can fail the gate immediately; that is intentional.

There is no per-file opt-out in this policy. Adding tests is the normal way to
restore headroom. A project-specific coverage exclusion must be reviewed and
documented as a threshold-policy change, not added silently to hide new code.
Coverage.py's built-in exclusions still apply, but they are not a substitute for
tests on safety-critical branches.

## Threshold revision policy

- Floors are minimums, not targets. Do not write low-value tests solely to
  reach a percentage, and do not treat a green floor as a correctness claim.
- Raising a floor is allowed in normal reviewed work when the measured baseline
  has improved.
- Lowering a floor requires a dedicated reviewed change. It must record the new
  measured baseline, the exact measurement command, the reason the prior floor
  is no longer appropriate (for example a large deliberate untested scaffold or
  a measured environment change), and the risk assessment for the affected
  package. A floor is never lowered merely to turn a red gate green.
- Any revision updates this document, the floors in `package_coverage.py`, the
  mirrored requirements in `release_check.py`, and their self-tests in the same
  change. Line and branch floors are revised together only with explicit
  justification; dropping branch enforcement requires its own decision.
- Every revision records its base SHA and measured figures. Thresholds are not
  copied from a different commit without remeasurement.

## Relationship to #202

Issue #202 tracks targeted Dhan transport coverage (reported around 62%) and
unreferenced 0%-coverage modules. Those files are outside the three packages
measured here, so these floors neither mask nor resolve that work:

- A high `quantx.execution` or `quantx.persistence` percentage says nothing
  about the Dhan broker boundary.
- The package floors do not replace #202's targeted adapter/dead-module
  treatment, and #202 does not replace these package floors.
- Future plugin-specific or broker-boundary floors should be added as their own
  measured policy change. They must not be implemented by lowering these core
  package floors.

Issue #182 remains about package regression detection; it does not close #202.

## Package inventory and exclusion rationale

The gate discovers every top-level package under `src/quantx/` and checks it against the explicit inventory below. Coverage JSON discovery is retained as a secondary consistency check. A package
must be listed as either ``measured`` (with an enforced floor) or ``excluded``
(with a documented reason). Any discovered package absent from this inventory
fails closed so a new package cannot silently bypass the gate.

| Package | Status | Reason |
|---|---|---|
| `quantx.domain` | measured | safety-critical domain money/risk contracts |
| `quantx.execution` | measured | safety-critical execution control path |
| `quantx.persistence` | measured | safety-critical durable execution and recovery state |
| `quantx.application` | excluded | application-layer orchestration; correctness verified by integration tests |
| `quantx.integrations` | excluded | boundary adapters and reconciliation evidence; coverage tracked by integration tests |
| `quantx.india` | excluded | India-market data adapter; coverage tracked by separate market-pack checks |
| `quantx.plugins` | excluded | broker plugin boundary; Dhan transport coverage tracked in issue #202 |
| `quantx.ports` | excluded | interface definitions without direct business logic |
| `quantx.research` | excluded | research utilities; not safety-critical for coverage floors |
| `quantx.strategy` | excluded | strategy implementations; correctness covered by confidence-contract tests |

To add a newly measured package, the change must:
1. add the package name and floor to `PACKAGE_FLOORS` in `package_coverage.py`,
2. add the package to `MEASURED_PACKAGES`,
3. record the measured baseline, floor rationale, and coverage command in this
   document, and
4. update the mirrored requirements and self-tests in `run_validation.py` and
   `release_check.py`.

To add an excluded package, the change must record the documented reason in
the inventory above and in `package_coverage.py`. Silently extending the
exclusion list is not permitted.

## Non-claims

- Line and branch coverage are not mutation scores and do not prove test
  quality, adversarial correctness, or the absence of defects.
- A passing gate does not establish production-broker correctness, LIVE
  readiness, or authenticated evidence provenance.
- The measurement is local and deterministic for the locked environment, but it
  is not a GitHub Actions or paid-CI attestation.
