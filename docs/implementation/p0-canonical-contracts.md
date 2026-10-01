# QuantX V0.1 P0 — Canonical Contracts

Status: implementation baseline on `feat/v0.1-implementation`.

## Purpose

P0 establishes the stable internal language of QuantX before UI, broker
adapters, AI agents, or persistent storage are allowed to define the trading
engine.

The intended lifecycle is:

`Strategy -> TradeIntent -> Risk -> Policy -> ApprovedExecutionRequest -> Execution Environment -> ExecutionReceipt -> Fill -> Position -> Portfolio`

## Contracts

QuantX now has explicit dependency-free contracts for:

- instruments and market context;
- accounts and broker connections;
- trade intents and normalized orders;
- strategy identity and signals;
- quotes and candles;
- risk decisions;
- execution policy and capabilities;
- execution receipts;
- immutable domain events.

Financial values use `Decimal`, and time-bearing records require timezone-aware
timestamps.

## Risk and policy boundary

Risk answers whether an intent satisfies deterministic financial and broker
constraints.

Policy answers whether the requested capabilities are permitted in the current
runtime context.

Live execution is fail-closed unless it has a broker connection, an approved
risk result, and an approved execution policy.

## Execution boundary

Paper, replay and shadow execution share the normalized request/receipt
contracts. Paper execution uses supplied market observations and explicit
simulation parameters for slippage, partial fills and fees. Missing required
quotes do not create invented fills, and repeated client order IDs are
idempotent.

## Plugin and agent boundary

Strategies, AI agents and community plugins produce normalized intents,
signals, capabilities or other declared inputs. They do not call brokers
directly and do not receive broker secrets merely because they can generate a
trading decision.

## Validation

The repository's GitHub Actions workflow runs the full pytest suite for this
branch. This environment cannot execute the GitHub repository locally, so test
execution is not claimed here; the branch CI result is the authoritative
runtime validation for these commits.

## Next slice

P1 will implement the Indian-market adapter boundary, instrument data source,
deterministic backtest/replay application service, and broker/data contract
tests before adding UI or autonomous AI execution.
