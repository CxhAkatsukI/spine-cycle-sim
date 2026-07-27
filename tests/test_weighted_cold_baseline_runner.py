from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_candidate10_spine_weighted_cold_baselines.py"
SPEC = importlib.util.spec_from_file_location("weighted_cold_runner", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class WeightedColdBaselineRunnerTest(unittest.TestCase):
    def test_restore_final_values_validates_compacted_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = [0, 3, 7]
            encoded = json.dumps(values, separators=(",", ":")).encode("ascii")
            (root / "result.json").write_text(
                json.dumps({"final_values": values}), encoding="utf-8"
            )
            restored = MODULE._restore_final_values(
                root,
                {
                    "final_values_count": len(values),
                    "final_values_sha256": hashlib.sha256(encoded).hexdigest(),
                },
            )
            self.assertEqual(restored["final_values"], values)
            with self.assertRaisesRegex(RuntimeError, "hash"):
                MODULE._restore_final_values(
                    root,
                    {
                        "final_values_count": len(values),
                        "final_values_sha256": "0" * 64,
                    },
                )

    def test_validator_requires_exact_dynamic_prefix(self) -> None:
        cold = {
            "success": True,
            "correctness_mismatches": 0,
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
            "cycles": 10,
            "backend_requests": 4,
            "final_values": [0, 1],
            "rounds": 2,
            "round_cycles": [6, 4],
            "maintenance_cycles": 3,
            "architecture_profile_id": "p",
            "sst_plugin_sha256": "a" * 64,
        }
        dynamic = {
            "cold_cycles": 10,
            "cold_backend_requests": 4,
            "cold_final_values": [0, 1],
            "cold_rounds": 2,
            "cold_round_cycles": [6, 4],
            "cold_maintenance_cycles": 3,
            "architecture_profile_id": "p",
            "sst_plugin_sha256": "a" * 64,
        }
        self.assertEqual(MODULE._validate_cold_prefix(cold, dynamic), [])
        dynamic["cold_cycles"] = 11
        self.assertEqual(MODULE._validate_cold_prefix(cold, dynamic), ["cycles"])
