---
name: quantx-testing
description: Use when writing, fixing, or running tests in QuantX — pytest conventions, test file/function naming, mirrored test tree, fixtures vs factory helpers, fakes, skip rules, parametrize usage, and exact pytest commands. Front-load keywords: test, pytest, write a test, regression test, test fails, test suite.
---

# QuantX Testing

## Running tests

```powershell
uv run pytest -q                                   # full suite (addopts=-q, testpaths=["tests"])
uv run pytest tests/unit -q                        # fast layer
uv run pytest tests/unit/execution -q              # execution slice
uv run pytest tests/unit/execution/paper -q        # paper venue
uv run pytest tests/unit/plugins/dhan -q           # Dhan slice
uv run pytest path/to/test_file.py::test_name -q   # single test
```

Python wrappers: `uv run python scripts/test_fast.py`, `scripts/test_all.py`, `scripts/test_execution.py`.

## Structure — mirror the source tree

There is **only one layer: `tests/unit/`**. No `tests/integration/`, no `tests/e2e/`, **no `conftest.py` anywhere in the repo.**

Tests mirror source exactly (rule #7 of `docs/architecture/40-package-organization-and-module-boundaries.md`):

```
src/quantx/execution/trading_gate.py  ↔  tests/unit/execution/test_trading_gate.py
src/quantx/india/execution_rules.py   ↔  tests/unit/india/test_execution_rules.py
```

Every test directory has `__init__.py` (exception: `tests/unit/india/`).

## Writing a test

- File: `test_<module>.py`. Some encode a batch ID instead (`test_p1_contracts.py`, `test_r0b_broker_timeout.py`).
- Function: `test_<behavior_in_sentence>` with explicit `-> None` annotation:

```python
def test_registry_rejects_duplicate_plugin_ids() -> None:
    ...
```

- **Established convention: private factory helpers prefixed with `_` rather than shared pytest fixtures** (inspect the repository before claiming fixture counts — do not store transient counts in this skill):

```python
def _instrument() -> Instrument: ...
def _request() -> ApprovedExecutionRequest: ...
```

- Fakes are named `Fake*`, `Stub*`, `InMemory*` (e.g. `FakePlugin`, `StubStrategy`, `InMemoryReferenceBrokerTransport`).
- Error assertions use `pytest.raises(..., match="...")`; otherwise plain `assert`.
- `@pytest.mark.parametrize` is used sparingly; inspect the repository before making claims about usage counts.
- Optional-dependency skip pattern (`tests/unit/plugins/dhan/test_host.py:323`):

```python
pytest.importorskip("dhanhq", reason="optional dhan extra is not installed")
```

## Discipline

Writing/fixing tests is permitted only during an explicitly assigned implementation task. During VALIDATION ONLY, tests are executed and analyzed read-only; the worker must not modify tests.

Per the 7-step implementation discipline: make the smallest production change, then **add a focused regression test** for the specific gap. Run the focused slice first, then the full suite.

Repository gate: `pytest green + changed-file Ruff clean + git diff --check clean`.

The current validation/test-count baseline is authoritative in `docs/STATUS.md` — read it for the baseline; do not store transient repository counts in this skill. Testing itself is architectural — broker/data adapters must pass a common contract suite (`docs/architecture/11-testing-and-contracts.md`).
