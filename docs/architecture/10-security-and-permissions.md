# QuantX Security and Permissions

QuantX should use capability-based authorization rather than broad role-only access.

## Example capabilities

- READ_MARKET_DATA
- READ_FUNDS
- READ_POSITIONS
- CREATE_PAPER_ORDER
- CREATE_LIVE_ORDER
- CANCEL_ORDER
- START_STRATEGY
- STOP_STRATEGY
- ACCESS_BROKER
- ACCESS_SECRETS
- EXECUTE_LIVE

## Safety boundary

AI agents and community plugins should not receive broker credentials merely because they can generate signals or strategies.

Live execution requires the normal policy, risk, approval and execution path.

## Plugin trust

Plugins are classified as trusted, community or sandboxed. Sandboxed code receives restricted access to filesystem, network and secrets unless explicitly granted.
