# Production Host Integration Boundary

## Purpose

QuantX separates **process composition** from **deployment hosting**.

The application layer owns recovery and execution invariants. The host layer owns deployment-specific concerns such as credentials, concrete broker transport construction, configuration loading, process lifecycle, and readiness signaling.

The validated `ProductionRuntime` is the boundary between these responsibilities.

## Boundary

```text
Host / Deployment
    │
    ├── load explicit deployment configuration
    ├── construct credentials and vendor transports
    ├── construct concrete broker adapters
    ├── register exact AccountId + BrokerConnectionId
    ├── construct read-only recovery evidence factory
    │
    ▼
ProductionRuntimeConfig
    │
    ▼
ProductionRuntime
    │
    ▼
ApplicationRuntime.start()
    │
    ▼
PendingExecutionRecoveryRunner
    │
    ▼
read-only reconciliation
    │
    └── startup succeeds only after recovery pass completes
```

## Host responsibilities

A future executable process wrapper may:

1. load configuration from an explicit deployment source;
2. construct broker credentials outside the application/domain packages;
3. construct the vendor transport and broker adapter;
4. create the canonical `BrokerConnectionRef`;
5. register that adapter explicitly in `AccountConnectionRegistry`;
6. supply the corresponding read-only recovery evidence factory;
7. construct `ProductionRuntimeConfig`;
8. call `build_production_runtime()`;
9. call `ProductionRuntime.start()`;
10. expose execution/control services only after startup succeeds.

The host must not invent an account or connection when persisted recovery identity cannot be resolved.

## Application responsibilities

The application boundary owns:

- durable SQLite lifecycle through `ProductionRuntime`;
- exact persisted account/connection resolution;
- pending LIVE recovery;
- reconciliation and evidence policy;
- one-shot startup semantics;
- fail-closed LIVE execution invariants.

The application must not own:

- credential loading or secret storage;
- vendor SDK construction;
- environment-specific configuration parsing;
- HTTP server or CLI framework lifecycle;
- deployment health/readiness implementation.

## Configuration rule

Configuration must be explicit and identity-bearing.

At minimum, a future host configuration must be able to express:

- database location;
- account identity;
- broker connection identity;
- broker identifier;
- market context;
- credential source;
- enabled/disabled state;
- broker-specific adapter settings.

There is deliberately no application-level default account or default broker connection.

## Readiness rule

Startup ordering is:

**construct → bind explicit identities → recover pending LIVE state → become ready**

If construction or recovery fails, the host must not advertise execution readiness.

`ApplicationRuntime.started` is the application readiness gate. `ProductionRuntime.started` exposes that state without creating another lifecycle authority.

## Determinism and cleanup

The host should provide a deterministic shutdown path by calling `ProductionRuntime.close()`.

Composition failure must release process-owned persistence. Broker transports are host-owned and therefore remain the host's responsibility to close when their concrete implementation requires cleanup.

No background recovery daemon is implied by this contract.

## Real broker boundary

The first concrete host implementation should remain outside the application/domain packages. A Dhan-specific host adapter may be added later, but it must use the existing plugin boundary:

- `DhanCredentials`
- `DhanSDKTransport`
- `DhanBrokerAdapter`
- `build_dhan_recovery_provider`

It must not introduce a second LIVE execution path.

## Deployment forms

The same host contract can later back:

- a local process;
- a CLI command;
- a service/daemon;
- a container entrypoint;
- a test harness.

These are hosting forms, not separate application architectures.

## Non-goals

This document does not prescribe:

- a configuration file format;
- environment variable names;
- a secret manager;
- a CLI framework;
- an HTTP framework;
- a service manager;
- a container image;
- a multi-process deployment.

Those choices belong to a concrete deployment implementation.

## Decision

Do not add a generic process entrypoint until a concrete host use case requires one. When one is added, keep it outside the application/domain execution path and make it a thin composition adapter over `ProductionRuntime`.