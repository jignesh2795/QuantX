"""Run the fast unit-test layer with uv."""

from __future__ import annotations

import subprocess


if __name__ == "__main__":
    raise SystemExit(subprocess.call(["uv", "run", "pytest", "tests/unit", "-q"]))
