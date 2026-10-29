# QuantX Status


## Current work-program reconciliation — 2026-10-27

The active cross-workstream priority order is maintained in the [master work programme](planning/quantx-work-program-2026-10.md). Use it with GitHub's individual issue acceptance criteria; this file remains the implementation and exact-SHA evidence ledger.

- **P0.1 / #239, P0.2 / #240 and P0.3 / #241:** fixed and merged. Do not reimplement without a newly reproduced defect.
- **QX-04 / #193, QX-05 / #194, QX-07 / #181, QX-08 / #196 and QX-09 / #197:** implementation recorded as merged/completed. QX-07 Slices 1, 2A and 2B landed in PRs #257, #259 and #261; #181 was closed as completed on 2026-10-27 after checking the merge state. The older pre-merge current-state snapshot later in this file is historical and is superseded by the new work programme.
- **LIVE trusted-clock slice / PR #281:** merged; it does not establish risk-evidence provenance. **#267 is the next priority** for request-bound, authority-bearing risk evidence. #266, #280, #271, #269 and #189 remain follow-up work.
- **QX-12 / #200:** the India charges design and evidence notes are now recorded under `docs/planning/`; this remains design/contract-only until implementation validation and unresolved GST/stamp-duty rate applicability gates are closed.
- **Global-market comparison and crypto extension:** remain proposals on separate unmerged docs branches. Their existence is not a statement that the audit, connector support, or LIVE eligibility is complete.

This documentation reconciliation did not run tests or CI, call a broker, run a sandbox, or perform a LIVE operation. Do not attribute validation results to this documentation commit.

## Issue #267 — LIVE authorization boundary and risk-evidence authority (2026-10-28)

The feature branch now moves authorization issuance out of the `ExecutionOrchestrator`
instance, rejects malformed nonce types before replay/digest processing, validates the
risk intent/order/execution-context identity, and rejects arbitrary evaluator callbacks.
The application-owned `LivePreTradeRiskEvaluator` reports authoritative evidence unavailable
because its provider inputs have no authenticated provenance source. Public LIVE dispatch is
therefore blocked before reservation and broker submission, even when the trading gate is
explicitly enabled.

**Issue #267 remains open.** No implemented trusted source currently binds positions,
balances, P&L, snapshot observation time, account, and connection identity to authenticated
broker/host evidence. Fresh timestamps and a matching request do not establish provenance.
Do not remove the fail-closed authority guard until an authoritative adapter/composition and
its identity, freshness, completeness, unavailable-state, and contradiction tests exist.

**Previous candidate validation record — SHA `8034905f064af7d12537936810e9d23a447b92e9`:**
the branch author reported 32 focused authorization tests passed, 1,789 affected tests
passed, 2,959 full-suite tests passed, Ruff/format, strict mypy, `uv lock --check`, and
`git diff --check` passed. Those results are historical, have not been independently
reproduced here, and do not validate the follow-up commits.

**Failed follow-up validation — SHA `c3c29e346548a345eb0f93dfebf65620db6f1e5e` (2026-10-29):**
default configuration: 17 failed, 2,965 passed, 1 skipped; Dhan-enabled configuration:
17 failed, 2,966 passed. Changed-file Ruff reported 3 errors across 9 files, format check
reported 4 files requiring formatting, and strict mypy reported `no-any-return` in
`src/quantx/application/live_risk.py:96`. `uv lock --check` and `git diff --check` passed;
both release checks failed because the validation overall was FAIL. The failed test set
included four application execution tests, four India-enforcement tests, five R0-B timeout
tests, three Dhan adapter tests, and one reference-broker composition test.

**Remediation validation - SHA `500b9e606c84b52a12513780e5033c991810c6b1` (2026-10-29):**
the remediation commit corrects the public LIVE versus transaction-test boundary assumptions,
preserves fail-closed public dispatch, keeps the application-owned `LivePreTradeRiskEvaluator`
blocked because authoritative evidence is unavailable, expands the request/risk identity
mismatch matrix, adjusts the instrument-resolution type contract, and corrects import
ordering. The admission-race regression now expects a direct retry of the pending reservation
to return `UNKNOWN` rather than `BLOCKED`, while still asserting zero broker submissions.

Focused results at that SHA: `tests/unit/application/test_execution.py` 118 passed; the
India-enforcement, R0-B timeout, Dhan adapter, and reference-broker group 69 passed; the
live-risk, LIVE submission authorization, receipt-identity, and LIVE execution group
205 passed.

Default configuration: 2,983 passed, 1 skipped; Dhan-enabled configuration: 2,984 passed.
Changed-file Ruff check and format check passed across 13 Python files, strict mypy passed
for 202 source files, `uv lock --check` passed, and `git diff --check` reported no whitespace
errors. Both release checks passed for that SHA, including evidence HEAD/base binding,
canonical argv, 13-file changed-Python scope, 15-file branch scope, and clean tracked-tree
integrity. The documentation commit that records these results changes HEAD and is therefore
validated separately in both configurations at its own final SHA; the counts above are not
evidence for that later commit.

**Reconciled candidate validation - SHA `15c9fff039124c13c20ebdc592c0ea0338d0a08f` (2026-10-29):**
the reconciliation merge commit has parents `10e348ed84035f59661dcce069dbc71996bdd910` and
`91cca51db45d35afc0eaaac791f557392c627c09`, preserving both the validated remediation and the
instrument-resolution consistency guard. When `context.instrument_resolution` is present,
`context.instrument` must equal `context.instrument_resolution.instrument`; divergence is
rejected as `LIVE_RISK_REQUEST_MISMATCH` before reservation or broker submission. The
regression is `test_live_pretrade_rejects_instrument_facts_that_diverge_from_resolution`.

Focused results at that SHA: `tests/unit/application/test_execution.py` 118 passed; the
India-enforcement, R0-B timeout, Dhan adapter, and reference-broker group 69 passed; the
live-risk, LIVE submission authorization, receipt-identity, and LIVE execution group
206 passed.

Default configuration: 2,984 passed, 1 skipped; Dhan-enabled configuration: 2,985 passed.
Changed-file Ruff check and format check passed across 13 Python files, strict mypy passed
for 202 source files, `uv lock --check` passed, `git diff --check` reported no whitespace
errors, and the tracked worktree was clean. Both release checks passed with exact HEAD/base
binding, canonical full-suite argv, 13-file changed-Python scope, and 15-file branch scope.
Evidence and reports under `%LOCALAPPDATA%\Temp\quantx-validation\`:
`issue267-reconcile-15c9fff-default.json`, `issue267-reconcile-15c9fff-dhan.json`,
`release-15c9fff-default.json`, and `release-15c9fff-dhan.json`.

The reconciliation candidate's evidence does not validate the earlier `10e348e` commit or
any later documentation commit; the documentation commit is validated separately at its own
final SHA.

Non-claims: the evidence is local, unauthenticated JSON produced without GitHub Actions or
paid CI; no broker I/O, LIVE order, production credential, or real-broker end-to-end run was
performed. PASS does not establish production or broker correctness, LIVE readiness, or
authenticated risk-evidence provenance. Issue #267 remains open, and public LIVE dispatch
remains blocked before reservation and submission until an authoritative provenance source
and its identity, freshness, completeness, unavailable-state, and contradiction tests exist.
No counts from SHA `c3c29e346548a345eb0f93dfebf65620db6f1e5e` validate a later revision.

No GitHub Actions or paid CI was used; no broker I/O, LIVE order, or production-broker
end-to-end run was performed.

## Issue #267 — LIVE risk-evidence source-trust remediation (2026-10-29)

Branch `fix/issue267-trusted-source-registration-v1`, created from the published
candidate `9977cb05ab5fa6c9ab2d61c3523eef2b0d7a6e46` over the frozen remediation
base `17cd4c8de01e283b2e3101c2d06cee7397a70b24`.

**Root cause.** `LiveExecutionConfig` accepted any object satisfying the
runtime-checkable `LiveRiskEvidenceSource` protocol. Availability was decided
from that source's own `supported_fields` claim, identity was checked against
account/connection/client/transport values supplied by the same caller, and
completeness compared observations against the `RiskContext`/`RiskSnapshot` the
source itself produced. The authority HMAC sealed only its own wrapping, so an
internally consistent fabricated source reached the risk engine and the broker.

**Trust model.** Trust follows the registered execution path. The evidence
construction path is the bound method of the adapter behind the account /
connection this process registered; there is no separate declaration to supply:

```text
AccountConnectionRegistry
        |  registered connection -> adapter
        v
DhanBrokerAdapter.build_live_risk_evidence_binding   (plugin construction path)
        |  derived by the application, never supplied by the caller
        v
LiveRiskEvidenceSourceCatalog   (application-minted; not constructible outside)
        |  grant(): build over the exact registered connection
        v
LiveRiskEvidenceSourceGrant     (sealed construction proof)
        v
LiveRiskEvidenceAuthority       (re-verifies the grant and its registry entry)
```

`LiveExecutionConfig` has no source field and no catalog field. Authority mode
takes the registered account and broker connection; the factory resolves
`ProductionRuntime.registry`, derives the catalog from that connection's own
adapter, and fails closed with a fixed composition error for an unregistered or
disabled connection, a wrong account, a connection whose adapter exposes no
construction path, or a construction path that does not describe the
registration. The authority
derives the expected account, connection, broker client and transport from the
grant's binding instead of from caller arguments, then re-verifies the grant
seal and the registry entry. Existing controls are unchanged: evidence
identity, request binding, contradictions, completeness, freshness,
future-dated rejection, trusted capture instant, and the per-instance HMAC
authorization. The neutral evidence contracts moved to
`quantx/application/live_risk_evidence.py` and are re-exported from
`quantx/application/live_risk.py`.

The Dhan plugin implements the construction path on its own adapter
(`DhanBrokerAdapter.build_live_risk_evidence_binding`), so the application layer
names no vendor and no plugin-only builder record exists. Dhan remains
non-authoritative: it still reports daily P&L, equity and high-water mark
unavailable, so sanctioned LIVE admission stays blocked before reservation and
broker submission.

**Regressions.** `tests/unit/application/test_live_risk_source_trust.py` pins
the bypass: a custom source claiming every field with internally consistent
fabricated values cannot be admitted because no API accepts a source instance;
a caller-supplied catalog cannot even be constructed, and the configuration
surface has no field for one; a hand-forged or source-swapped grant fails the
seal even when account, connection, client id and transport all match; an
unregistered connection, an adapter without a construction path, or a
construction path describing a foreign identity is rejected at composition with
zero durable gate state, zero evidence collection, zero reservation, zero broker
submit and no quarantine row; a registered adapter path still exercises the
sanctioned stack end to end.

**Validation at SHA `478e66d83ad8c911ae0c9f10e4c3ad09980e9354` (base
`17cd4c8de01e283b2e3101c2d06cee7397a70b24`):** default configuration
3,211 passed, 2 skipped; Dhan-enabled configuration 3,213 passed. Focused LIVE
authority/composition suites 259 passed; focused Dhan risk-evidence and
transport suites 127 passed, 2 skipped (129 passed with the Dhan extra).
Changed-file Ruff check and format passed for 16 Python files; strict mypy
passed for 205 source files; `uv lock --check` and `git diff --check` passed;
the tracked worktree was clean. Both release checks passed with exact HEAD/base
binding, canonical full-suite argv, 16-file changed-Python scope and 18-file
branch scope. Evidence and reports under
`%LOCALAPPDATA%\Temp\quantx-validation\`:
`issue267-trust-478e66d-default.json`, `issue267-trust-478e66d-dhan.json`,
`release-478e66d-default.json`, and `release-478e66d-dhan.json`.

Non-claims: the evidence is local, unauthenticated JSON produced without GitHub
Actions or paid CI; no real broker I/O, authenticated Dhan session, production
credential, or LIVE order was used. Source trust is composition configuration,
not an in-process security boundary: Python cannot distinguish the deployment
wiring a connection from other code in the same process wiring one, so this
design does not claim to sandbox arbitrary in-process code. What it does
guarantee is that no separate evidence declaration exists to inject —
substituting the evidence path means substituting the registered broker
connection itself, which is also the object the process uses for health,
capability routing and recovery observations. Issue #267 remains open, this
slice does not establish LIVE readiness, and sanctioned LIVE dispatch remains
blocked because no registered source supplies every required field. The
documentation commit that records these results changes HEAD and is validated
separately at its own final SHA; the counts above are not evidence for that
later commit.

### Provenance follow-up — caller-supplied catalogs removed (2026-10-29)

Branch `fix/issue267-catalog-provenance-v1`, created from the reviewed candidate
`0b066366789350ff917365c8b555cd07e7004a0e`. An independent adversarial review
demonstrated that the allowlist above was still caller-controlled:
`LiveExecutionConfig.risk_evidence_catalog` accepted a catalog the caller
constructed, a builder labelled `dhan` was granted over a genuine registered
connection, `authoritative_evidence_available` became true, and fabricated but
internally consistent evidence reached the broker (one submit).

**Correction.** The catalog leaves the composition surface entirely. Authority
mode is selected by the registered account/connection alone; the factory derives
the catalog from that connection's adapter through
`live_risk_evidence_catalog_for`, and `LiveRiskEvidenceSourceCatalog` can only be
constructed with a module-private token, so no caller can declare a construction
path anywhere in the process. `LiveRiskEvidenceSourceBuilder` is no longer
public, and the Dhan plugin's `build_dhan_risk_evidence_builder` /
`build_dhan_risk_evidence_catalog` helpers were removed in favour of the
adapter's own method. `DhanHostConfig` gained an optional `broker_client_id` so a
host over a custom transport can declare the client identity the adapter binds
evidence to; without it the adapter exposes no usable construction path and
composition fails closed.

**Regressions.** `test_the_published_catalog_bypass_cannot_be_reconstructed`
replays the reported exploit shape and proves each step is refused: the catalog
cannot be built, the config has no field for it, and the sanctioned root raises a
fixed composition error with zero gate state, zero evidence collection, zero
reservation and zero broker submit.
`test_a_catalog_cannot_be_constructed_outside_the_application`,
`test_a_plain_registration_exposes_no_construction_path`,
`test_a_provider_result_that_is_not_the_registered_construction_is_not_granted`,
`test_a_raising_provider_is_not_granted` and the Dhan adapter/host tests cover
the remaining edges.

**Validation at SHA `acea2894b12f0884834786858dd0446a7f2d0f99` (base
`17cd4c8de01e283b2e3101c2d06cee7397a70b24`):** default configuration 3,217
passed, 2 skipped; Dhan-enabled configuration 3,219 passed. Focused LIVE
trust/authority/composition and Dhan suites 236 passed, 2 skipped in the default
configuration and 282 passed with the Dhan extra (that run also includes the
Dhan transport suite). Changed-file Ruff check and format passed for 17 Python
files; strict mypy passed for 205 source files; `uv lock --check` and
`git diff --check` passed; the tracked worktree was clean. Both release checks
passed with exact HEAD/base binding, canonical full-suite argv, 17-file
changed-Python scope and 19-file branch scope. An executed probe at this SHA
replayed the original exploit attempt and recorded: catalog construction
refused, no config field, composition error before any durable write, zero
submits, zero evidence collections. Dhan remains non-authoritative
(`authoritative_evidence_available` false,
`LIVE_RISK_EVIDENCE_SOURCE_UNAVAILABLE`, zero profile reads, zero submits).
Evidence and reports under `%LOCALAPPDATA%\Temp\quantx-validation\`:
`provenance-acea289-default.json`, `provenance-acea289-dhan.json`,
`provenance-acea289-default-release.json`,
`provenance-acea289-dhan-release.json`, and `provenance-acea289-probe.txt`.

Non-claims: local, unauthenticated JSON evidence produced without GitHub Actions
or paid CI; no real broker I/O, authenticated Dhan session, production
credential or LIVE order. This boundary is application composition, not an
in-process sandbox, and it does not establish independent corroboration of
broker-reported financial values. Issue #267 remains open and the sanctioned
LIVE path remains blocked.

## Issue #267 — Dhan risk-evidence authority slice (2026-10-29)

Branch `feat/issue267-dhan-risk-evidence-authority-v1`, based on the frozen
remediation SHA `17cd4c8de01e283b2e3101c2d06cee7397a70b24`. The application layer
now owns a `LiveRiskEvidenceAuthority` over a neutral `LiveRiskEvidenceSource`
port. The authority binds each evidence candidate to the configured account,
broker connection, expected broker client id, exact transport, approved
request, and a trusted capture instant. It rejects identity, request,
completeness, contradiction, stale, future-dated, and missing-observation paths
with fixed sanitized reasons, then mints a per-instance HMAC authorization that
the evaluator verifies before the existing `PreTradeRiskEngine` runs. Callback
mode remains explicitly non-authoritative.

The Dhan plugin adds normalized profile, funds, positions, and holdings
observations to the canonical transport and a `DhanRiskEvidenceSource`.
Collection is profile-first and requires the authenticated client id to match.
Funds map to the six financial evidence fields; positions and holdings are both
required for exposure; an unavailable book never becomes an empty book; missing
or contradictory values stay unavailable. Dhan does not expose daily P&L,
complete equity, a reliable high-water mark, or mark-to-market portfolio
valuation, so the source declares those fields unsupported. The sanctioned LIVE
limits always require daily P&L, so the Dhan path remains blocked before
reservation and broker submission; `authoritative_evidence_available` stays
false for this source and public LIVE dispatch is not unblocked.

**Validation at SHA `194036627a69d22254804cc07a0c39a65cf6b6fd` (base
`17cd4c8de01e283b2e3101c2d06cee7397a70b24`):** default configuration
3,191 passed, 2 skipped; Dhan-enabled configuration 3,193 passed. Changed-file
Ruff check and format passed for 12 Python files; strict mypy passed for 203
source files; `uv lock --check` and `git diff --check` passed; the tracked
worktree was clean. Both release checks passed with exact HEAD/base binding,
canonical full-suite argv, 12-file changed-Python scope, and 13-file branch
scope. Evidence and reports under `%LOCALAPPDATA%\Temp\quantx-validation\`:
`issue267-dhan-authority-1940366-default.json`,
`issue267-dhan-authority-1940366-dhan.json`,
`release-1940366-default.json`, and `release-1940366-dhan.json`.

Non-claims: the evidence is local, unauthenticated JSON produced without GitHub
Actions or paid CI; no real broker I/O, authenticated Dhan session, production
credential, or LIVE order was used. Dhan endpoint behavior is implemented
against documented fields and exercised only through the in-memory transport;
no Dhan response fidelity or production correctness is claimed. Issue #267
remains open, and this slice does not establish LIVE readiness or authoritative
Dhan risk evidence. The documentation commit that records these results changes
HEAD and is validated separately at its own final SHA; the counts above are not
evidence for that later commit.

## LIVE trusted clock for risk freshness — slice B (2026-10-24)

`LiveExecutionConfig` requires an injected `Clock`; the factory rejects any non-`Clock` before writing durable state. `LivePreTradeRiskEvaluator` reads it once per evaluation and passes only that reading to the clock-free engine as `evaluated_at`, so the engine computes snapshot age from trusted time against the provider-supplied `snapshot.observed_at`.
The provider's renamed `claimed_evaluated_at` is a claim validated within a fixed five-second skew of the trusted reading; it never reaches the engine, so a recent claim cannot make an already-old `snapshot.observed_at` pass freshness.
Clock or claim failures return classified `LIVE_CLOCK_*` rejections that keep the resolved instrument and block before reservation or submission; the orchestrator's generic LIVE risk failure reason no longer carries exception text.
Non-claims: the truth, accuracy, and provenance of `snapshot.observed_at`, positions, balances, and PnL stay caller-supplied and unverified; the five-second tolerance is a policy threshold, not a measured latency bound.
No broker I/O, no LIVE operation, no CI run.

## LIVE region lock: India-only composition root (2026-10-24)

`build_live_execution` derives its market policy from `MarketRegion` members: India keeps the
caller's classification and placements unchanged; every other region requires both stages
with no registered checks, so a non-India LIVE request is blocked by the market stage after
the gate and request-proof checks. A caller policy placing a non-India check fails the build.
Non-claims: no broker I/O, no LIVE operation; risk inputs stay caller-supplied; clock is later.

## LIVE gate disarms on every process start — slice A2 (2026-10-24)

The candidate for slice A2 updates `build_live_execution(runtime, config)` to persist a disarmed
trading-gate state on every composition-root invocation, overriding an enabled state left by a
prior process. The host must not expose execution if this disarm write fails, and the operator
must explicitly enable the gate after each process start. Regression coverage seeds the durable
store as enabled, rebuilds the stack, and verifies the persisted gate is disabled and a LIVE
request is blocked before broker submission.

**Validation evidence (code-bearing SHA `f6deba4594a25fc2b5af82627f8777fe2ed77417`):**
the focused composition-root module reports **14 passed**; the trading-gate/execution persistence
tests report **29 passed**; the full suite reports **2,904 passed, 1 skipped, 1 warning** (the
base SHA reported **2,903 passed, 1 skipped, 1 warning**). Ruff check passes with no findings;
Ruff format check reports **404 files already formatted**; strict mypy reports **no issues in
201 source files**; and `git diff --check` is clean. These measurements bind to the code-bearing
candidate SHA above. This status-text correction is documentation-only and does not claim that the
new documentation commit itself was re-tested. No GitHub Actions or paid CI was used.

This behavior is separate from region authorization: after an explicit enable, the previously
measured non-India LIVE execution path remains a distinct review finding and is not fixed by
startup disarming.

## LIVE execution composition root, slice A (2026-10-24)

`build_live_execution(runtime, config)` is the one supported way to assemble a LIVE-capable `ExecutionOrchestrator` over a validated `ProductionRuntime`: a durable gate persisted disarmed, a SQLite submission quarantine, the real `LivePreTradeRiskEvaluator`, the India market policy and an explicit `MarketPackPolicyVerifier`. Builds fail closed on missing or mistyped limits, risk engine, policy stages, verifier or risk-evidence provider, and a rejected build writes no durable state.
**Non-claims:** no commit, no push, no broker I/O, no LIVE operation; risk inputs stay caller-supplied and the trusted clock is slice B.
A non-India LIVE request through this stack currently executes (measured by test 12: `EXECUTED`, one broker submit); a region lock is the next slice.

## ExecutionContext.execution_mode must be an exact ExecutionMode enum (2026-10-23)

`ExecutionContext.__post_init__` now rejects any mode that is not exactly an
`ExecutionMode` enum member (`type(...) is ExecutionMode`); a plain `"live"`
or `"paper"` string, a value string, `None` or an integer is blocked before any
LIVE prerequisite, gate or adapter path. Global `execution_mode` tightening and
annotation-only fields (`broker_connection_id`, `market_pack_id`, `rule_version`)
remain tracked by [#271](https://github.com/jignesh2795/QuantX/issues/271).
**Non-claims:** no broker I/O, no LIVE operation, no CI run.

## ExecutionContext.execution_mode must be an exact ExecutionMode enum (2026-10-23)

`ExecutionContext.__post_init__` now requires `type(self.execution_mode) is ExecutionMode`; a plain `"live"` or `"paper"` skips LIVE prerequisites; `"paper"` takes the paper adapter; a `ValueError` is raised with a fixed message, no exception text included. Non-LIVE modes unchanged; `#271` tracks annotation-only fields (`broker_connection_id`, etc.). Non-claims: no broker I/O, no LIVE operation, no CI run.

