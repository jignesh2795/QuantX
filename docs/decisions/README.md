# Architecture Decision Records

Architecture decisions are recorded here before major implementation work.

## Accepted ADRs

Written ADR-lite records live in `docs/architecture/adr/`. They capture the
Context / Decision / Consequences rationale for the target architecture; the
normative rules themselves remain in `docs/architecture/`.

- ADR-001 — [Modular monolith first](../architecture/adr/ADR-001-modular-monolith-first.md)
- ADR-002 — [Plugin-first extensibility](../architecture/adr/ADR-002-plugin-first-extensibility.md)
- ADR-003 — [Event-driven domain core](../architecture/adr/ADR-003-event-driven-domain-core.md)
- ADR-004 — [One semantic lifecycle across environments](../architecture/adr/ADR-004-one-semantic-lifecycle.md)
- ADR-005 — [Indian-market domain first](../architecture/adr/ADR-005-indian-market-domain-first.md)
- ADR-006 — [Broker adapters and capabilities](../architecture/adr/ADR-006-broker-adapters-and-capabilities.md)
- ADR-007 — [Modular-hybrid architecture](../architecture/adr/ADR-007-modular-hybrid-architecture.md)

## Decisions not yet written as ADRs

These remain planning intent; the accepted records above already cover parts of
them, so write a new ADR only when there is additional rationale to record.

- Ports and adapters (covered in principle by ADR-001/002)
- Capability-based integrations (covered by ADR-006)
- Data plane, control plane and execution plane separation (covered by ADR-007)
- Strategy Intermediate Representation
- Local-first deployment
