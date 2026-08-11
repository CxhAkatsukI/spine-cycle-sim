from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.finalize_current_fpga_evaluation_v12 import (
    DEFAULT_OUT,
    DEFAULT_SIMULATION_ROOT,
    require_status,
)


class FinalizeCurrentFPGAEvaluationV12Tests(unittest.TestCase):
    def test_defaults_bind_current_v12_paths(self) -> None:
        self.assertIn("current_fpga_v12", str(DEFAULT_SIMULATION_ROOT))
        self.assertEqual(DEFAULT_OUT.name, "evaluation_refresh_20260810")

    def test_require_status_rejects_nonpassing_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "gate.json"
            path.write_text(json.dumps({"status": "INCOMPLETE"}), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "evidence gate failed"):
                require_status(path, "PASS")


if __name__ == "__main__":
    unittest.main()
