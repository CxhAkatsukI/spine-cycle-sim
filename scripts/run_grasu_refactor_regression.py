#!/usr/bin/env python3
"""Compatibility entry for the original G+R refactor regression command."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_component_refactor_regression import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
