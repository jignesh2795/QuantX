# QuantX Architecture Decision Gates

Status: Active planning control

QuantX does not move into major implementation until these gates are satisfied.

## Gate 0 — Baseline

- repository baseline exists
- documentation branch exists
- source references recorded
- no production implementation committed accidentally

## Gate 1 — Architecture

- domain boundaries approved
- dependency rules approved
- plugin/adapters model approved
- execution environments approved
- F&O domain constraints captured

## Gate 2 — Interface contracts

- core ports defined
- broker/data contracts defined
- event schema conventions defined
- strategy contract/IR defined
- persistence/message-bus contracts defined

## Gate 3 — External comparison

For each significant subsystem, decide:

- reuse from QuantumTrade
- integrate existing project/library
- implement in QuantX
- make a plugin
- defer
- reject

## Gate 4 — v0.1 scope

Only capabilities required to prove the core should enter v0.1. Feature breadth must not outrun testability and maintainability.

## Gate 5 — Implementation

Implementation starts only after Gates 0–4 are documented and reviewed.

## Change-control rule

If a new feature violates a locked architectural principle, update the relevant ADR before changing code.