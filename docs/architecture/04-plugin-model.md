# QuantX Plugin Model

## Plugin categories

- broker adapters
- market-data adapters
- strategy plugins
- research plugins
- analytics plugins
- AI/provider plugins
- notification/integration plugins
- application extensions

## Adapter vs plugin

An adapter connects QuantX to an external system. A plugin extends platform capability.

Examples:

- `quantx-broker-dhan` — adapter
- `quantx-data-nse` — adapter
- `quantx-strategy-iron-condor` — plugin
- `quantx-research-vectorbt` — plugin
- `quantx-ai-local` — plugin

## Safety boundary

Plugins generate intents or provide capabilities. Live execution remains owned by QuantX risk, policy and execution services.

A community plugin must not gain broker secrets merely because it can generate a strategy or signal.

## Compatibility

Plugins declare:

- plugin name and version
- plugin type
- supported QuantX API range
- capabilities provided
- capabilities required
- markets and instruments supported
- security/trust level

## Trust levels

- Trusted — reviewed core-quality integrations
- Community — externally maintained plugins with defined permissions
- Sandboxed — untrusted or experimental code with restricted filesystem, network and secret access

## Contract testing

Each adapter/plugin category has a reusable contract suite. Broker adapters, for example, must demonstrate connection, authentication, instrument discovery, account state, order lifecycle, fills, reconciliation and recovery behavior.
