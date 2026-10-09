"""Run execution-focused tests with uv."""

from __future__ import annotations

import subprocess


if __name__ == "__main__":
    raise SystemExit(subprocess.call(["uv", "run", "pytest", "tests/unit/execution", "-q"]))
