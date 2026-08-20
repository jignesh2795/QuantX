# Implementation Batch Plan

The architecture is implemented in coherent batches rather than one-file-at-a-time changes.

## Batch A — Execution integrity
- Idempotent order submission
- Execution receipts
- Broker acknowledgement states
- Unknown/uncertain outcomes
- Order reconciliation
- Position/account reconciliation

## Batch B — Research integrity
- Dataset identity/versioning
- Artifact integrity
- Point-in-time metadata
- Market calendars
- Instrument/contract lifecycle
- Corporate actions
- Adjustment policies
- Futures roll policies
- Deterministic replay
- Research provenance

## Batch C — Account-aware connectivity
- Account/connection identity
- Capability discovery
- Connection health
- Account-safe routing
- Failover constraints
- Actual/paper account state
- Broker reconciliation

## Batch D — Package organization
- Keep domain, application, execution, portfolio, risk, research, integrations, plugins, AI and infrastructure separate.
- Split large areas into focused subpackages.
- Do not introduce catch-all utility/modules when a responsibility has a stable boundary.
- Migrate existing modules incrementally rather than performing a risky repository-wide rename.

## Batch E — Market plugins
- India plugin family
- Global plugin family
- Crypto plugin family
- Venue rule providers
- Broker adapters
- Market calendars
- Contract lifecycle providers

## Batch F — Trading application core
- strategy interfaces
- signal/trade intent
- risk decisions
- order construction
- portfolio state
- execution orchestration

## Batch G — Realistic simulation
- latency
- liquidity
- spread
- slippage
- fees/taxes/funding
- partial fills
- rejection models
- market impact where supported
- replay/paper/live semantic parity

## Batch H — AI and research extensions
- feature pipelines
- model registry
- walk-forward validation
- experiment comparison
- AI agents
- optional AI-assisted execution models
- model provenance and promotion controls

## Batch I — Platform infrastructure
- persistent stores
- event bus
- observability
- secrets boundary
- configuration management
- background jobs
- API/UI integration
- plugin discovery

## Large decisions requiring explicit approval
Only stop for decisions that materially change the product or architecture, such as:
- changing the core domain model or execution semantics;
- selecting a fundamentally different persistence/event architecture;
- changing the separation between India/global/crypto plugins;
- introducing a mandatory external service or cloud dependency;
- choosing a production deployment/security model that cannot remain local-first.