## LIVE execution idempotency decision validation (2026-10-23)

`IdempotencyDecisionValidationError` is raised inside `_execute_live_transactional` at both the pre-reservation `check()` read and the `reserve_or_get()` permit scope when `validate_decision_for_request` (exact `UUID`/`str` types plus exact equality with the dispatched `client_order_id` and request fingerprint) or `validate_decision_state` (exact-`bool` flags plus the six-state matrix a reservation store can actually produce) reports a violation; raising inside the unit of work makes that transaction roll back, and `except IdempotencyDecisionValidationError` returns `BLOCKED` with a fixed reason. A cached receipt at either duplicate path is validated by `validate_cached_receipt_identity`, which accepts the exact `UUID` or the exact canonical `str` rendering and nothing else; a mismatch returns `UNKNOWN` with a fixed reason, the foreign receipt is never returned or persisted, and the diagnostic stays in sanitized quarantine evidence. Non-claims: no broker I/O, no LIVE operation, no CI run.

## LIVE idempotency decision validation completed (2026-10-24)

The earlier entry for this batch claimed request-bound validation, a state matrix and
cached-receipt identity at both duplicate paths. Only the `except` handler and one
duplicate path existed: `validate_decision_for_request(decision)` compared nothing
against the request, no state matrix or exact-`bool` check existed, a decision with
`reservation_acquired=True` and `reservation_pending=False` still reached
`broker.submit()`, and `docs/STATUS.md` described the second duplicate path as covered
when it was not. Corrected on branch
`fix/live-idempotency-decision-validation-complete-v1` (base `135b488`):
`validate_decision_for_request(decision, *, client_order_id, request_fingerprint)`
binds the decision to the dispatched request, requires an attached operator or
not-submitted closure record to belong to the same order and fingerprint (a record
closing another order proves nothing about this one), `validate_decision_state` enforces
exact `bool` flags and the six legal `(pending, acquired, receipt, operator-resolved,
not-submitted)` states, both run after `check()` and after `reserve_or_get()` with the
sentinel raised inside the transaction so the reservation rolls back, and
`validate_cached_receipt_identity` guards both duplicate paths with `UNKNOWN`, a fixed
reason and sanitized quarantine evidence on mismatch. `validate_decision_intrinsic` is
removed; no schema, fingerprint, store API, serialization or adapter change.

Local validation on `fix/live-idempotency-decision-validation-complete-v1` (base
`135b488`): the measured baseline before editing was 7 Ruff errors and 1 strict-mypy
error with **2,802 passed, 1 skipped**; afterwards `uv run ruff check src tests` reports
`All checks passed!`, `uv run ruff format --check src tests` reports
`402 files already formatted`, `uv run mypy` reports
`Success: no issues found in 200 source files`, and the full suite is
**2,890 passed, 1 skipped**, a net **+88** tests: `tests/unit/execution/test_decision_validation.py`
collects 64 (4 before this batch), `tests/unit/application/test_execution.py` collects
118, `tests/unit/application/test_receipt_identity_validation.py` collects 56.
**Non-claims:** no broker I/O, no LIVE operation, no CI run, no commit or merge.

## LIVE request client order id must be an exact UUID (2026-10-23)

