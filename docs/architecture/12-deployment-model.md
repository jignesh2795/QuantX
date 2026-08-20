# QuantX Deployment Model

## Local-first

The default deployment should be usable on one machine with minimal infrastructure.

```text
QuantX
├── Core
├── Control Plane
├── Adapters
├── Storage
└── UI/CLI
```

## Distributed-ready

When required, selected workloads may move into workers or services:

```text
API Gateway
   ├── Core/Control
   ├── Strategy Workers
   ├── Data Workers
   ├── Research Workers
   └── Execution Workers
          ↓
      Message Bus
```

The deployment topology must not change domain contracts.

## Supported direction

- local development
- Docker/Compose
- Linux server
- optional cloud VM
- later multi-worker deployments

Cloud services are deployment choices, not mandatory dependencies of the product.
