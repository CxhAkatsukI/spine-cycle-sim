from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_refactor31_real_slice_matrix.py"
SPEC = importlib.util.spec_from_file_location("run_refactor31_matrix", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RunRefactor31RealSliceMatrixTests(unittest.TestCase):
    def test_case_id_is_stable(self) -> None:
        self.assertEqual(
            MODULE.case_id({"dataset": "AU", "target_edges": 100_000}),
            "AU_e100000",
        )

    def test_sim_command_preserves_resident_transfer_contract(self) -> None:
        command = MODULE.sim_command(
            {"dataset": "AU", "target_edges": 100, "path": "/tmp/a.slice", "source": 7},
            output=Path("/tmp/out"),
            profile=Path("/tmp/profile.json"),
            max_cycles=123,
            max_rounds=45,
        )
        self.assertIn("--resident-static-sssp", command)
        self.assertEqual(command[command.index("--source") + 1], "7")
        self.assertEqual(command[command.index("--max-cycles") + 1], "123")


if __name__ == "__main__":
    unittest.main()
