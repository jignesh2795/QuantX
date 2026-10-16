---
name: quantx-adversarial-review
description: Independent break-the-change review of QuantX diffs — safety, evidence integrity, UNKNOWN handling, idempotency, reconciliation, scope leakage, and misleading tests or docs. Use after implementation, before validation/merge. Do not praise the diff; try to break it.
metadata:
  quantx/role: review
---

# QuantX Adversarial Review

Do not praise the diff. Try to break it.

## Review checklist

- gate bypass / order races (can any path skip `TradingGate` or the approved dispatcher?);
- submit-admission races (does every broker contact cross `admit_submission()` after the durable reservation? what does a `block()` landing before vs after admission do?);
- failed `block()` / `enable()` persists across multiple gates sharing one persistence domain (second gate and late joiners must deny `allow()` / permits / admission while the store still reports stale enabled state);
- independent persistence domains never sharing or clearing each other's fault state (no global latch; store identity vs shared-database identity);
- SQLite wrappers sharing one database denying and recovering together;
- fault-registry edge cases: key identity vs equality (no custom `__eq__` / `__hash__` on domain objects), weak-reference lifetime (fault dies with its domain; fresh domains unaffected), `shared_fault_domain` fallback for stores without one, lock ordering (gate → registry leaf → store), concurrent read linearizing against a failed write;
- stale enabled state reloaded after a failed persist; successful-write fault recovery on any gate in the domain; already-admitted submissions never reported as cancelled;
- idempotency failures (fingerprint stability, duplicate submission, repeated client order IDs);
- UNKNOWN incorrectly becoming definitive (UNKNOWN is never PASS; missing evidence stays UNKNOWN);
- recovery paths that could submit (recovery must never submit broker orders);
- fabricated defaults / invented market or broker evidence;
- float financial math (Decimal mandatory for money and prices);
- authority signals that can be spoofed (strings/booleans where a typed contract is required);
- stale/future data leakage (point-in-time violations);
- hidden backward-compatibility breaks;
- wrong test expectations (tests that pass while proving nothing);
- dead code that creates false authority;
- scope leakage (changed files outside the stated task);
- docs/PR claims unsupported by code;
- broker SDK imports outside `plugins/dhan/transport.py`;
- compatibility shims extended instead of target boundaries used.

## Control-path awareness

Reason over: `intent → domain validation → risk/policy → gate + reservation → submit → receipt → continuation → reconciliation/recovery → position update`. Flag any change that touches multiple control-path layers without explicit justification.

## Findings format

For each finding give:

- severity;
- file and line;
- why it matters;
- smallest failing test or demonstration;
- whether it blocks merge.

State explicitly what could not be verified.