`ApprovedExecutionRequest` now rejects an `ExecutionMode.LIVE` request whose
`order.client_order_id` is not exactly `uuid.UUID`; non-LIVE modes are unchanged.
Global `Order` tightening remains tracked by [#271](https://github.com/jignesh2795/QuantX/issues/271).
**Non-claims:** no broker I/O, LIVE operation, or global `Order` tightening.

## LIVE prerequisite declarations require exact booleans (2026-10-23)

`ExecutionOrchestrator.execute()` now proceeds past the LIVE `TradingGate.is_durable` and `ApplicationRuntime.started` prerequisites only on exact `True`; a real `False` keeps its existing reason, while any other value (for example `"false"`, `1`, `None`, or a bool-like such as `numpy.bool_`) returns `BLOCKED` with a distinct fixed reason. `is True` intentionally rejects bool-likes. Check order, signatures, serialization, fingerprints, schema, adapters, recovery, and non-LIVE behavior are unchanged. Highest-priority remaining LIVE probe truthiness finding: `broker.health()` at `execution.py:801`, tracked as [#269](https://github.com/jignesh2795/QuantX/issues/269).

Local validation on branch `fix/live-prerequisite-exact-bools-v1` (base `23018ab`): full suite **2,773 passed, 1 skipped**; focused execution file **113 passed**; Ruff check/format, strict mypy and `git diff --check` pass. **Non-claims:** no composition root, broker I/O, LIVE operation, or CI run.

## LIVE risk limits require explicit values (2026-10-23)

`require_live_risk_limits` rejects LIVE limits unless per-order notional, per-symbol position notional, daily loss and maximum snapshot age are explicit exact positive `Decimal`/`timedelta` values; bools, ints, floats, strings, non-finite values, subclasses and duck types are rejected without coercion, and errors name fields only. `LivePreTradeRiskEvaluator` validates at construction, stores a copy, requires exact provider inputs and delegates unchanged to `PreTradeRiskEngine`; it reads no clock. `RiskLimits` defaults/`__post_init__` and non-LIVE behavior are unchanged. Report-only gaps: daily loss remains realized-only ([#266](https://github.com/jignesh2795/QuantX/issues/266)); arbitrary evaluator callables remain injectable until the composition root ([#267](https://github.com/jignesh2795/QuantX/issues/267)).

Local validation on branch `fix/live-require-risk-limits-v1` (base `ccab47de`): full suite **2,764 passed, 1 skipped**; Ruff check/format and strict mypy pass. **Non-claims:** no CI, no broker I/O, no LIVE operation, no composition root.

## LIVE session guard and trading gate results fail closed (2026-10-23)

`ExecutionOrchestrator.execute()` now validates LIVE injected callback results instead of truth-testing them. A session guard result that is not an exact `SessionGuardResult` with a bool `allowed` and string `reason` returns `BLOCKED` with reason `live session guard returned an invalid result`; valid denials keep the guard's reason. `TradingGate.allow()`, `submission_permit()` and `admit_submission()` proceed only on exact `True`; invalid non-bool values return `BLOCKED` with reason `live trading gate returned an invalid result` before broker contact, and before reservation except at the admission boundary, where the existing pending reservation remains for reconciliation. PAPER/SHADOW/REPLAY/BACKTEST behavior, signatures, schema, fingerprints, adapters, recovery and existing reason strings are unchanged. Regression coverage includes string, integer, wrong-type and non-string-reason session results, plus truthy non-`True` gate values.

Local validation on branch `fix/live-callback-truthiness-v1` (base `20af647c`): full suite **2,714 passed, 1 skipped**; Ruff check/format and strict mypy pass. **Non-claims:** no CI, no broker I/O, no LIVE operation.

## LIVE risk evaluator malformed results fail closed (2026-10-23)

`ExecutionOrchestrator.execute()` now validates the configured LIVE risk evaluator's result in the existing fail-closed handler. Values that are not `RiskResult` or that carry a non-`RiskDecision` decision or non-string reason return `BLOCKED` with reason `live pre-trade risk evaluation returned an invalid result` before any permit, reservation, or broker contact. Evaluator exceptions, valid non-APPROVE decisions, and all other execution modes are unchanged; no signatures, schema, fingerprints, adapters, or recovery code changed. Regression coverage: `None`, plain string, object without decision, wrong decision type, and non-string reason, each with zero permits/reservations/submits.

Local validation on branch `fix/live-risk-evaluator-malformed-result-v1` (base `3285092a`): full suite **2,704 passed, 1 skipped**; Ruff check/format and strict mypy pass. **Non-claims:** no CI, no broker I/O, no LIVE operation.

## LIVE execution requires a pre-trade risk evaluator — fail-closed guard (2026-10-23)

`ExecutionOrchestrator.execute()` now returns `BLOCKED` with reason `live execution requires a configured pre-trade risk evaluator` for `ExecutionMode.LIVE` when no evaluator is configured. The check sits with the other LIVE composition prerequisites, before any gate permit, idempotency reservation, or broker contact. PAPER/SHADOW/REPLAY/BACKTEST behavior, signatures, serialization, SQLite schema, fingerprints, broker adapters, and recovery are unchanged; a configured evaluator keeps its existing fail-closed exception and non-APPROVE handling. Regression coverage: LIVE without an evaluator blocks with zero gate permits/reservations/submits; evaluator REJECT blocks with zero submits; approving evaluator still executes; PAPER without an evaluator still executes.

Local validation on branch `fix/live-require-risk-evaluator-v1` (base `8f86f8f8`): full suite **2,699 passed, 1 skipped**; Ruff check/format and strict mypy pass. **Non-claims:** no GitHub Actions or paid CI, no broker I/O, no LIVE operation, and no production LIVE composition readiness claim.

## QX-08 v3.2.0 acceptance reconciliation — complete (2026-10-16)

PR [#234](https://github.com/jignesh2795/QuantX/pull/234) merged the final acceptance-evidence slice as merge commit `fe832fc21b5e714b3e1827a94e381cf84bb43746`, preserving the validated feature commit `9bd0d0e8fe983e3f415d97aed205a5175447635b` in history. The patch changes only `tests/unit/application/test_backtest.py` and `tests/unit/application/test_strategy_rehearsal.py`; no production code changed.

Exact-feature-HEAD validation was operator-reported at `9bd0d0e8fe983e3f415d97aed205a5175447635b`: focused suite **191 passed**; full suite **2,028 collected, 2,027 passed, 0 failed, 1 known optional-Dhan-extra skip**; Ruff check and format check passed for both changed files; strict mypy for `backtest.py` passed; `git diff --check` was clean. These are local results, not GitHub Actions or paid-CI results. No broker/LIVE operation was performed.

### QX-08 v3.2.0 acceptance-matrix traceability (T1–T8; G1–G3)

- **T1 / G3 — committed positions and order inventory:** `test_qx08_buy_and_hold_driver_state_and_callback_parity` (paper/backtest post-fill context parity), `test_active_order_persists_into_next_strategy_context_until_terminal_status`, `test_active_order_fact_retains_unknown_and_drops_canonical_terminal`, and the post-commit callback tests assert position facts after accounting and retained order status.
- **T2 — state-derived BuyAndHold:** `tests/unit/strategy/test_reference.py` covers known-empty entry, existing position, accepted/UNKNOWN orders, incomplete inventory, terminal-order retry, per-instrument independence, stateless repeat evaluation, and typed quantity bounds.
- **T3 / T7 — driver parity and repeatability:** `test_backtest_paper_order_sequence_parity`, `test_qx08_buy_and_hold_driver_state_and_callback_parity`, `test_qx08_accepted_without_fill_callback_and_order_inventory_parity`, `test_qx08_buy_and_hold_semantics_repeat_across_fresh_runs`, and deterministic timestamp/order/evidence regression tests cover matching decisions, outcome paths, and repeat runs.
- **T4 / G1 — timer phases and information cuts:** `tests/unit/strategy/test_timers.py` covers equal/past rejection, due-time then timer-ID ordering, uniqueness and end-of-horizon pending timers. The rehearsal/backtest driver suites cover timer dispatch before equal-timestamp cohorts, cohort failure blocking and later continuation, caller-order preservation, prior-only same-instrument history, latency/capability preflight, and current/future mark exclusion through `test_backtest_timer_snapshot_excludes_same_timestamp_mark_and_history`.
- **T4 / G2 — callback commit/error semantics:** `tests/unit/strategy/test_callbacks.py::test_post_commit_dispatch_attempts_all_fills_then_order_update` plus both driver-level `test_postcommit_callback_errors_complete_batch_then_latch_halt` tests assert complete deterministic notification attempts and halt behavior. PR #234 adds `test_qx08_accepted_without_fill_is_preserved_after_order_callback_error` for preserved accepted/submitted no-fill facts and post-commit halt in both drivers, and `test_rehearsal_preserves_future_effective_fill_and_halts_before_callbacks` for the exceptional temporal-integrity path.
- **T5 / G3 — incomplete and point-in-time evidence:** `tests/unit/strategy/test_engine_snapshot.py` covers unavailable/incomplete reasons, UNKNOWN order quantities, future evidence rejection, frozen views and bounded prior-only history; `test_backtest_as_of_observed_with_unusable_mark_stays_incomplete` covers stale marks; PR #234 adds `test_strategy_context_uses_tracker_snapshot_not_financial_state_input` so construction-time financial input is not presented as current account evidence.
- **T6 / T8 — paper-only and no-LIVE/no-broker boundary:** `test_session_rejects_non_paper_deployment`, `test_qx08_backtest_rejects_live_execution_context_for_bound_intents`, and `tests/unit/strategy/test_no_live_boundary.py::test_strategy_seams_have_no_broker_submit_or_scheduler_path` cover the runtime guard and AST boundary.
- **Typed parameters/history cross-cut:** `tests/unit/strategy/test_typed_params.py`, `test_prior_candle_history_rejects_invalid_limits`, and rehearsal history-bound tests cover canonical lexical forms, field-named errors, default-zero history and the 512-bar cap.

The bounded source/test reconciliation now has traceable evidence for every in-scope T1–T8 criterion and G1–G3 invariant. The parent Strategy Platform Flow path remains separate and out of QX-08 scope; no LIVE strategy execution, external scheduler, second accounting/lifecycle subsystem, or risk/execution-recovery redesign is introduced.


## QX-06 multi-leg design decision — accepted (2026-10-16)

[ADR-010: Composed Multi-Leg Order Workflow Semantics](architecture/adr/ADR-010-composed-multi-leg-order-semantics.md) resolves the architecture choice in issue #195: the first multi-leg vertical is an application-owned, sequential workflow of ordinary single-leg orders, not a native/atomic basket. The ADR defines stable workflow/leg identity, workflow-wide path-risk and margin admission, deterministic leg order, per-leg idempotency, partial-exposure/UNKNOWN handling, durable recovery requirements, and the explicit no-automatic-compensation/no-automatic-retry policy.

**Design only; no multi-leg execution is implemented or enabled.** Implementation is gated on the canonical per-leg product/position-effect decision (#193, now implemented and merged) and the derivative-contract decision (#194, now implemented and merged through PR [#252](https://github.com/jignesh2795/QuantX/pull/252)), plus a bounded trace of existing aggregate-risk, reservation, persistence and recovery seams. If those contracts cannot prove safe aggregate admission and restart/reconciliation, the workflow must fail closed. Native baskets, parallel submission, assumed spread-margin offsets, automatic flatten/hedge, and cross-broker atomicity remain unsupported.

## QX-04 order product and position-effect — implemented and merged (2026-10-20)

[ADR-011: Order Product and Position Effect](architecture/adr/ADR-011-order-product-position-effect.md) settles the canonical contract choice for issue #193: product and position effect are per-order request semantics, not instrument attributes. Product vocabularies, support and compatibility defaults are resolved by the applicable versioned market-pack rules; Dhan adapters translate the resolved approved product to wire values. Position effect distinguishes OPEN, CLOSE, AUTO and absent/not-applicable, with AUTO requiring authoritative position evidence before approval. Fingerprints must include resolved product/effect and relevant rule identity.

**Post-merge status (2026-10-20):** QX-04 implementation is merged via PR [#250](https://github.com/jignesh2795/QuantX/pull/250) as merge commit `9c9852c9de288400fe5436dd120dc57c7c60f31d`. The validated feature head was `906e59195e051656f2723797b32bbb3ad1536c45`. Issue [#193](https://github.com/jignesh2795/QuantX/issues/193) is closed as completed. The validation counts recorded in this section belong to the feature head (and earlier remediation commits), not to the merge commit; they do not prove that the merge commit itself was validated. Statements below that issue #193 remained open until review and merge are historical pre-merge statements, not current status. Non-claims remain explicit: no production-broker end-to-end proof, no LIVE operation, and no GitHub Actions or paid-CI validation.

**Implemented on branch `feat/qx-04-order-product-position-effect-v1`** by commits `c7bc333` and `784be56` plus the remediation commit containing this update. `TradeIntent`/`Order` carry a validated `ProductCode` and `PositionEffect`; `ApprovedExecutionRequest` re-resolves CLOSE/AUTO against bound authoritative `PositionEvidence` and a caller-supplied freshness policy, rejecting forged effective effects, mismatched evidence cuts, stale evidence, and closes that would cross zero. `ProductSelectionPolicy` (market-pack id + rule version) resolves omitted products or fails closed, and LIVE without a resolved product is blocked before the trading gate, reservation, or broker contact. `DhanInstrumentRef` no longer carries `product_type`; Dhan maps only the resolved approved product and rejects an omitted one. Canonical fingerprints, pending-context serialization/recovery, and partial-fill continuation preserve product, effect, and evidence. The reserve-before-submit, idempotency, receipt-validation, durable PENDING/UNKNOWN, and no-automatic-retry guarantees are unchanged.

**Historical pre-merge statement (superseded by the 2026-10-20 merge recorded above):** issue #193 remained open until review and merge. Exact-head validation evidence for the default and Dhan-extra configurations was produced by the repository's read-only gate scripts at the commit containing this update and was reported with the branch; no validation counts are asserted in this file for that commit.

**QX-04 F1–F3 remediation (2026-10-19):** the independently reported blockers are addressed on the same branch without rewriting its prior commits.

- **F1 — control-path tests.** `ProductSelectionPolicy`, `ProductSelectionRule`, `ProductSelectionError`, and the pre-approval resolver now have direct unit coverage for matching, explicit products, omitted products, invalid defaults, duplicate/blank configuration, uncovered markets, and mismatched market-pack/rule identities (`tests/unit/domain/test_product_selection.py`). Orchestration-boundary tests prove resolution precedes risk for strategy preparation and backtest, and that a LIVE unresolved product is blocked in the orchestrator before gate acquisition, idempotency reservation, or broker contact, using gate/idempotency/broker counters rather than internal-helper assertions (`tests/unit/strategy/test_execution.py`, `tests/unit/application/test_backtest.py`, `tests/unit/application/test_execution.py`).
- **F2 — real composition.** One canonical, explicit market-pack configuration now exists at `src/quantx/india/market_pack.py`: `INDIA_EQUITY_PRODUCT_SELECTION` binds market pack `india-equity` and rule version `india-products-v1`. The strategy-rehearsal composition requires and supplies an explicit policy, and the pre-approval resolver binds its identity onto the durable request context. The compatibility default is `CNC` for **India NSE cash equity only**; it is derived from the pre-migration `DhanInstrumentRef.product_type="CNC"` NSE_EQ fixtures and the India product/asset matrix. No compatibility default exists for BSE cash equity, derivatives, currency, or commodity contexts, and none is inferred from instrument identity, symbol, or a mutable broker mapping; those contexts fail closed at resolution. ADR-011 acceptance criterion 7 is claimed only for the documented NSE cash-equity context; the remaining contexts are an explicit, unresolved migration constraint, not a silent default. `DhanInstrumentRef.product_type` remains removed and is not a fallback. Pending-context serialization/recovery preserves the resolved product, pack identity, rule version, effect, and evidence cut (`tests/unit/application/test_pending_reconciliation.py`).
- **F3 — resolution before final risk approval.** `StrategyExecutionPreparer` and `DeterministicBacktestService` resolve product and position effect before risk/policy, evaluate risk against the resolved intent and a `RiskContext` carrying product/effective effect/pack identity/rule version, and build the approved request from those exact immutable values. `ExecutionOrchestrator` and `ExecutionTransactionCoordinator` no longer accept a product-selection policy or resolve anything during submission; LIVE still fails closed for a directly constructed unresolved request. A resolution failure stops approval and every later side effect.
- **Low-severity audit items.** Dhan's adapter-wide product map no longer exposes an unused instrument reference or claims instrument/segment-specific validation; `PositionEvidence.matched` requires a real boolean; OPEN and CLOSE/AUTO enforce the same evidence contract; and fingerprint evidence timestamps canonicalize equivalent instants across UTC offsets while remaining serialization/replay stable.

**QX-04 R1–R4 review remediation (2026-10-20, code commit `209a05a91f4c10178cf5f2e1f754a4a7c42714bf`, base `afebb691aa8ea31b2e85ed57757cb4c9796a3a46`):** the independent source-review findings are addressed on the same branch without rewriting prior commits.

- **R1 — freshness is judged at an explicit approval instant.** `resolve_position_effect` requires a timezone-aware approval instant for CLOSE/AUTO, rejects evidence observed or cut after it, and measures evidence age at it rather than at the evidence cut. `ApprovedExecutionRequest`, `PendingExecutionRecoveryRequest`, and `PendingExecutionContext` carry `position_effect_approval_instant`; the canonical fingerprint includes it; pending-context serialization round-trips it; backtest uses the replay-frame occurrence time and strategy rehearsal the event timestamp.
- **R2 — an absent effect is never a universal default.** `resolve_absent_position_effect` resolves only through a versioned `PositionEffectPolicy`/`PositionEffectRule` (a documented OPEN default or an explicit not-applicable declaration), always binds the pack/rule identity onto the execution context used by risk and the request, and fails closed without a rule. Risk rejects an absent effect resolving to anything but OPEN (with identity) and an explicit OPEN carrying an effective effect.
- **R3 — explicit products require versioned support.** `ProductSelectionPolicy.resolve_explicit` validates an explicit product against the rule's `supported_products`; the India pack's set is derived from the execution-rule matrix (`india_supported_products`: CNC, DELIVERY, MIS for equity) rather than duplicated. An explicit product without a versioned policy now fails closed.
- **R4 — one symmetry contract, one strict decode.** Shared validators enforce order/request product and effect symmetry for approved requests, pending recovery requests, and pending contexts. `PendingExecutionContext.from_json` no longer reconstructs a missing product/effect from the serialized order; pre-remediation CLOSE/AUTO pending payloads that cannot prove their approval instant fail closed at decode instead of inventing one.

Validation at code commit `209a05a` base `afebb691`, produced by the repository's read-only gate scripts in the task worktree: Dhan-extra configuration full suite **2,362 passed, 0 skipped**; default configuration full suite **2,361 passed, 1 skipped** (the expected optional-Dhan skip); changed-file Ruff check and format **PASS (62 changed Python files)**; strict mypy **PASS (196 source files)**; `git diff --check` **PASS**; tracked-worktree integrity **PASS**; `release_check.py` **OVERALL PASS** for the exact head. Evidence: `%TEMP%\opencode\qx04-evidence\validation-209a05a.json`, `pytest-dhan-extra.xml`, `pytest-default.xml`, and `release-209a05a.json`. No GitHub Actions, paid CI, broker I/O, or LIVE order was involved; the release-gate non-claims apply unchanged.

**QX-04 R5–R6 request-boundary proof remediation (2026-10-20, code commit `dd92744c15b5b5f47a60610ef36bfd5ca5af6150`, base `7ee6427`):** the second independent review found that a resolved product or an absent position effect could still be claimed from caller-supplied identity alone, because the approved-request boundary re-derived neither fact from a validated rule.

- **R5 — a resolved product needs a validated selection proof.** `ProductSelectionResolution` is a validated, serializable proof that a versioned policy selected one product for one market, market pack, and rule version. `resolve_request_product` returns it as part of `ProductSelectionResult`; `ApprovedExecutionRequest`, `PendingExecutionRecoveryRequest`, and `PendingExecutionContext` require it for a resolved product and reject a proof whose product, market, market-pack id, or rule version disagrees with the request or its execution context. A proof attached to an absent product, and an explicit product without a proof, both fail closed.
- **R6 — an absent effect needs a validated policy proof.** `AbsentPositionEffectResolution` records the exact market/product scope and the rule that permitted the absence, and it distinguishes a not-applicable rule from a documented OPEN default. `resolve_absent_position_effect` attaches it to the resolution, and the same three request types require it for an absent effect, rejecting a proof that contradicts the request product, the resolved effective effect, the context identity, or an explicitly requested effect. Both proofs participate in the canonical fingerprint and in pending-context serialization, so a pending payload that lost or forged its proof fails closed at decode instead of being recovered on caller identity. `MarketContext` gains one canonical payload codec shared by both proofs.
- **India pack scoping.** `INDIA_EQUITY_POSITION_EFFECT_POLICY` now scopes its not-applicable rule to `CNC` and `DELIVERY`; it has no market-wide rule, and `MIS` has no absent-effect rule, so an absent effect under `MIS` (or under an absent product) fails closed at resolution rather than inheriting the delivery rule. The pack id and rule version are unchanged (`india-equity` / `india-products-v1`).

Validation at code commit `dd92744` base `7ee6427`, produced by the repository's read-only gate scripts at the exact head: full suite **2,382 passed, 0 skipped**; changed-file Ruff check and format **PASS (81 changed Python files)**; strict mypy **PASS (197 source files)**; `git diff --check` **PASS**; tracked-worktree integrity **PASS**; `release_check.py` **OVERALL PASS** for the exact head. Evidence: `%TEMP%\quantx-validation\validation-dd92744c15b5-20261020T110114Z.json` and `release-dd92744c15b5-20261020T110123Z.json`. The optional-Dhan skip did not occur in this environment because the `dhanhq` extra is installed in the task worktree, so the single-skip count recorded for the earlier default-configuration run is not reproduced here. No GitHub Actions, paid CI, broker I/O, or LIVE order was involved; the release-gate non-claims apply unchanged.

**Explicit non-claims for this slice:** the proofs are validated records, not sealed capabilities. The request boundary revalidates each proof against the request, its context, and its recorded effect, but it cannot re-derive provenance against the canonical market pack; enforcement stays at `resolve_request_product` and `resolve_absent_position_effect`, which remain the only producers and both fail closed without a versioned policy. A pending context written before this change cannot prove a product or an absent effect and therefore fails closed at decode instead of being recovered; no production pending rows exist because the branch was not merged at that time. At that time, issue #193 remained open until review and merge (historical; now closed as completed). The provenance limitation named above is addressed by the R7–R9 remediation recorded next.

**QX-04 R7–R9 proof authenticity remediation (2026-10-20, code commit `c098f0f3db7c1bd66fe4a1cb455caa44d73c2421`, base `948f824`):** the third independent review found that a proof was still only a claim. `ProductSelectionResolution` carried a caller-supplied support set, `AbsentPositionEffectResolution` was publicly constructible, and neither the request boundary nor the recovery path consulted the canonical policy that owns the rule.

- **R7 — a claim is authenticated by the trusted policy, never by itself.** `ProductSelectionResolution` no longer carries a supported-product set, and a payload can no longer attest to its own support. `ProductSelectionPolicy.verify_resolution` and `PositionEffectPolicy.verify_resolution` re-derive the decision from the trusted, versioned rules: the product must be in the policy's support set for that market, and the absent-effect claim must match the rule scope, the not-applicable declaration, or the documented default the policy actually holds. The new `MarketPackPolicyVerifier` (`src/quantx/domain/policy_verification.py`) selects the trusted policy by the market-pack and rule identity a claim names and fails closed when no trusted policy covers that identity, when the identity or version disagrees, or when the trusted policy does not support the request semantics. It holds no market vocabulary of its own, so no India-specific rule enters the universal core.
- **R8 — the seam is enforced wherever a claim is trusted.** `ExecutionOrchestrator.execute` and `continue_partial`, `ExecutionTransactionCoordinator.execute`, `ExecutionDispatcher.dispatch`, and `PendingExecutionRecoveryRunner` all verify the request's proofs against the verifier the deployment composes, before any trading-gate permit, durable reservation, broker contact, or recovery action. `StrategyExecutionPreparer` and `DeterministicBacktestService` additionally re-derive the claims they built from the very policies that produced them, so a request never leaves the pre-approval seam with a claim its own pack does not support. `ProductionRuntimeConfig`, `build_application_runtime`, and the Dhan host take the verifier as explicit configuration, and `INDIA_EQUITY_POLICY_VERIFIER` publishes the India pack's own trusted policies.
- **R9 — a persisted proof is re-verified, and the stored digest is re-derived.** `PendingExecutionContext.from_json` re-derives the canonical fingerprint from the restored execution semantics and compares it with the stored digest, so a payload whose proof or execution fields were altered while the old digest was kept is rejected instead of recovered; the reservation's independently stored fingerprint is still compared with the payload. A restored context is not canonical until the recovery runner re-verifies its claims against the trusted policies, so a self-consistent fabricated proof fails safely instead of being recovered.

**Adversarial regressions** (`tests/unit/application/test_proof_authenticity.py`, 20 cases): a self-consistent claim naming `NRML` under the India NSE equity pack is rejected; a claim that the pack declares the effect not applicable for `MIS` is rejected; the pack's own `CNC`/`DELIVERY` absent-effect rules still authenticate their claims; a missing proof, a wrong rule version, an unavailable policy, and a claim naming a foreign pack identity all fail closed; a fabricated pending proof is refused by the recovery runner even when its digest was recomputed; a tampered proof or tampered execution field that keeps the old digest is detected at decode; and a plugin-supplied pack for another market authenticates only its own claims. The existing CLOSE/AUTO evidence-freshness, reversal-prevention, receipt-identity, and startup-recovery-readiness regressions are unchanged and still green.

Validation at code commit `c098f0f` base `948f824`, produced by the repository's read-only gate scripts at the exact head: full suite **2,402 passed, 0 skipped**; changed-file Ruff check and format **PASS (94 changed Python files)**; strict mypy **PASS (198 source files)**; `git diff --check` **PASS**; tracked-worktree integrity **PASS**; `release_check.py` **OVERALL PASS** for the exact head. Evidence: `%TEMP%\quantx-validation\validation-c098f0f3db7c-20261020T121439Z.json` and `release-c098f0f3db7c-20261020T121448Z.json`. The optional-Dhan skip does not occur in this environment because the `dhanhq` extra is installed in the task worktree. No GitHub Actions, paid CI, broker I/O, or LIVE order was involved; the release-gate non-claims apply unchanged.

**Explicit non-claims for this slice:** the proofs remain validated records, not sealed capabilities — no signature, capability token, or private constructor is used, and none of them would survive a reload. Authenticity now comes from the trusted, versioned policy the deployment composes: a claim that the trusted policy does not support is refused at every boundary that trusts a claim, and an unavailable or mismatched policy fails closed. A pending context written before this change cannot prove its product or absent effect and therefore fails closed at decode instead of being recovered; no production pending rows exist because the branch was not merged at that time. A market that no trusted pack covers can no longer carry a product, so such a request is refused by the proof seam rather than by the market-policy stage. At that time, issue #193 remained open until review and merge (historical; now closed as completed).

**QX-04 R10 request-proof binding remediation (2026-10-20, code commit `2c0b182fb6517e8312a0a398d53a1981524ad017`, base `e6a2372`):** the bounded follow-up audit found that the verifier authenticated each proof against a trusted policy but did not fully bind the proof to the request semantics it accompanied. A supported product claim for another product or market, an absent-effect claim for another market or effective effect, and a proof attached to an absent product or an explicit effect could still pass the verifier's Protocol seam.

- **R10 — proof authenticity includes request binding.** `MarketPackPolicyVerifier.verify_product_resolution` and `verify_absent_effect_resolution` now require the claim market to equal the execution-context market, in addition to the existing market-pack and rule-version checks. `verify_request` requires `product_resolution.product == request.product`, rejects a product resolution on an absent product, rejects an absent-effect resolution on an explicit effect, and requires `position_effect_policy_resolution.effective is request.effective_position_effect`. A claim that is authentic for its pack but describes different request semantics is refused before any gate, reservation, broker contact, or recovery action.
- **Adversarial regressions** (`tests/unit/application/test_proof_authenticity.py`, 26 cases): six new cases cover the product, market, absent-product, effect-market, effective-effect, and explicit-effect mismatches; each fails closed at the verifier.

Validation at code commit `2c0b182` base `e6a2372`, produced by the repository's read-only gate scripts at the exact head: full suite **2,408 passed, 0 skipped**; changed-file Ruff check and format **PASS (94 changed Python files)**; strict mypy **PASS (198 source files)**; `git diff --check` **PASS**; tracked-worktree integrity **PASS**; `release_check.py` **OVERALL PASS** for the exact head. Evidence: `%TEMP%\quantx-validation\validation-2c0b182fb651-20261020T132241Z.json` and `release-2c0b182fb651-20261020T132309Z.json`.

**Explicit non-claims for this slice:** the change closes the verifier's request-binding gap only; it does not add signatures or capability tokens, does not change the canonical market-pack rules, and does not claim production readiness, broker correctness, LIVE safety, or authenticated CI evidence. At that time, issue #193 remained open until review and merge (historical; now closed as completed).

**QX-04 Dhan host product-map wiring remediation (2026-10-20, directly applied code commit `0ed665c6a99d6137d3c5a8f80575360074f4082c`, base `4621cb5834727a8d01359cea954ec36b47a50073`; corrected by `6d2afe1c3525c3b722fc5df3dcfbd05c9705e274` and `410e98d4392a1742b2b24154de9669d31cbda3ac`):** the P1 review finding was confirmed: the supported `DhanHostConfig` / `build_dhan_host_runtime()` path constructed `DhanBrokerAdapter` without a product map, so every resolved product failed before transport.

- **Explicit host configuration.** `DhanHostConfig` now requires a non-empty `product_map`, validates and freezes it through `normalize_dhan_product_map`, and `build_dhan_host_runtime` passes the normalized map to the adapter. Empty maps, blank keys/values, duplicate normalized keys, and unsupported Dhan wire values fail closed during host config construction, before runtime build.
- **No implicit fallback.** Product translation remains adapter-wide and requires an explicit neutral-to-wire mapping. There is no instrument-symbol, segment, or identity fallback; an omitted product or an unmapped product is rejected before transport.
- **Regression coverage.** `test_host_wires_configured_product_map_through_adapter_submission` uses `InMemoryDhanTransport` and asserts the actual submitted wire product for `CNC` and `MIS` (`CNC` and `INTRADAY`). `test_host_rejects_invalid_product_maps_before_runtime_build` covers empty, blank-key, blank-value, duplicate-after-normalization, and unsupported-wire maps. The follow-up commits add the now-required map to existing R0-B host timeout fixtures and correct changed-file Ruff import ordering, formatting, and the test default-argument lint finding; no behavior was weakened.

Validation at code-fix HEAD `410e98d4392a1742b2b24154de9669d31cbda3ac` base `afebb691aa8ea31b2e85ed57757cb4c9796a3a46`, produced by the repository's read-only gate scripts at the exact head: default configuration full suite **2,414 passed, 1 skipped**; Dhan-extra configuration full suite **2,415 passed, 0 skipped**; changed-file Ruff check and format **PASS (94 changed Python files)**; strict mypy **PASS (198 source files)**; `git diff --check` **PASS**; tracked-worktree integrity **PASS**; `release_check.py` **OVERALL PASS** for both configurations and the exact head. Evidence: `%TEMP%\quantx-validation\qx04-hostfix-0ed665c\validation-410e98d-default-20261020T210949.json`, `release-410e98d-default-20261020T211041.json`, `validation-410e98d-dhan-20261020T211132.json`, and `release-410e98d-dhan-20261020T211223.json`. No GitHub Actions, paid CI, broker I/O, or LIVE order was involved; the release-gate non-claims apply unchanged. **Final feature-head validation (2026-10-20):** the merged feature head `906e59195e051656f2723797b32bbb3ad1536c45` (documentation-only commit on top of code-fix HEAD `410e98d`) was reported validated with default configuration full suite **2,414 passed, 1 skipped** and Dhan-extra **2,415 passed, 0 skipped**; changed-file Ruff check and format **PASS (94 changed Python files)**; strict mypy **PASS (198 source files)**; `git diff --check`, tracked-worktree integrity, and `release_check.py` **OVERALL PASS** in both configurations at that exact head. Evidence: `%TEMP%\quantx-validation\qx04-hostfix-0ed665c\validation-906e591-default-20261020T211413.json`, `release-906e591-default-20261020T211503.json`, `validation-906e591-dhan-20261020T211538.json`, and `release-906e591-dhan-20261020T211632.json`. These results are bound to feature head `906e591`, not to merge commit `9c9852c9de288400fe5436dd120dc57c7c60f31d`; the merge commit was not separately validated. No GitHub Actions, paid CI, broker I/O, or LIVE operation was involved.

**Recorded feature-head validation commands (recovered from the producer console logs):**

```powershell
# Default dependency configuration
uv sync --dev --locked
python .opencode/skills/quantx-validation-gate/scripts/run_validation.py --expected-head 906e59195e051656f2723797b32bbb3ad1536c45 --base origin/main --output "%TEMP%\quantx-validation\qx04-hostfix-0ed665c\validation-906e591-default-20261020T211413.json"
python .opencode/skills/quantx-release-gate/scripts/release_check.py --expected-head 906e59195e051656f2723797b32bbb3ad1536c45 --base origin/main --evidence "%TEMP%\quantx-validation\qx04-hostfix-0ed665c\validation-906e591-default-20261020T211413.json" --output "%TEMP%\quantx-validation\qx04-hostfix-0ed665c\release-906e591-default-20261020T211503.json"

# Dhan-extra dependency configuration
uv sync --dev --extra dhan --locked
python .opencode/skills/quantx-validation-gate/scripts/run_validation.py --expected-head 906e59195e051656f2723797b32bbb3ad1536c45 --base origin/main --output "%TEMP%\quantx-validation\qx04-hostfix-0ed665c\validation-906e591-dhan-20261020T211538.json"
python .opencode/skills/quantx-release-gate/scripts/release_check.py --expected-head 906e59195e051656f2723797b32bbb3ad1536c45 --base origin/main --evidence "%TEMP%\quantx-validation\qx04-hostfix-0ed665c\validation-906e591-dhan-20261020T211538.json" --output "%TEMP%\quantx-validation\qx04-hostfix-0ed665c\release-906e591-dhan-20261020T211632.json"
```

The console logs `validation-906e591-*.log`, `release-906e591-*.log`, `sync-default-906e591.txt`, and `sync-dhan-906e591.txt` record these invocations; the evidence directory is abbreviated as `%TEMP%\quantx-validation\qx04-hostfix-0ed665c\` (the logs contain the expanded local path). At the time of the feature-head run, `origin/main` resolved to `afebb691aa8ea31b2e85ed57757cb4c9796a3a46`, as recorded by the release-gate `command-scope` check. For an immutable replay today, substitute `--base afebb691aa8ea31b2e85ed57757cb4c9796a3a46` in the four producer/release commands above; the `origin/main` form is the exact historical invocation, not an equivalent to today's `origin/main`. These commands and results are bound to feature head `906e591` only and are not evidence for merge commit `9c9852c9de288400fe5436dd120dc57c7c60f31d`.

## QX-05 derivative contract metadata decision — accepted (2026-10-16)

[ADR-012: Canonical Derivative Contract Metadata and Resolution](architecture/adr/ADR-012-derivative-contract-metadata.md) settles the ownership/resolution contract for issue #194. `Instrument` remains the owner of tradable instrument facts; a separate, canonical `Contract` record keyed by stable `InstrumentId` owns derivative underlying, expiry, strike and `OptionType`. The explicit resolution result must combine one canonical instrument with its point-in-time contract and instrument-rule versions/provenance. Options require complete option metadata; futures require underlying and expiry; missing, overlapping or malformed records fail closed.

**Historical pre-implementation statement (superseded by the implementation record below):** at ADR acceptance the code did not implement the decision: `Contract` embedded an `Instrument`, derivative fields were optional, `option_type` was a free string with lowercase spelling preserved, and `VersionedInstrumentRule` carried no derivative contract metadata.

## QX-05 derivative contract metadata — implemented and merged (2026-10-21)

QX-05 was merged through PR [#252](https://github.com/jignesh2795/QuantX/pull/252) as merge commit `5e5ac5a60ca926a877478ac5fcad30c0a03a9cd7`, preserving validated feature head `cfa89ac704e7fd28422eb55355d7fd3760621d02` based on immutable base `bbf572b5aa56c42f9ae06afea1705fcb44d4fbf9`. Issue [#194](https://github.com/jignesh2795/QuantX/issues/194) was closed as completed after the ADR-012 acceptance criteria were implemented and local validation passed at the exact feature head. The merge commit itself was not separately validated.

- **Canonical vocabulary and record.** `OptionType` in `quantx.domain.instruments` is the single CALL/PUT vocabulary, with a strict `parse` boundary for raw source spellings; the India instrument specifications normalize `option_type` once at construction. `Contract` is keyed by the stable `InstrumentId` instead of embedding an `Instrument`, and it requires a derivative asset class, a canonical underlying `InstrumentId` different from the contract instrument, a timezone-aware expiry, a positive `Decimal` strike, and an `OptionType` for options. Futures require underlying and timezone-aware expiry and reject option-only strike/option-type fields; non-derivative instruments carry no contract record.
- **Point-in-time resolution.** `quantx.research.market_rules` adds `VersionedContractMetadata` and `PointInTimeContractCatalog` beside the existing effective-dated rule registry. Duplicate metadata versions for one instrument and overlapping effective windows are rejected at registration; exactly one record may apply at the resolution instant. `PointInTimeInstrumentResolver.resolve_at` composes the canonical instrument, the applicable contract, the instrument-rule version, the contract metadata version and provenance (catalog source, effective-from, resolution instant) into one `InstrumentResolution`. Missing, overlapping, conflicting or malformed records raise `InstrumentResolutionError`; a historical resolution never falls back to current metadata, and contract applicability stays separate from point-in-time tradability (the resolver does not require TRADABLE).
- **Downstream binding.** `RiskContext` consumes the canonical `InstrumentResolution` itself — never a bare `Contract` — so the instrument facts, the selected contract, the instrument-rule version and the contract metadata version/provenance reach risk as one coherent object; `RiskContext.contract` is a read-only projection of that resolution, not a second writable source of truth. Strategy preparation and deterministic replay select the resolution once, pass that exact object into risk and attach the same object to the resulting approved request, with no later unversioned lookup. `RiskResult` carries the resolution it evaluated, and `ApprovedExecutionRequest` fails closed unless it retains that same resolution: a different contract record, metadata version, rule version or effective identity, and a dropped resolution, are all rejected. `RiskContext` also fails closed on a derivative without a resolution, a resolved instrument that contradicts the intent or risk instrument, and a derivative resolution without a contract, metadata version or provenance. `ApprovedExecutionRequest`, `PendingExecutionRecoveryRequest`, the canonical request fingerprint (`identity_payload`: instrument facts, contract, rule/contract versions and provenance), `PendingExecutionContext` serialization/recovery with digest re-derivation on decode, partial-fill continuation, the `MarketPackPolicyVerifier` re-resolution seam and the Dhan adapter preflight all carry and validate the selected contract/rule identity. Missing fields are never recovered by parsing symbols, and serialization is canonical across equivalent decimal scales and UTC offsets, so equivalent resolutions fingerprint identically. The existing notional/margin arithmetic is unchanged and no derivative-specific margin model is introduced.
- **Fail-closed seams.** A derivative intent prepared by the strategy or backtest execution seams without a configured point-in-time resolver never executes; a verifier composed with a resolver rejects a request that omits its resolution; Dhan submission rejects a derivative request without a matching resolved contract or with a resolution that contradicts the mapped instrument; non-derivative behavior is preserved and never fabricates a contract record. Pending contexts are schema version 2 with explicit resolution evidence: pre-QX-05 version 1 rows still decode without a resolution and remain digest-checked, while a version 1 payload that claims a resolution, a version 2 payload missing the field, and a stored resolution that no longer matches its execution semantics are rejected.
- **Acceptance tests.** `tests/unit/research/test_contract_resolution.py`, `tests/unit/domain/test_contract_metadata.py`, `tests/unit/domain/test_risk.py`, `tests/unit/domain/test_instrument_registry.py`, `tests/unit/execution/test_contract_execution_binding.py`, `tests/unit/strategy/test_execution_contract_resolution.py`, `tests/unit/application/test_backtest_contract_resolution.py` and `tests/unit/plugins/dhan/test_adapter_contract_preflight.py`, plus the extended `tests/unit/domain/test_instruments.py`, `tests/unit/india/test_instrument_catalog.py`, `tests/unit/india/test_domain.py` and `tests/unit/india/test_execution_rules.py`, cover ADR-012 acceptance criteria 1–9: lossless metadata round-trips, incomplete/invalid option and future metadata, one canonical `OptionType`, identity-preserving resolution, historical version selection with no fallback, missing/overlapping/duplicate record rejection, risk/request/fingerprint/recovery/Dhan binding, tamper and identity-mismatch rejection, the risk boundary receiving the exact contract metadata version, rule version/effective identity and provenance rather than an equal `Contract`, and unchanged non-derivative and LIVE safety boundaries.

**Limitations.** The verifier authenticates a resolution against the trusted resolver at the resolution's own instant; it does not impose an approval-instant freshness bound, so a caller able to authenticate a superseded record at a past instant would retain that selection (the shipped Dhan wire mapping uses `InstrumentId`, and no derivative execution path is enabled). The risk/request identity binding is one-directional by construction: when the risk result carries a resolution the request must retain exactly that resolution, but a request built outside the risk seam with a risk result that consumed no resolution asserts nothing, and the domain request types cannot determine derivative-ness from an `InstrumentId`, so such a hand-constructed approved request is not independently rejected by the paper engine. A partial-fill continuation keeps the parent request's resolution and fails closed when the fresh risk result evaluated a different identity, so a child is never silently rebound to a re-resolved contract. Composing a resolver makes resolution-less version 1 pending rows fail verification, so such rows require operator closure instead of automatic recovery. `Instrument` facts (tick, lot, multiplier) come from the registry while the rule version and contract metadata are effective-dated: point-in-time selection covers rule and contract records, not retroactive reconstruction of instrument facts.

**Exact-feature-head validation commands and results (feature head `cfa89ac704e7fd28422eb55355d7fd3760621d02`; immutable base `bbf572b5aa56c42f9ae06afea1705fcb44d4fbf9`).** Evidence files were produced by the repository's local validation and release gates and are operator-reported, editable local artifacts—not authenticated CI attestations.

```powershell
# Default configuration
uv sync --dev --locked
python .opencode/skills/quantx-validation-gate/scripts/run_validation.py --expected-head cfa89ac704e7fd28422eb55355d7fd3760621d02 --base bbf572b5aa56c42f9ae06afea1705fcb44d4fbf9 --output "%TEMP%\qx05-remediation-cfa89ac-default.json"
python .opencode/skills/quantx-release-gate/scripts/release_check.py --expected-head cfa89ac704e7fd28422eb55355d7fd3760621d02 --base bbf572b5aa56c42f9ae06afea1705fcb44d4fbf9 --evidence "%TEMP%\qx05-remediation-cfa89ac-default.json" --output "%TEMP%\qx05-remediation-cfa89ac-release-default.json"

# Dhan-extra configuration
uv sync --dev --extra dhan --locked
python .opencode/skills/quantx-validation-gate/scripts/run_validation.py --expected-head cfa89ac704e7fd28422eb55355d7fd3760621d02 --base bbf572b5aa56c42f9ae06afea1705fcb44d4fbf9 --output "%TEMP%\qx05-remediation-cfa89ac-dhan.json"
python .opencode/skills/quantx-release-gate/scripts/release_check.py --expected-head cfa89ac704e7fd28422eb55355d7fd3760621d02 --base bbf572b5aa56c42f9ae06afea1705fcb44d4fbf9 --evidence "%TEMP%\qx05-remediation-cfa89ac-dhan.json" --output "%TEMP%\qx05-remediation-cfa89ac-release-dhan.json"
```

- Default: full suite **2,557 passed, 1 skipped**; changed-file Ruff check/format, strict mypy (197 source files), `git diff --check`, and worktree integrity **PASS**; validation and release gates **PASS**.
- Dhan-extra: full suite **2,558 passed, 0 skipped**; changed-file Ruff check/format, strict mypy (197 source files), `git diff --check`, and worktree integrity **PASS**; validation and release gates **PASS**.
- Changed feature scope against base: **29 files, 28 Python files**. The reported focused QX-05 slice had **189 passed**; those results, as well as the counts above, are tied to feature head `cfa89ac...`, not the merge commit.
- Evidence paths: `%TEMP%\qx05-remediation-cfa89ac-default.json`, `%TEMP%\qx05-remediation-cfa89ac-dhan.json`, `%TEMP%\qx05-remediation-cfa89ac-release-default.json`, `%TEMP%\qx05-remediation-cfa89ac-release-dhan.json`.

No broker I/O, LIVE operation, real order, GitHub Actions or paid CI was used. The resolver is an opt-in composition seam whose effective-dated records are caller-supplied: no production derivative contract catalog, historical backfill, automatic contract discovery, or symbol-derived metadata is shipped. Existing notional/margin arithmetic is unchanged; no derivative-specific margin/charges model is introduced. The resolution binding claims the ADR-012 domain and resolution contract only; it does not claim production derivative readiness or that QX-07 shared-contract migration is complete.

## P0.3 post-submit evidence remediation — implemented and merged (2026-10-18)

P0.3 (issue #241) is implemented on `fix/p03-post-submit-evidence-v1` at feature commit `2cb02ae2100078a3f1e21a3a01d5edbb957c5b75`, based on `main` at `103b7f47ac11813a0d6df9360b2885f9c1b9db1d` (P0.2 integration, PR #244). Changed paths: `src/quantx/application/execution.py`, `src/quantx/execution/submission_preflight.py` (new), `src/quantx/execution/receipts/quarantine.py` (new), `src/quantx/ports/persistence.py`, `src/quantx/persistence/sqlite/submission_quarantine.py` (new), `src/quantx/persistence/sqlite/schema.py`, `src/quantx/persistence/sqlite/__init__.py`, `src/quantx/plugins/dhan/adapter.py`, plus the mirrored regression tests and this documentation.

Local validation was executed by the read-only validation producer (`run_validation.py`) in a detached temporary worktree at the exact feature SHA, with base `103b7f47ac11813a0d6df9360b2885f9c1b9db1d`:

- Default dependency configuration (`uv sync --locked`, then the full producer run bound to the exact head): **OVERALL PASS** — full suite **2,186 passed, 1 skipped** (the known optional-Dhan-extra test); changed-file Ruff check and format **PASS** (10 changed files); strict mypy **PASS**; `git diff --check` **PASS**; tracked-worktree integrity **PASS**.
- Dhan-extra configuration (`uv sync --locked --extra dhan`, then the full producer run again against the same head and base): **OVERALL PASS** — full suite **2,187 passed, 0 skipped**.
- Focused persistence/recovery slice (`tests/unit/persistence` plus recovery, reconciliation, and runtime regression files): **240 passed**.
- Release gate: producer self-test **77 checks PASS**; `release_check.py` against each real producer evidence file reports **OVERALL PASS** for both configurations, with the changed scope vs `origin/main` exactly the 12 intended files. Evidence JSONs and release-gate reports were retained under the local validation temp directory (`%TEMP%\quantx-validation\p03-run1-default.json`, `p03-run2-dhan.json`, plus the two `release-2cb02ae…-*.json` reports).

These are local results produced by the repository's own read-only gate scripts. No GitHub Actions or paid CI was triggered (repository policy), and no broker/LIVE operation was performed. The release-gate PASS does not authenticate evidence files or claim production readiness; the explicit non-claims printed by `release_check.py` apply unchanged.

Follow-up hardening (commit `092f8075f559ef68d78ecdc94444c63187a74d48`, on top of the docs-evidence commit `f869979b1ed7c0342aa15eedb093607de33a5611`): the durable submission quarantine repository is now a mandatory LIVE-admission precondition — LIVE admission fails closed (`live execution requires a durable submission quarantine repository`) before any reservation or broker contact when the composition omits it — and the preflight path now closes a pending reservation through a typed `NotSubmittedResolution` (`NotSubmittedSource.ADAPTER_PREFLIGHT_REJECTION`, `not_submitted_resolutions` table, SQLite schema v8) instead of the previous sentinel `orchestrator:preflight-rejection` operator closure; no human operator identity is recorded or implied, and a not-submitted-resolved reservation can never complete, resolve pending, or be operator-resolved. Validation was re-executed by the read-only producer in a detached temporary worktree at the exact follow-up SHA with base `103b7f47ac11813a0d6df9360b2885f9c1b9db1d`: default configuration **OVERALL PASS** — full suite **2,196 passed, 1 skipped**; Dhan-extra configuration **OVERALL PASS** — **2,197 passed**; focused persistence/execution/plugin slice **902 passed**; release gate producer self-test **77 checks PASS** and `release_check.py` **OVERALL PASS** for both configurations, with the changed scope vs `origin/main` exactly the 23 intended files. Evidence JSONs: `p03f-run1-default.json`, `p03f-run2-dhan.json`, `release-092f807-default.json`, `release-092f807-dhan.json` under the local validation temp directory. Those results remain bound to those exact SHAs only.

Publication sync (merge commit `8f73fb880e324ab346d2f5bbac6f2727413f03db`): the branch was synchronized with `origin/main` at `9d5a69e6035e0b928a1d17f39d8134bc40d347b9` (PRs #245/#246 — skills hardening and validation/release-gate evidence contracts) by a normal non-rewriting merge that preserved the candidate commits above. Main's delta contained no `src/` or `tests/` changes, so the validated P0.3 source and regression tests were unaffected, and the changed scope versus the new base remains exactly the same 23 intended files. All gates were then re-executed with the merged canonical scripts at the exact merge SHA against base `9d5a69e6035e0b928a1d17f39d8134bc40d347b9`: default configuration **OVERALL PASS** — full suite **2,196 passed, 1 skipped**; Dhan-extra configuration **OVERALL PASS** — **2,197 passed**; focused execution/persistence/application/plugin/reconciliation slice **1,481 passed**; producer self-test **24 checks PASS**; release-gate self-test **99 checks PASS**; `release_check.py` **OVERALL PASS** for both configurations with the changed scope exactly the 23 intended files. Evidence and console logs: `%TEMP%\quantx-validation\p03-publication-sync-8f73fb8-v1\` (`validation-default.json`, `validation-dhan.json`, `release-default.json`, `release-dhan.json`).

Malformed-response hardening (commit `1c86dd874b357eae54d28ea3fb6b2a13917e33ad`, on top of the publication-sync tree): the LIVE orchestrator no longer trusts the broker response's runtime shape. `validate_receipt_runtime_shape` (`quantx.execution.receipts.identity`) rejects a response that is not an `ExecutionReceipt`, or whose `outcome`/`order_status`/`receipt_id`/`source`/`fills` hold non-canonical runtime values, before any attribute is trusted or persisted; the outcome is explicit UNKNOWN with a sanitized `MALFORMED_RECEIPT` quarantine observation, the PENDING reservation is kept, and no retry occurs. A residual runtime failure inside request-identity validation is classified the same way, so no malformed response can escape the public execution call after the external submit may have started. Quarantine observation identity tolerates responses without a usable receipt id, and observation reasons are bounded, so a hostile response cannot force the dual-persistence safety-fault latch. Local validation at that exact commit (Python 3.12, `uv`): full suite **2,199 passed, 1 skipped**; focused execution/receipt/idempotency/schema/Dhan slice **196 passed**; `uv run ruff check .` **PASS**; `uv run ruff format --check` **PASS on all changed files** with three pre-existing, unmodified skill-markdown findings (`.opencode/skills/quantx-india-market/references/plugin-registration.md`, `quantx-strategy-plugins/SKILL.md`, `quantx-testing/SKILL.md`) that predate this branch and are reported rather than edited in this slice; strict mypy **PASS, 193 source files** both with the Dhan extra installed and with `dhanhq` absent; `uv sync --locked --dev --extra dhan` and `uv sync --locked --dev` both **PASS** in separate recorded environments; `git diff --check` **PASS**; skills integrity `--check` **PASS (34/34)** and `--self-test` **PASS (11 checks)**; validation-gate self-test **PASS (24 checks)**; release-gate self-test **PASS (99 checks)**. No GitHub Actions, paid CI, network broker call, or LIVE order was involved. Logs were captured outside the repository worktree; this revalidation is local evidence for that exact commit only.

Admission-ordering correction (commit `1b2aec52901b4e8bbb62bcd5662863ad3b1bfcdc`, on top of the malformed-response hardening): the LIVE missing-quarantine check moved from after the broker capability probes to the earliest LIVE admission boundary, beside the other LIVE-only composition prerequisites. A LIVE composition without a durable `SubmissionQuarantineRepository` is now BLOCKED (`live execution requires a durable submission quarantine repository`) before the trading gate is consulted, before market-policy evaluation, before any broker-specific probe (connection identity, health, instrument, capabilities), before any durable reservation exists, and before broker submission; the later redundant guard was removed, so a single boundary enforces the precondition. The move also closes the audited composition window where `submission_quarantine` was checked only after broker `instrument`/`capabilities` calls. Audit hardening accompanying the move: `validate_receipt_runtime_shape` now also requires readable string enum members, so an uninitialized or value-shadowing `StrEnum` instance is rejected as MALFORMED before identity validation and canonical persistence (which reads `.value`); the shape-validator call and outcome read are exception-guarded, so raising attribute access on a hostile response becomes explicit MALFORMED UNKNOWN instead of escaping the public call; quarantine observation extraction reads every broker-supplied field through a non-raising accessor and drops unreadable enum values, so a hostile response is still recorded as sanitized evidence instead of forcing the admission safety-fault latch; and observation identity tolerates a raising `receipt_id`. Tests: the LIVE missing-quarantine regression proves zero broker probes (connection/health/instrument/capabilities), no canonical receipt, no submit, and a pending reservation; new regressions cover a receipt subclass whose `outcome` property raises and a real-but-uninitialized `OrderStatus` member (UNKNOWN, receipt not persisted, `MALFORMED_RECEIPT` observation recorded, gate not latched, replay never resubmits). Changed scope versus base `9d5a69e6035e0b928a1d17f39d8134bc40d347b9` is now 25 files: the publication-sync 23 plus `src/quantx/execution/receipts/identity.py` (first changed by the malformed-response hardening) and `tests/unit/application/test_market_policy.py` (its LIVE test helper now composes the quarantine capability the admission boundary requires). Full gates re-executed at the exact commit against base `9d5a69e6`: default configuration **OVERALL PASS** — full suite **2,201 passed, 1 skipped**; Dhan-extra configuration **OVERALL PASS** — **2,202 passed**; focused execution/persistence/application/plugin/reconciliation slice **1,486 passed**; changed-file Ruff check and format **PASS** (23 changed Python files); strict mypy **PASS**; `git diff --check` **PASS**; producer self-test **24 checks PASS**; release-gate self-test **99 checks PASS**; `release_check.py` **OVERALL PASS** for both configurations with the 25-file changed scope. Evidence and console logs: `%TEMP%\quantx-validation\p03-admission-ordering-1b2aec5-v1\` (`validation-default.json`, `validation-dhan.json`, `release-default.json`, `release-dhan.json`, `focused-slice.log`, `producer-self-test.log`, `release-self-test.log`). These are local results bound to that exact commit only; no GitHub Actions, paid CI, broker call, or LIVE order was involved.

Second publication sync (2026-10-18): the branch was synchronized with `origin/main` at `77c6b4dfb7690b2e7ce2b5cadaa17d030fa0479c` (PR #248, skills-manifest hardening) by a normal non-rewriting merge; `main`'s delta contained no `src/` or `tests/` changes. At that sync point, P0.3 was documented as implemented and locally validated on the feature branch but not yet merged. That pre-merge status was superseded by PR #247's merge on 2026-10-18, recorded below. Prior validation results remain bound to their exact recorded SHAs.

Final candidate validation (2026-10-18, commit `1186474c0532971597e2ff80e519b19b02e04b98`, base `77c6b4dfb7690b2e7ce2b5cadaa17d030fa0479c`): a focused safety-wording correction on top of the second publication sync changed no execution behavior — the submit-admission denial texts now state "before `broker.submit()`" (and "never called") instead of "before any broker contact", explicitly acknowledging that the read-only connection/health/instrument/capability observations in `execute` may already have run; `NotSubmittedResolution` records a local outcome proven without transport I/O; the admission-denial regression now uses the counting probe broker and asserts the probes ran while submit never happened; and the stale post-merge P0 status rows (architecture-56 remediation table, STATUS heading) were reconciled to "implemented on this branch, open in `main`". The read-only validation producer then ran in a detached temporary worktree at that exact head. Default configuration **OVERALL PASS** — full suite **2,201 passed, 1 skipped**; Dhan-extra configuration **OVERALL PASS** — **2,202 passed**; focused execution/persistence/application/Dhan slice **314 passed** (default) and **340 passed** (Dhan-extra, including transport and lifecycle goldens); changed-file Ruff check and format **PASS** (23 changed files); strict mypy **PASS**; `git diff --check` **PASS**; producer self-test **24 checks PASS**; release-gate self-test **99 checks PASS**; `release_check.py` **OVERALL PASS** for both configurations against that exact head. Evidence: `%TEMP%\quantx-validation\validation-1186474c0532-*.json` and `release-1186474c0532-*.json`. Local results bound to that exact commit; no GitHub Actions, paid CI, broker call, or LIVE order was involved.

**Final exact-tip validation and merge (2026-10-18):** the published final tip `7f77a0161a3c5f9be408abe2f8435436663ca46c` (documentation-only commit on top of behavior-corrected candidate `1186474c0532971597e2ff80e519b19b02e04b98`) was reported validated against base `77c6b4dfb7690b2e7ce2b5cadaa17d030fa0479c`. The read-only validation producer and release gate reported **OVERALL PASS** in both dependency configurations: default full suite **2,201 passed, 1 skipped**, and Dhan-extra **2,202 passed, 0 skipped**. The final exact-tip report gives focused counts of **314 passed** for the default focus and **304 passed** for the Dhan adapter/transport/golden focus; earlier focused results of 314/340 remain evidence bound to `1186474` and are not substituted for the final report's focused count. Changed-file Ruff check/format (23 Python files), strict mypy, `git diff --check`, worktree integrity, producer self-test (24 checks), release-gate self-test (99 checks), and both release gates were reported PASS. Evidence JSONs are local and editable, not cryptographically authenticated runner attestations. PR [#247](https://github.com/jignesh2795/QuantX/pull/247) merged using the expected-head guard as commit `d19782a0bff7398127b2738ff9878c53bff7169f`; issue [#241](https://github.com/jignesh2795/QuantX/issues/241) closed automatically. No GitHub Actions or paid CI, broker I/O, or LIVE orders were used; no production/LIVE-readiness claim is made. This paragraph records operator-reported local evidence and the merge, not a new source-level validation run.

Implemented behavior:

- **Fail-closed post-submit persistence.** In `ExecutionOrchestrator._execute_live_transactional`, failures of `unit_of_work.receipts.save(receipt)` or of the surrounding unit-of-work commit boundary after the broker may have accepted now return an explicit UNKNOWN result (never an escaped exception implying a known outcome, never a fabricated success), leave the PENDING idempotency reservation unresolved, and never automatically retry or resubmit.
- **Durable non-authoritative quarantine evidence.** A separate `SubmissionQuarantineRepository` port (`quantx.ports.persistence`) with the SQLite implementation (`SqliteSubmissionQuarantineRepository`, `submission_quarantine` table, introduced in schema v7; the database schema is v8 after the not-submitted table) records sanitized, typed observations for transport-uncertain submissions, broker-UNKNOWN receipts, identity-rejected receipts, and receipt-persistence failures. Observations carry client-order identity, request correlation, source/adapter identity, observed broker order id, observed outcome/status vocabulary values, observation timestamp, typed reason category, and a deterministic idempotent observation identity. Untrusted fields are type- and length-validated before serialization; secrets, tokens, raw transport payloads, and unsanitized exception messages are never stored. Quarantine records never complete idempotency, never become canonical receipts, and never affect accounting or lifecycle facts, and they survive database close/reopen.
- **Typed preflight boundary (NOT_SUBMITTED vs SUBMISSION_UNKNOWN).** `DhanBrokerAdapter.submit()` proves its connection, instrument, market, and wire-request validation happens before `_transport.submit()` by raising the typed `BrokerPreflightRejected` (`quantx.execution.submission_preflight`, a `ValueError` subclass). The orchestrator reports a known local BLOCKED rejection — never an ambiguous remote UNKNOWN — and durably closes the pending reservation through the typed `NotSubmittedResolution` contract (`not_submitted_resolutions`, SQLite schema v8; never a human operator identity, never a fabricated receipt, no retry); a replay of a closed reservation is a known local block and never resubmits. If the durable closure cannot be persisted, the outcome stays conservatively unresolved. All other post-admission failures remain SUBMISSION_UNKNOWN. This resolves the sequencing conflict between issue #241 (requires the distinction now) and architecture record 56's F6 (later slice): the preflight boundary is delivered here, and F6's remaining non-preflight scope (strategy-intent identity, pending-recovery ordering) stays deferred.
- **Mandatory quarantine for LIVE admission.** A LIVE composition without a durable `SubmissionQuarantineRepository` is blocked at the earliest LIVE admission boundary — before the trading-gate evaluation, market-policy evaluation, any broker probe (connection identity, health, instrument, capabilities), any durable reservation, and any broker contact — so an uncertain post-admission outcome can never lack a durable evidence path; the pre-existing in-orchestrator evidence recorder additionally fails closed (latching the trading-gate safety fault) if it is ever reached without a store. Non-LIVE (paper/shadow/replay) flows do not require quarantine.
- **Malformed-response boundary.** The broker response is untrusted plugin-boundary data. A response outside the canonical receipt contract (wrong runtime type, non-canonical enum values, uninitialized or value-shadowing enum members whose `value` is unreadable or not a string, non-UUID receipt id, non-string source, non-tuple fills) is never persisted, never completes idempotency, and never affects accounting; it returns UNKNOWN, keeps the PENDING reservation, and records a sanitized `MALFORMED_RECEIPT` quarantine observation. Raising attribute access on a hostile response object is converted to the same MALFORMED classification instead of escaping the public call, and a raising `receipt_id` cannot fail the observation identity. Because the observation identity and reason are bounded and every extracted field is read defensively, a malformed response does not by itself trip the admission safety fault.
- **Safety fault on dual persistence failure.** When canonical receipt persistence and quarantine evidence persistence both fail, the orchestrator reuses the durable trading-gate fault semantics (`DurableTradingGate.block`, with its process-local fail-closed latch when the durable write also fails) so further submission is disabled pending reconciliation; the uncertainty is still reported as UNKNOWN.
- **Preserved valid-receipt behavior.** The existing regression `test_sqlite_completion_failure_is_unknown_with_pending` behavior is retained: a valid receipt stays durable when idempotency completion fails, the reservation stays pending, and replay never resubmits; the receipt and reservation state remain understandable after reopen.

Non-claims: no real broker I/O, no LIVE operation, and no GitHub Actions were used; all regression coverage is deterministic and offline. Quarantine evidence is reconciliation input only; no automated reconciliation behavior consumes it yet. The quarantine store is a mandatory LIVE-admission dependency: LIVE compositions without it are blocked before any reservation or broker contact rather than degrading to UNKNOWN-plus-pending-reservation without durable evidence; non-LIVE flows are unaffected.

## Quarantine evidence worklist — implemented and merged (2026-10-22)

The bounded read-only quarantine evidence worklist is implemented and merged in PR [#255](https://github.com/jignesh2795/QuantX/pull/255) as merge commit `a4d27955c56f2a49fec1f1593d0a806d25588766`, preserving validated feature head `4acdce19e4d25d2be4c1c2caf27b2542714ae1e4`. The cumulative change is 17 files against base `0e14395e0c04f2d06cf8db7262ff8e0c906b0237`; the full contract is in [implementation/quarantine-evidence-worklist.md](implementation/quarantine-evidence-worklist.md) and is not duplicated here.

- **Bounded read-only operator view.** `QuarantineWorklistReadService` presents quarantined observations with a caller-bounded page limit, deterministic `(observed_at, observation_id)` ordering, and an opaque single-pass continuation cursor. It only reads: no acknowledgement, resolution, retry, receipt, idempotency, trading-gate, or lifecycle state is created, updated, or consumed.
- **SQLite payload-integrity checks.** Stored payloads are measured and read as bytes, so SQLite TEXT semantics cannot stop at an embedded NUL; the per-row payload bound and the per-scan row bound fail closed as `UNAVAILABLE`, and embedded NUL, invalid UTF-8, and over-bound payloads are rejected instead of being decoded from a truncated prefix.
- **Logical identity and cursor hardening.** Ordering, duplicate detection, and cursor anchors use the canonical 128-bit UUID identity rather than an object's `str()` rendering, so duplicate logical observations — including legacy and noncanonical UUID renderings — return `UNAVAILABLE`, and a `UUID` subclass cannot bypass uniqueness or break cursor attribution between pages.
- **Unicode display neutralization.** Operator-facing text escapes control characters, bidi controls, and every invisible Unicode format character (category `Cf`, including U+200B, U+2060, and U+FEFF) while retaining ordinary printable Unicode and the script-joining ZWNJ/ZWJ.
- **Regression coverage.** Real-SQLite persistence tests plus worklist and renderer tests cover embedded-NUL and oversized payloads, duplicate and legacy identities, UUID subclass renderings, cursor traversal, maximal valid payloads, immutable evidence rows, and the absence of broker or network imports.

Reported exact-feature-head local validation (read-only producer and release gate, feature head `4acdce19e4d25d2be4c1c2caf27b2542714ae1e4`, base `0e14395e0c04f2d06cf8db7262ff8e0c906b0237`): default configuration **OVERALL PASS** — full suite **2,663 passed, 1 skipped** (the known optional-Dhan-extra test); Dhan-extra configuration **OVERALL PASS** — **2,664 passed, 0 skipped**; the matching validation-gate and release-gate reports passed for both configurations. These results apply to the feature head, are local and operator-reported, and are not GitHub Actions or authenticated CI evidence; the merge commit itself was not separately validated.

Limitation: the worklist is a bounded inspection view over one readable snapshot, intended for manual reconciliation pending a separately authorized operator action. It is not automated reconciliation, not complete-inventory monitoring at arbitrary table sizes, and not a production-certification or LIVE-readiness proof; quarantine evidence remains reconciliation input only.

## QX-07 package-boundary slice 1 — implemented and merged (2026-10-22; slice-one state, superseded by slices 2A/2B)

The first bounded slice of issue [#181](https://github.com/jignesh2795/QuantX/issues/181) is implemented and merged in PR [#257](https://github.com/jignesh2795/QuantX/pull/257) as merge commit `7b41c230bbd5bcaf4036aca8fc9015c5dee7f7a2`, preserving validated feature head `081c31c882057277badba6084b2312ae8c810631` (validation base `fdf5bc45281e6635530a09b17d7329029403efe2`). The slice is 10 files (5 production, 5 test) and stays inside the dependency-direction audit recorded in [architecture/56-live-execution-safety-audit-and-priority.md](architecture/56-live-execution-safety-audit-and-priority.md) and the dependency rules in [architecture/02-dependency-rules.md](architecture/02-dependency-rules.md); the audit itself is not duplicated here.

This section records the state at the slice-one merge. The slice 2A section below records the current boundary state and supersedes the follow-up wording here.

- **Broker capability contracts moved to the ports boundary.** `BrokerCapability`, `BrokerConnectionRef`, `CapabilitySet`, `BrokerDescriptor`, and `BrokerAdapter` now canonically live in `quantx.ports.broker` beside `BrokerPort`. `quantx.integrations.brokers` remains an identity-preserving compatibility export, so the old and new import paths resolve to the same objects rather than to a second definition.
- **Runtime `ports -> execution` imports removed.** Port modules reference canonical execution records only in postponed annotations, so `quantx.ports` no longer imports `quantx.execution` at runtime.
- **`OperatorResolutionAction` ownership moved to the persistence port.** The enum is defined once in `quantx.ports.persistence`; the legacy `quantx.execution.idempotency` import path, the `CLOSE_UNRESOLVED` default at the application, port-protocol, and SQLite boundaries, and the persisted `CLOSE_UNRESOLVED` value are unchanged.
- **Import-boundary regression added.** `tests/unit/architecture/test_import_boundaries.py` builds a deterministic AST package import graph that separates runtime from `TYPE_CHECKING` imports, reports offending edges with `file:line`, enforces an explicit allowed-edge matrix, registers deferred dependencies with owning issue, reason, and removal condition, asserts `domain` has no outbound package edges, and self-tests cycle detection against a synthetic cycle.

Reported graph at the slice-one feature head: **198 source modules**, **431 intra-QuantX import-statement edges** (**426 runtime**, **5 type-only**), **zero runtime package cycles**, and **zero outbound `domain` edges**.

Reported exact-feature-head local validation (read-only producer and release gate, feature head `081c31c882057277badba6084b2312ae8c810631`, base `fdf5bc45281e6635530a09b17d7329029403efe2`): focused architecture/compatibility/execution/persistence suite **64 passed**; default configuration **OVERALL PASS** — full suite **2,678 passed, 1 skipped**; Dhan-extra configuration **OVERALL PASS** — **2,679 passed**; Ruff check and format passed for the **10 changed files**; strict mypy passed for **199 source files**; `git diff --check` was clean; and the supporting worktree/scope integrity checks, skill-integrity and trigger-asset checks, validation- and release-gate self-tests, and both configuration release gates passed. These results apply to the feature head, are local and operator-reported, and are not GitHub Actions or authenticated CI evidence; the merge commit itself was not separately revalidated.

**At the slice-one merge, issue #181 remained open**; this slice did not satisfy its full acceptance criteria. Boundaries recorded at that point:

- Runtime `india -> research` and `strategy -> research` edges were explicitly registered follow-ups; the India historical normalizer and the strategy replay evaluation were deliberately not relocated in this slice. Slice 2A subsequently removed both runtime edges and relocated those responsibilities.
- `ports -> execution` remains a declared type-only dependency, pending the canonical-record ownership decision or a successor ADR.
- Canonical receipt/outcome, idempotency/recovery, and quarantine records were not relocated or duplicated.
- `persistence -> research` remains permitted because the research package owns the related repository protocols.
- No SQLite schema, payload format, broker runtime behavior, transaction semantics, reconciliation, startup-readiness, risk-gate, or LIVE behavior change is claimed.

See the slice 2A section below for the current status of these boundaries.

## QX-07 package-boundary slice 2A — implemented and merged (2026-10-22)

The second bounded slice of issue [#181](https://github.com/jignesh2795/QuantX/issues/181) is implemented and merged in PR [#259](https://github.com/jignesh2795/QuantX/pull/259) as merge commit `a5b35eb6a8701a4ffa4a905860b38ef99000f1c7`, preserving validated feature head `fcd93eb3c7a928acf33ff4741714e773109722ac` (validation base `69c78ee62a2ff757cc1c8af38fc0379dce574310`). PR #259 changed only the audited 15-path allowlist (14 diff entries including one rename). This documentation-only status reconciliation records the post-merge state; it does not re-run or reinterpret the feature-head validation.

- **India historical normalization moved to research ingestion.** `IndianHistoricalOHLCVNormalizer` was removed from `quantx.india`; `quantx.research.ingest.CatalogOHLCVNormalizer` now performs catalog-resolved canonical OHLCV normalization with injected `InstrumentRegistry`. No compatibility shim remains.
- **Replay-frame adaptation moved to the application boundary.** `event_from_replay_frame` and `evaluate_replay_frame` now live in `quantx.application.replay`; `StrategyEvaluationService` and `quantx.strategy.evaluation` no longer import `quantx.research.replay`. Backtest and replay tests use the application API.
- **Runtime dependency removal.** The `india -> research` and `strategy -> research` runtime edges are gone. Reported feature-head graph: **198 source modules**, **431 intra-QuantX import-statement edges** (**426 runtime**, **5 type-only**), and **zero runtime package cycles**. The all-edge package graph still contains the known type-only `execution <-> ports` cycle.
- **Operator-reported feature-head validation.** At `fcd93eb3c7a928acf33ff4741714e773109722ac`, default configuration full suite: **2,681 passed, 1 skipped** (the known optional-Dhan-extra test); Dhan-extra configuration: **2,682 passed**; focused suite: **310 passed**; changed-file Ruff check and format: **PASS (10 changed Python files)**; strict mypy: **PASS**; `git diff --check` and tracked-worktree integrity: **PASS**; validation and release gates: **PASS** for both configurations. Evidence: `%TEMP%\quantx-validation\qx07-slice2a-release-v1\validation-default.json`, `validation-dhan.json`, `release-check-default.json`, and `release-check-dhan.json`. These are local, operator-reported results, not GitHub Actions or authenticated CI evidence. The merge commit `a5b35eb6a8701a4ffa4a905860b38ef99000f1c7` was not separately revalidated; feature-head evidence does not prove the merge commit was validated.
- **Issue #181 remains open.** Slice 2A does not close it: the known type-only `execution <-> ports` package cycle remains and the Slice 2B ownership decision is unresolved. This record does not claim a zero-cycle all-edge graph or full QX-07 acceptance.

## Current state (dated snapshot as of 2026-10-23) — P0.1/P0.2/P0.3 fixed and merged; QX-04/QX-05 implemented and merged; QX-06 design accepted; QX-08 acceptance complete; QX-09 complete; quarantine evidence worklist merged; QX-07 package-boundary slices 1 and 2A merged; Slice 2B candidate at a5219cf... reviewed and represented by PR #261 (open and unmerged as of 2026-10-23); issue #181 open

The consolidated LIVE-safety audit is recorded in [architecture/56-live-execution-safety-audit-and-priority.md](architecture/56-live-execution-safety-audit-and-priority.md). Its source analysis is a historical snapshot at `2ce04cf40952124e8b2ef0414cbc4ded9d660292`, not current `main`.

**Current remediation status (2026-10-22):**
- **P0.1 / #239 — durable kill-switch and submit-admission race:** closed; fixed and merged in PR [#243](https://github.com/jignesh2795/QuantX/pull/243), merge `6692731e1bcffddcfb189bce8b49d8ab351fdfb2`.
- **P0.2 / #240 — startup readiness with unresolved recovery:** closed; fixed and merged in PR [#244](https://github.com/jignesh2795/QuantX/pull/244), merge `103b7f47ac11813a0d6df9360b2885f9c1b9db1d`.
- **P0.3 / #241 — post-submit receipt/persistence uncertainty:** closed; implemented and merged in PR [#247](https://github.com/jignesh2795/QuantX/pull/247), merge `d19782a0bff7398127b2738ff9878c53bff7169f`; final published head `7f77a0161a3c5f9be408abe2f8435436663ca46c`; see the P0.3 section above.
- **QX-04 / #193 — order product and position effect:** closed as completed; implemented and merged in PR [#250](https://github.com/jignesh2795/QuantX/pull/250), merge `9c9852c9de288400fe5436dd120dc57c7c60f31d`; validated feature head `906e59195e051656f2723797b32bbb3ad1536c45`; see the QX-04 section above. Validation counts there belong to the feature head, not the merge commit; no production-broker end-to-end proof, LIVE operation, or GitHub Actions/paid-CI validation is claimed.
- **QX-05 / #194 — derivative contract metadata:** implemented and merged via PR [#252](https://github.com/jignesh2795/QuantX/pull/252), merge commit `5e5ac5a60ca926a877478ac5fcad30c0a03a9cd7`; validated feature head `cfa89ac704e7fd28422eb55355d7fd3760621d02` against base `bbf572b5aa56c42f9ae06afea1705fcb44d4fbf9`; issue closed as completed. Validation counts belong to the feature head, not the merge commit; no GitHub Actions/paid-CI validation, broker I/O, or LIVE operation is claimed.
- **QX-07 / #181 — package-boundary cleanup:** slices 1 and 2A merged via PRs [#257](https://github.com/jignesh2795/QuantX/pull/257) and [#259](https://github.com/jignesh2795/QuantX/pull/259); the Slice 2B candidate at `a5219cf...` has been reviewed and is represented by PR [#261](https://github.com/jignesh2795/QuantX/pull/261), which was open and unmerged as of the 2026-10-23 snapshot; issue #181 remains open. At the main-branch state captured by this snapshot, the all-edge graph still contains the type-only `execution <-> ports` package cycle because the Slice 2B candidate had not yet merged. See the slice 2A section above.

The audit distinguishes source-confirmed findings at its historical baseline from F1/F2 failure injections reported by the first audit and claims that require broader proof. Do not read the pre-fix P0.1/P0.2 narratives as current behavior.

**Post-merge local validation checkpoint — skills hardening (2026-10-18):** operator-reported validation at exact merge commit `9d5a69e6035e0b928a1d17f39d8134bc40d347b9`, using historical first parent `103b7f47ac11813a0d6df9360b2885f9c1b9db1d` as the release-gate base. Dhan-disabled full pytest: **2,176 passed, 1 skipped, 1 warning**; Dhan-enabled full pytest: **2,177 passed**. Changed-file Ruff check/format, strict mypy (190 files), diff checks, validation producer, release gates in both configurations, skill manifest (34/34), skills self-test (11 checks), trigger evaluator/self-test, and validation/release gate self-tests (24/24 and 99/99) were reported passing. These are local results, not GitHub Actions/paid-CI evidence; no broker/LIVE operations were performed. The detailed report and JSON evidence remain local to the operator's machine and are not committed.

PR #221 merged QX-09 from `feat/qx-09-market-pack-checks-v1` at validated head `7793646e0e3d210e81364d39605ee3383e434723` as merge commit `1e4ebf4f4671e90dcdcafc1cda578182ab39d58b`. The PR covers 15 focused files (+5,746/−229); local validation was reported at the exact feature head, and no GitHub Actions results are claimed. Repository Actions are disabled by project policy.

PR #224 merged QX-08 M1 from `feat/qx-08-m1-engine-truth-context-v1` at validated feature head `0e9dd86401dae244b0c2546af528211a7039346d` as merge commit `8f1cc49c143fd5ee866be81fe366763700db1ac5` on 2026-10-16. M1 establishes immutable `StrategyContext` inputs, engine evidence/snapshot types, strict `TypedParams`, prior-only candle history, `EventTimeSupport` preflight contracts, and T8 no-LIVE boundary coverage. It does not implement callback/timer dispatch or paper/backtest driver wiring; those remain later QX-08 phases.

Exact-head OpenCode local validation at the PR feature head reported 1,945 passed, 0 failed, and 1 skipped (the known optional-Dhan-extra test); the focused strategy/application/execution/research set had 1,408 passed. Changed-file Ruff check and format check passed on the 12 intended paths, strict mypy passed on the seven changed production files, and `git diff --check` was clean. No GitHub Actions or paid CI result is claimed.

PR #226 merged QX-08 M2 from `feat/qx-08-m2-callback-timer-v1` at validated feature HEAD `75f8b0e2858d1ba11d1e7cd3c32f2fc6a6c2df1e` as merge commit `e150350ce747f88845227a70c35a9f94c8e7cd83` on 2026-10-16. M2 adds timer-request validation and deterministic timer/callback dispatch in rehearsal and StrategyEvaluationService backtests, with explicit precommit/postcommit failure semantics, event-time guards, retained active-order evidence, and T8 no-LIVE checks. Exact-HEAD local validation at the feature SHA was reported as 1,988 passed, 1 skipped, 0 failures/errors (1,989 collected); 1,451 focused strategy/application/execution/research tests passed; 21 T8/timer/callback/legacy-clock checks passed; Ruff format/lint and strict mypy on nine production files passed; and `git diff --check` was clean. The formatter-only commit `75f8b0e` was reported AST-identical across all seven touched Python files. This is operator-reported local validation; no GitHub Actions or paid CI result is claimed.

PR #229 merged QX-08 M3 from `feat/qx-08-m3-buy-and-hold-typed-bounds-v1` at validated feature HEAD `ebc67365ce589e50b0477de1b790885b4916c3e7` as merge commit `6f84259b8e6281576eead0831082067283baddeb` on 2026-10-16. M3 removes BuyAndHold's private entry state and derives BUY/HOLD decisions from engine position/order evidence, fails closed when inventory evidence is unavailable/incomplete or a position/order is present, uses strict typed quantity projection, and retains bounded prior-only candle history. BuyThenClose keeps its original legacy quantity parsing via an isolated compatibility helper. Exact-HEAD local validation at the feature SHA was reported as 2,018 passed, 1 skipped, 0 failures/errors (2,019 collected); 247 focused tests passed; Ruff check/format, strict mypy on `reference.py`, and `git diff --check` passed. The changed-file set was exactly eight intended Python files. This is operator-reported local validation, not GitHub Actions evidence. No Actions or paid CI was used; no broker/LIVE operations were performed.

PR #232 merged QX-08 M4 from `feat/qx-08-m4-driver-parity-v1` at validated feature HEAD `40559841bc94e3b4c1c7482b21528300c895d7e4` as merge commit `f13249f3b15dd4ab720225f1af5b2b8341d3e6a4` on 2026-10-16. M4 adds explicit caller-owned simulated execution-context binding for bare intents on the StrategyEvaluationService backtest path, rejects unsupported modes, preserves existing intent contexts and the legacy callable path, and adds BuyAndHold state/callback parity, determinism, LIVE-context rejection, and accepted/submitted-without-fill inventory coverage. Exact-tip local validation at the feature SHA was reported as 153/153 focused tests and 2,023 full-suite tests with 0 failures and 1 known optional-Dhan-extra skip; Ruff check/format on the two changed files, strict mypy on `backtest.py`, and `git diff --check` passed. The changed-file scope was exactly the two intended files. This is operator-reported local validation; GitHub Actions remain disabled, and no broker/LIVE operations were performed.

PR #218 merged the independently validated M4.1 feature head `d99c12f3ae051f992722bee2bc8ea3253032fdc8` from `feat/m4-1-strategy-paper-rehearsal-v1` as feature merge commit `a0bf101b6f6bb87d11460cefb199932a768d6335`. That SHA is the PR #218 feature-merge anchor, not the current `main` HEAD. PR #219 subsequently merged the cross-document status rebaseline in commit `3893ea4f19bed3f6b4c0b5cdc70da9167e0e90b9` on 2026-10-14.

M4.1 adds a deterministic, single-use Python strategy rehearsal from registry/runtime evaluation through deployment-owned execution-context binding, risk/policy preparation, and the existing paper executor. It admits enabled PAPER deployments only; it creates no broker-submit path and changes no execution/recovery semantics. The timestamp regression fix derives submission nanoseconds and order creation time from the market event and rejects strategy signal timestamps that differ from event time.

Independent local validation at the exact feature head reported **22 rehearsal tests passed, 177 focused regressions passed, and 1,713 full-suite tests passed with 0 skipped** in an environment where the optional Dhan SDK was installed. Repo-wide Ruff and format checks passed; strict mypy passed across 183 files both with and without the Dhan extra; frozen Dhan sync succeeded and its focused slice passed 130 tests; `git diff --check` was clean. These are local test results, not GitHub Actions evidence. No Actions or paid CI was used.

M4.1 is the first Strategy Platform vertical, not the full parent M4 exit. QX-09 (issue #197) is complete in PR #221. The normative QX-08 design contract remains [docs/implementation/qx-08-engine-truth-strategy-context.md](implementation/qx-08-engine-truth-strategy-context.md), v3.2.0. QX-08 implementation milestones M1, M2, M3, and M4 are complete in PRs #224, #226, #229, and #232 respectively. PR #232's validated feature HEAD is `40559841bc94e3b4c1c7482b21528300c895d7e4`, merged as `f13249f3b15dd4ab720225f1af5b2b8341d3e6a4`. The QX-08 v3.2.0 acceptance-matrix reconciliation is complete; see the closeout section at the top of this file. Issue #196 is closed. The current execution-safety remediation order is recorded in architecture record 56 and issues #239–#241. The parent Strategy Platform M4 exit still includes a first Flow path with shared runtime semantics; that is separate roadmap work and is explicitly outside QX-08. QX-08's callback-enabled path fails closed on nonzero-latency execution configurations because future-effective fills require a separate event-time execution integration, which is out of scope. External scheduling, AI/agents, and LIVE strategy execution remain outside the QX-08 scope.

## Historical merge checkpoint — PR #214 (QX-03 canonical order lifecycle)

At this historical checkpoint, PR #214 advanced `main` to `1fbddc69982722a03ba13bdde76aa8aa76c85d94` (merge commit); that is not the current `main` head. The merged PR #214 head was
`675d351915671168a0e0c4af38ba82f05c85022f`; a post-merge audit proved the
merged tree and the tested tree byte-identical (`git diff 675d351 1fbddc6`
empty, merge parents exactly `1aaf27b` + `675d351`). The QX-03 canonical
order lifecycle (ADR-009) reached `main` in three sequenced slices: PR #213
delivered the first migration slice (canonical `OrderStatus` vocabulary
with `SUBMITTED`, a consolidated evidence-preserving reducer, and trusted
reconciliation entrypoints; merged as `2785fbd`); PR #214 added Dhan
lifecycle goldens for all seven vendor statuses and explicit paper DAY/IOC
semantics; and the merged PR #216 contract added cumulative-observation
receipt evidence (`ExecutionEvidenceKind`) with legacy-payload
compatibility. Issue #192 is closed as completed (2026-10-14), as is
follow-up issue #215.

The following is implementer-reported **local validation** at the tested
head `675d351`, not GitHub Actions results and not independently executed
in this reconciliation:

- Full default suite: **1,690 passed, 1 skipped** across three consecutive
  runs, plus a passing warnings-as-errors run.
- Dhan-extra suite (`uv sync --frozen --extra dhan`): **130 passed**.
- Focused Dhan lifecycle goldens: 6 passed; goldens plus paper suite:
  53 passed; broader execution/Dhan/persistence/application suites:
  1,106 passed, 1 skipped.
- `uv run ruff check`: all checks passed. `uv run ruff format --check src tests`:
  350 files already formatted. `uv run mypy`: no issues in 182 source
  files, with the Dhan extra both absent and installed. Frozen sync and
  `git diff --check`: clean.

No GitHub Actions or paid CI was triggered for this evidence. No API keys,
broker credentials, network-dependent tests, or real broker orders were
used.

## Historical v0.1 acceptance and R1-C completion baseline
**v0.1 acceptance base:** `6f771b5044d7c971b5da2301901534a5156df361` (PR #164 merge; verified before this status update).

**R1-C1 through R1-C12:** complete.

**R1-C13:** complete through C13.8, including durable research persistence, research-run orchestration and lifecycle binding, rehydration, experiment comparison/association/metadata persistence, experiment detail read, and the experiment write boundary.

**R1-C14:** complete through C14.9, including provider/MarketDataPort composition, registered dataset identity, explicit quality evidence, durable candle persistence/readback, research provenance binding, and the end-to-end deterministic lifecycle proof. PR #158 is merged to `main` at the post-C14 integration base above.

**V0.1 local-first host and integration readiness:** rebaselined at the acceptance base. PR #164 (host-composed restart regression) and PR #175 (optional Dhan SDK typing fix) are merged. Per ADR-008, v0.1 ships as a programmatic local-first library on the `DhanHostConfig` + `build_dhan_host_runtime()` → `DhanHostRuntime.start()` / `close()` bootstrap contract; the CLI is deferred and `docs/roadmap/feature-priorities.md` is aligned. The normative checklist in `docs/architecture/28-v0.1-acceptance-criteria.md` records every required criterion PASS with exact evidence (full suite 1483 passed, Ruff zero findings, strict mypy clean with and without the Dhan extra) and closes the release gate for the declared scope. Validation remains local; no real-broker LIVE-readiness claim is implied. This rebaseline changes documentation and one formatting-only test collapse; no production behavior changed.

The repository contains an implemented domain, execution, research, India-market, integration, reconciliation, and deterministic research foundation. Historical validation records below are retained as evidence/history and do not define the current milestone.

**Latest externally validated recovery milestone:** `feat/production-recovery-entrypoint` at `efa4798a76d3576f31b5a2127381fb990c6a0915` with 665 passed, 0 failed, 0 errors, 0 skipped. The earlier 635-test checkpoint remains the last independently documented baseline on the pre-entrypoint recovery branch.

## Post-PR #33 validation evidence

The LIVE startup/readiness and trading-gate hardening merged in PR #33. Claude's local sandbox validation of the PR branch reached **813 passed tests, 0 failed** after aligning the affected fixtures with the new runtime/evidence contracts. Equivalent test fixes are included in the merged mainline, with an additional explicit unscoped negative-case correction. This is local validation evidence, not GitHub Actions evidence; Actions is not used as a repository gate while billing is disabled.

## Validation baseline

A prior externally reported checkpoint for the production-recovery stack was **665 passed, 0 failed, 0 errors, 0 skipped** at `efa4798a76d3576f31b5a2127381fb990c6a0915`. This validation was run externally with OpenCode on `feat/production-recovery-entrypoint`; changed-file Ruff and `git diff --check` were clean. At that time, repo-wide Ruff reported 272 pre-existing errors. No production-broker end-to-end execution was claimed.

This checkpoint validates the LIVE durability hardening, pending-recovery corruption isolation, and explicit startup lifecycle: LIVE requires a UnitOfWork-backed transaction path; completed broker submissions retain a durable receipt even when idempotency completion is uncertain; direct LIVE dispatcher/adapter bypasses are blocked; durable trading-gate state survives restart; pending LIVE reservation context is persisted and reconstructible across a simulated process restart; malformed pending contexts are isolated as per-context recovery failures; the default all-required recovery path can resolve with local position/account evidence; concurrent recovery passes resolve a pending reservation at most once; and an explicit application runtime runs pending recovery once before startup completes. The 635-test suite completed with zero failures, errors, or skipped tests.

The 635-test validation was performed against the branch head after fast-forward sync at `e4d85ae6e4d61fe61bfbeba1c838fb7a428d1c9c`. The only Ruff finding was the pre-existing `I001` import-order issue in `src/quantx/application/execution.py`; a subsequent import-only cleanup was committed at `5817ce0f9cb2103f9ba05abfefa7495c5f2ec342`. `git diff --check` was clean; the local `uv.lock` modification was pre-existing environment noise and remained untouched. The import-only cleanup has not been independently re-run through the full suite in this environment.

This is the reported validation result for the checked commit. The available GitHub Actions status endpoint does not show an independent workflow run for this checkpoint, so this document does not claim GitHub CI independently executed that suite.

## Historical local validation evidence (R1-C14 vertical proofs)

Local validation on the C14.7 vertical-proof branch `feat/r1c14-dhan-market-data-host-wiring-test-v1` (base `e72287ce84afdd8393bd8c4203e7c82dd2629abf`) reports **1399 passed, 0 failed, 1 skipped** in the full suite (the skip is the optional-Dhan-SDK test; no warnings were emitted across two consecutive runs). Repo-wide Ruff reports **zero findings**; strict mypy reports **no issues in 179 source files**; `git diff --check` is clean. This is local validation evidence; no GitHub Actions run is claimed and no production-broker end-to-end execution was performed.

Local validation on the C14.8 binding branch `feat/r1c14-research-provenance-binding-v1` (base `0196ceec6f46231eb5c9be0e6d5b983bfaa4746d`) reports **1409 passed, 0 failed, 1 skipped, 1 warning** in the full suite (the skip is the optional-Dhan-SDK test; the warning is the pre-existing `SyntaxWarning` in `tests/unit/research/test_storage_filesystem.py`). Repo-wide Ruff reports **zero findings**; strict mypy reports **no issues in 180 source files**; `git diff --check` is clean. This is local validation evidence; no GitHub Actions run is claimed and no production-broker end-to-end execution was performed. It binds declared dataset identity to the canonical research-run identity and does not yet prove the full provider-to-research lifecycle.

Local validation on the C14.9 proof branch `feat/r1c14-end-to-end-deterministic-proof-v1` (stacked on the C14.8 head `62f87b657cf66a3f078b069a6e522ec3801b6046`; not on `main`) reports **1410 passed, 0 failed, 1 skipped, 1 warning** in the full suite (the skip is the optional-Dhan-SDK test; the warning is the pre-existing `SyntaxWarning` in `tests/unit/research/test_storage_filesystem.py`). Repo-wide Ruff reports **zero findings**; strict mypy reports **no issues in 180 source files**; `git diff --check` is clean. This is local validation evidence; no GitHub Actions run is claimed and no production-broker end-to-end execution was performed. It proves one declared dataset identity flowing deterministically from provider retrieval through durable persistence and dataset-scoped read into provenance binding and a completed, reopen-verified research run.

Recent continuation/recovery work includes:
- explicit continuation lifecycle reconstruction from authoritative receipt evidence;
- continuation-chain lineage and aggregate fill validation;
- idempotent continuation dispatch claims;
- pending/recoverable/resolved continuation recovery states;
- validation that reused continuation claims match authoritative receipt identity, quantity, account, and broker connection;
- conservative recovery of execution state rather than inference from an uncertain submission;
- durable trading-gate state persisted behind a pluggable state-store boundary, with SQLite restart coverage;
- versioned pending LIVE execution context persisted with idempotency reservations and reconstructible after restart;
- SQLite schema v2 migration coverage for pending context and durable trading-gate state;
- deterministic pending LIVE recovery with per-context failure isolation and no-submit semantics;
- malformed persisted-context isolation with reservation/context identity checks;
- explicit, one-shot application startup lifecycle for recovery-backed startup;
- broker-returned `UNKNOWN` LIVE receipts remain durably PENDING for reconciliation rather than completing idempotency.

## Architecture direction

- modular monolith first; distributed-ready later
- event-driven/domain-driven core
- ports and adapters
- capability-based integrations
- plugin-first extensibility
- Indian-market/F&O-first domain model
- data, control, and execution plane separation
- deterministic research, replay, and simulation
- explicit provenance and point-in-time market rules
- fail-closed live execution
- reconciliation rather than inference for uncertain broker outcomes
- local-first deployment with clear integration seams

## Current implementation track

QX-09 market-pack pre-trade-check pipeline is complete via PR #221 (validated feature head `7793646e0e3d210e81364d39605ee3383e434723`; merge commit `1e4ebf4f4671e90dcdcafc1cda578182ab39d58b`). Issue #197 is complete. QX-08 issue #196 has completed implementation phases M1 in PR #224, M2 in PR #226, M3 in PR #229, and M4 paper/backtest driver parity in PR #232 (validated feature HEAD `40559841bc94e3b4c1c7482b21528300c895d7e4`; merge commit `f13249f3b15dd4ab720225f1af5b2b8341d3e6a4`). The QX-08 v3.2.0 acceptance-matrix reconciliation is complete; see the closeout section at the top of this file. Issue #196 is closed. The current execution-safety remediation order is recorded in architecture record 56 and issues #239–#241. Flow authoring/runtime parity, external scheduling, AI/agents, and LIVE strategy execution remain outside QX-08 scope and must not be implied by these completed implementation phases. Execution/recovery safety boundaries remain frozen unless a concrete reproducible invariant violation is proven. The repository now covers idempotency, execution receipts, order lifecycle reconstruction, account/connection identity, broker-order reconciliation, bounded evidence refresh, uncertain-submission recovery, partial-fill continuation/recovery, durable trading-gate state, durable pending LIVE execution context, malformed-context isolation, explicit recovery-backed application startup, fail-closed handling of broker-returned UNKNOWN LIVE receipts, and concrete production startup composition with identity-bound Dhan recovery evidence. The Dhan production host adapter (`DhanHostConfig`/`DhanHostRuntime`) composes credentials/transport construction, exact account/connection registration, and one-shot recovery-backed startup with no broker-submit surface and no new execution semantics. A vendor-neutral local market-data store (`MarketDataStore`, SQLite-backed) persists canonical quotes/candles with exact Decimal fidelity, deterministic chronological retrieval, idempotent-duplicate/conflicting-duplicate semantics, and schema v3 migration; Dhan remains an adapter above that storage boundary. A vendor-neutral dataset catalog registers immutable `DatasetVersion` identities with idempotent-duplicate/conflicting-duplicate semantics and local JSON metadata persistence, without verifying source content or performing ingestion. A deterministic historical-data quality seam analyzes canonical candle collections for structural soundness and assesses completeness only against an explicitly supplied expected timestamp set, reporting UNKNOWN completeness otherwise, without repairing data or verifying source files. A dataset-backed historical research access seam resolves a registered `(dataset_id, version)` through the catalog and reads version/source-scoped canonical candles from `MarketDataStore` without source verification, backtesting, simulation, or scheduled operation. A canonical historical candle ingestion bridge (`research/market_data_ingestion.py`) connects `MarketDataPort` to `MarketDataStore` with no scheduling, retry, caching, or network behavior; there is no claim of scheduled ingestion, production historical-data operation, or real-broker end-to-end execution. Historical research observations (`HistoricalObservation`) now preserve canonical candles losslessly alongside quote snapshots: `HistoricalObservation.from_candle` keeps the exact `Candle` (instrument, timeframe, timestamp, OHLCV) with no Quote projection and no synthetic bid/ask, `HistoricalDataSeries`/`HistoricalReplay` stay payload-neutral over both payload types, and dataset-backed candles convert through `research/dataset_access.py` without touching `MarketDataStore`, catalog, or identity rules. This does not implement backtesting or execution simulation, does not verify source integrity, and does not add scheduled/production historical ingestion. The deterministic backtest path now accepts candle-backed replay frames through the existing event and reference-price contracts (candle events carry the exact `Candle` with `MarketDataType.CANDLE`; bar-close is the reference price per the strategy preparation contract), while quote-based paper execution stays explicitly unavailable for candles via a `BLOCKED` disposition instead of synthetic bid/ask. A minimal deterministic `BASIC_BAR` fill model now prices candle MARKET orders at the observed bar close through the existing `FillModel` seam (`CandleFillModel`, routed by `DataAdaptiveFillModel` without changing quote behavior); limit/stop orders propose no fill rather than an inferred one, and all fills remain `SIMULATED_EXECUTION` with explicit assumptions. Each fill proposal now carries its selecting model identity (`QUOTE`/`paper-core-v0.3` or `BASIC_BAR`/`basic-bar-v2`) onto the engine receipt, so mixed quote/candle runs can no longer inherit a misleading profile label; quote receipt metadata is unchanged. Intrabar semantics, partial fills beyond the existing ratio, slippage beyond the existing model, and richer bar-model provenance remain future M3 work. `CandleFillModel` has since grown a conservative close-cross LIMIT rule (`basic-bar-v2`): BUY fills only at or below the limit, SELL only at or above it, priced at the exact bar close, with high/low never triggering fills; STOP/STOP_LIMIT still propose no fill. `CandleFillModel` now classifies stop triggers explicitly (`basic-bar-v3`): a touch confirmed by the close fills at the close, a touch without confirmation is ambiguous and blocked rather than priced, untouched stops rest unfilled, and STOP_LIMIT stays rejected because post-trigger limit ordering is unknowable from OHLC; single-step lifecycle is unchanged. `BacktestResult` now carries experiment-level `BacktestFidelity` reusing the research `ResultQuality` vocabulary (models, evidence types, determinism, limitations) with per-receipt model identity; missing research-provenance inputs remain explicitly unavailable rather than fabricated. `CandleFillModel` (`basic-bar-v4`) accepts an optional Decimal candle-volume participation rate bounding proposed quantity by that share of the observed bar volume (zero volume means no fill); the cap is recorded as a modeled assumption, never observed liquidity, while pricing, triggers, quote behavior, and the existing partial-fill ratio remain unchanged. The pre-existing deterministic `slippage_bps` control is now Decimal-strict at construction, applies unchanged after price discovery (BUY multiplies, SELL divides, per the pinned engine semantics), records a `reference_price=` token only when actually applied, and is noted in backtest fidelity; no new slippage parameter was introduced.

`PendingExecutionRecoveryRunner` remains a deterministic application service with no broker-submit capability. The current hardening branch also makes LIVE execution depend on a started recovery-backed `ApplicationRuntime` and adds submission-time trading-gate authorization spanning durable reservation and the broker call. `ApplicationRuntime` now provides the explicit one-shot startup lifecycle seam: it requires a recovery hook, runs it synchronously before marking the runtime started, rejects repeated starts, and leaves startup failed if recovery infrastructure raises. `ProductionRuntime` now provides the concrete process-composition boundary: it owns the durable SQLite lifecycle, accepts explicit registry configuration, delegates to the recovery-backed `ApplicationRuntime`, and closes persistence on composition failure. It intentionally does not construct credentials, broker transports, or deployment-specific services. Therefore this is validated production composition, not a claim of an executable CLI/service deployment or real-broker end-to-end startup.

The continuation implementation deliberately remains persistence-agnostic: it consumes authoritative receipt/reconciliation contracts and does not introduce a database or broker network dependency by itself.

## Execution/recovery adversarial findings — latest recorded audit

No outstanding adversarial finding. The record below is historical: the review of the 20-commit recovery sequence identified two additional LIVE control-path gaps — startup recovery was not a required dependency of `ExecutionOrchestrator`, and the gate check could race with broker submission. Both were integrated (recovery-backed `ApplicationRuntime` startup dependency and submission-time trading-gate authorization) and are covered by the current green suite; they are not pending validation. A new finding will be recorded here only with exact evidence of an actual unresolved issue.

## Documentation policy

Architecture documents distinguish implemented/current behavior, target architecture, and roadmap/future capabilities. Historical batch records should not be treated as current implementation state unless explicitly marked as historical.

## R1-C9 milestone

R1-C9 multi-instrument account-state synchronization is implemented and merged (squash `53022d15ff9e209e78739c1b87462635a8c2e174`). The final implementation head was `6bf81fb2571da7423e25865b6c859bea6f5e78eb` on `feat/r1c9-remediation`. External OpenCode/local revalidation reported **1185 passed, 0 failed** in the full suite; the focused C9/replay set reported **23 passed**. Changed-file Ruff had **0 new in-scope findings**, strict mypy had **0 errors in the changed production files**, and `git diff --check` passed. C9 adds an explicit `AccountStateSamplingPolicy` (`EXACT_CURRENT` default, `AS_OF_OBSERVED` opt-in) mapped onto the existing tracker behavior, plus a replay-boundary extension so `HistoricalReplay` accepts multiple single-instrument series merged deterministically, while `HistoricalDataSeries` remains strictly single-instrument. No LIVE, broker, reconciliation, recovery, risk, persistence, or accounting semantics were changed.

## R1-C8 milestone

R1-C8 historical account-state valuation provenance is implemented and merged in PR #69. The final revalidated implementation head was `57ddc1e5e65a55e8cea0296e9120b704e9224951`; it was squash-merged to main as `d5a8776d26e773552b1ba072fcffc827176c0183`. External revalidation reported **1175 passed, 0 failed, 0 errors, 1 skipped** in the full suite, with the optional Dhan SDK test skipped; the focused C8/C4/C7 regression set reported **89 passed**. Changed-file Ruff passed with zero new in-scope findings, strict mypy passed for `historical_account_state.py`, and `git diff --check` passed. C8 adds immutable valuation provenance to historical account-state snapshots without changing mark-selection, accounting, risk, LIVE, broker, reconciliation, retry, UNKNOWN, or recovery semantics.

## R1-C7 milestone

R1-C7 time-indexed historical account-state sampling is implemented and merged in PR #67. The final revalidated implementation head was `92f3a7915a70b16f43d98eae8f0ad36d79c3af65`; it was squash-merged to main as `3a35d32ce60eecb155027bb59a69edd94e5b4cff`. External revalidation reported **1173 passed, 0 failed, 0 errors, 1 skipped** in the full suite, with the optional Dhan SDK test skipped; the focused C7/execution/backtest regression set reported **76 passed**. Changed-file Ruff had **0 new in-scope findings**, strict mypy passed on the three changed production files, and `git diff --check` passed. The final implementation adds timestamped valuation marks and an additive pre-frame `account_state_series` with exact-current-mark fail-closed semantics while preserving the C4 receipt-driven `account_states` path. No LIVE, broker, reconciliation, retry, UNKNOWN, recovery, risk, or accounting semantics were changed.

## R1-C6 milestone

R1-C6 execution-fidelity hardening is implemented and merged in PR #65. The final validated implementation head was `5a58318c3978b3a78da32847d717e8bc842a8ac8`; it was squash-merged to main as `8067e5f3b81344698b818d950373bbcc477c170a`. External revalidation reported **1168 passed, 0 failed, 0 errors, 1 skipped** (the optional Dhan SDK test). Changed-file Ruff, strict mypy for the two changed production files, and `git diff --check` all passed. The final C6 implementation touched only the paper/research execution-fidelity path and test/docs surfaces; it did not expand LIVE, reconciliation, retry, UNKNOWN, recovery, broker SDK, persistence, or integration boundaries.

## V0.1 and R1-C roadmap context (historical baseline)

V0.1 local-first host and integration readiness is acceptance-complete for the declared programmatic-library scope (ADR-008): the acceptance audit is done, the host-composed restart proof (PR #164) and the optional-SDK typing fix (PR #175) are merged, the CLI is explicitly deferred, and the release gate is closed per `docs/architecture/28-v0.1-acceptance-criteria.md`. R1-C13/C14 records below are historical milestones, not current work. Treat execution/recovery safety boundaries as frozen unless a concrete invariant violation is proven; no production-broker end-to-end execution has been performed.

C14 establishes a deterministic, provider-neutral historical dataset ingestion application boundary that composes the existing `MarketDataPort`, `DatasetCatalog`, historical-data quality, `MarketDataStore`, dataset-backed research access, and research provenance seams. Dataset identity is pre-declared and authoritative; observations remain lossless; completeness remains evidence-bound; persistence semantics remain centralized; and provider-specific behavior remains outside the dataset domain.

The protected C14 salvage sources are `feat/m2-dataset-ingestion-workflow-v1` and `feat/dhan-host-market-data-wiring-v1`. They are not current implementation branches and must not be merged wholesale; their unique tests/design are source material for C14.

C14 explicitly defers scheduling, retry orchestration, streaming, production historical-data service, distributed ingestion, cloud storage, generic ETL, UI, AI/ML, optimization, and broad broker expansion.

GitHub Actions is not a repository validation gate while billing is disabled; OpenCode/local validation remains the execution gate. No production-broker end-to-end execution has been performed.
