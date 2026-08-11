from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.build_current_fpga_rq3_v11 import case_payload


class CurrentFPGARQ3V11Tests(unittest.TestCase):
    def test_case_payload_preserves_role_and_physical_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result_path = Path(temporary) / "result.json"
            result_path.write_text("{}\n", encoding="ascii")
            payload = case_payload(
                execution_id="case",
                dataset="au",
                algorithm="connected_components",
                scenario="insert",
                role="trace_calibration",
                user_mutations=8,
                physical_records=16,
                raw_result_path=result_path,
                result={
                    "success": True,
                    "cycles": 100,
                    "maintenance_cycles": 20,
                    "correctness_mismatches": 0,
                    "architecture_correctness_mismatches": 0,
                    "mathematical_correctness_mismatches": 0,
                },
                plugin_sha256="a" * 64,
            )
        self.assertEqual(payload["rq3_role"], "trace_calibration")
        self.assertEqual(payload["case"]["update"]["physical_records"], 16)
        self.assertEqual(payload["row"]["cycles"], 100)

    def test_case_payload_rejects_failed_correctness(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result_path = Path(temporary) / "result.json"
            result_path.write_text("{}\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "correctness_mismatches"):
                case_payload(
                    execution_id="case",
                    dataset="au",
                    algorithm="weighted_sssp",
                    scenario="insert",
                    role="trace_calibration",
                    user_mutations=8,
                    physical_records=8,
                    raw_result_path=result_path,
                    result={
                        "success": True,
                        "cycles": 100,
                        "correctness_mismatches": 1,
                    },
                    plugin_sha256="a" * 64,
                )


if __name__ == "__main__":
    unittest.main()
