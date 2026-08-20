# Versioning, Security, Governance, and Compatibility

## Versioning

QuantX uses semantic versioning for public software contracts.

- Patch: backward-compatible fixes.
- Minor: backward-compatible capabilities and extensions.
- Major: intentional breaking changes.

The following are independently versioned contracts:

- REST API
- WebSocket protocol
- domain events
- Strategy IR
- plugin API
- storage schema

## Plugin compatibility

Every plugin declares:

- plugin name and version
- plugin type
- supported QuantX API range
- required capabilities
- required permissions
- dependencies
- license
- maintainer

A plugin that is incompatible with the running core is rejected before activation.

## Security boundary

Core trading components must not expose raw broker credentials to strategies or AI agents.

Secrets should be accessed through a secrets provider abstraction and least-privilege credentials.

Capabilities such as `READ_MARKET_DATA`, `CREATE_PAPER_ORDER`, `CREATE_LIVE_ORDER`, `ACCESS_SECRETS`, and `CHANGE_RISK_POLICY` are independently controllable.

## Plugin trust

Plugins may be classified as:

- **Trusted:** maintained and reviewed as part of the core project.
- **Community:** third-party extensions with declared permissions.
- **Sandboxed:** untrusted or AI-generated code with restricted filesystem, network, and secret access.

## AI safety boundary

AI may research, analyze, generate proposals, backtest, and recommend. AI must not bypass the normal risk/order/execution lifecycle or silently weaken safety controls.

Promotion from AI-generated proposal to live execution requires the same validation and approval gates as any other strategy.

## Governance

The repository should eventually contain:

- CONTRIBUTING.md
- SECURITY.md
- GOVERNANCE.md
- CODEOWNERS
- pull request template
- issue templates
- release policy
- RFC/ADR process

Breaking architecture changes require an ADR and review before implementation.

## Data and legal boundaries

QuantX may model fees, charges, market rules, and configurable tax calculations, but should not hard-code jurisdiction-specific legal advice. Market-data redistribution and broker terms must be respected by each adapter and distribution method.

## Privacy

The default deployment model is local/self-hosted. Telemetry, remote synchronization, and external AI access should be explicit opt-in features rather than hidden defaults.