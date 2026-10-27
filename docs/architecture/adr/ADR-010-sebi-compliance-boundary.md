# ADR-010: SEBI Compliance Boundary and Self-Check

Status: Accepted

## Context

SEBI's 2025 algorithmic trading framework (effective 2025-10-01, full
applicability 2026-04-01) places brokers as the principal and algo
providers (including self-hosted platforms) as agents. It requires
algo-ID tagging, static-IP whitelisting, OAuth, 2FA, audit trails, and
rate limits (TOPS 10 orders/sec).

QuantX is an open-source, single-user library/engine. The broker (Dhan,
Zerodha, etc.) is the regulated entity and already implements SEBI
compliance at the API boundary. Re-implementing broker-side compliance
inside QuantX would duplicate responsibility, bloat the core, and
conflict with the "infrastructure first" and "composition over opinion"
stances in VISION.md.

## Decision

QuantX does not implement broker-side SEBI compliance. Compliance
remains the broker's responsibility. QuantX provides only a read-only
self-check that audits the engine's own hygiene:

- No broker SDKs outside `plugins/` (especially `transport.py`).
- No secrets or credentials in code or config.
- API keys resolved server-side, never exposed to strategies.
- Order rate within the default TOPS threshold (10 orders/sec).
- Full audit trail present in receipts and idempotency stores.
- Decimal-only money; fail-closed on missing state.
- Broker adapter capability metadata present.

The self-check is an audit, not a compliance implementation, and lives
with the security-audit concern (not in the trading core).

## Consequences

- Core stays broker-SDK-free and venue-neutral.
- No algo-ID tagging, static-IP awareness, OAuth, or session-logout
  logic in core or domain.
- `execution/receipts` and `execution/idempotency` remain for internal
  correctness and recovery, not for SEBI audit.
- `india/` keeps market rules (sessions, charges, instruments) as
  domain data, not compliance.
- Broker adapters own any broker-specific compliance translation.
- A future `compliance check` command or security-audit routine can
  surface hygiene gaps without changing trading semantics.
