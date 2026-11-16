# QuantX Package Organization and Module Boundaries

## Purpose

QuantX uses purpose-specific packages to keep ownership and dependency direction understandable. Package structure should describe responsibilities that exist in the implementation, not reserve folders for hypothetical future features.

## Rules

1. Keep one cohesive responsibility per package.
2. Separate stable contracts from concrete adapters when that makes dependency direction clearer.
3. Keep market-specific rules outside universal domain packages.
4. Add a market implementation only when an approved, evidenced requirement exists; market-neutral contracts do not require scaffolding future markets.
5. Keep broker/account integration state separate from execution mechanics.
6. Separate research data, replay, provenance and experiment responsibilities where they have distinct contracts.
7. Organize tests around the behavior and ownership they verify.
8. Keep concrete optional integrations outside the universal core.
9. Keep compatibility shims temporary, explicit and identity-preserving where compatibility requires them.
10. Module size alone is not a reason to split. Split only when the proposed package owns a distinct invariant, test surface or stable integration boundary.

## Package-map reference

Use [41-current-package-map.md](41-current-package-map.md) for the implemented package layout and the deliberately high-level long-term organization. Its target map is explanatory, not a requirement to create packages before an implemented use case needs them.

## Migration principle

Prefer the smallest coherent structure that preserves clear ownership. Do not reorganize packages merely to make the tree symmetrical or to match a speculative target.

When a real change exposes a responsibility that belongs behind an independent invariant, test surface or stable integration boundary, move or split only the affected code and migrate its consumers safely. Avoid repository-wide structural migrations without a demonstrated need and regression coverage.
