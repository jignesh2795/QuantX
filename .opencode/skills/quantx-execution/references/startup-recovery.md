# Startup & Recovery (quantx-execution)

Ordering rule (`docs/architecture/50-production-host-integration-boundary.md`):

```
construct → bind explicit identities → recover pending LIVE state → become ready → permit LIVE submission
```

- `application/pending_recovery.py` — `PendingExecutionRecoveryRunner` / `recover_pending_live_executions()`: boot-time, deterministic, **never submits broker orders**, per-context failure isolation.
- `application/runtime.py` — `ApplicationRuntime.start()`: ONE-SHOT startup recovery before marking started; rejects repeat starts.
- `application/recovery_composition.py` — `build_application_runtime()`, `RecoveryEvidenceFactory`.
- `application/production.py` — `build_production_runtime()`: process boundary owning SQLite lifecycle; no credentials/transports/background workers; `close()` for deterministic shutdown.
- `application/uncertain_submission.py` — `UncertainSubmissionReceiptRecovery`.

**No background recovery daemon. No automatic retry on uncertain broker outcomes** — uncertain → `UNKNOWN` receipt, then reconciliation.
