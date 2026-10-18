# Module & Package Boundaries (quantx-architecture)

From `docs/architecture/40-package-organization-and-module-boundaries.md`.

- One bounded responsibility per package; ports separate from adapters where practical.
- Tests mirror the source package hierarchy.
- Compatibility shims are temporary and clearly named (existing shims: `research/data_quality.py`, `research/venue_adapters.py`, `execution/market_data.py`, `execution/market_ports.py`). New code uses target boundaries directly.
- Migration principle: existing files are moved/split when next modified — no risky repo-wide renames.
- Avoid repository-wide structural migrations while execution-integrity work is active.
- Deliberately distinct modules that must NOT be merged: `execution/order_lifecycle.py` vs `execution/receipts/lifecycle.py`.
