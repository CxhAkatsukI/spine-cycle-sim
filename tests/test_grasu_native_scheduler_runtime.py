from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = (
    ROOT / "docs/evidence/grasu_native_scheduler_runtime_20260725.json"
)
BASE_RESULTS = ROOT / "docs/evidence/grasu_native_hw_matrix/simulation"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class NativeSchedulerRuntimeEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    def test_claim_is_host_runtime_only(self) -> None:
        self.assertEqual(
            self.evidence["claim_class"], "simulator_host_runtime_only"
        )
        self.assertEqual(
            self.evidence["status"], "PASS_EQUIVALENCE_RUNTIME_GATE_OPEN"
        )

    def test_before_and_after_result_hashes_are_identical(self) -> None:
        for case in self.evidence["cases"]:
            self.assertEqual(
                case["baseline_result_sha256"],
                case["optimized_result_sha256"],
            )
            committed = BASE_RESULTS / f"{case['case']}.result.json"
            self.assertEqual(sha256(committed), case["baseline_result_sha256"])

    def test_speedup_and_reduction_are_derived_from_wall_time(self) -> None:
        for case in self.evidence["cases"]:
            before = float(case["baseline_seconds"])
            after = float(case["optimized_seconds"])
            self.assertLess(after, before)
            self.assertAlmostEqual(case["speedup"], before / after, places=5)
            self.assertAlmostEqual(
                case["reduction_pct"], (before - after) / before * 100, places=5
            )

    def test_stress_projection_is_explicit_and_gate_remains_open(self) -> None:
        projection = self.evidence["stress_projection"]
        basis = next(
            case
            for case in self.evidence["cases"]
            if case["case"] == projection["basis_case"]
        )
        expected_minutes = (
            basis["optimized_seconds"] * 4096 / basis["supersteps"] / 60
        )
        self.assertAlmostEqual(projection["projected_minutes"], expected_minutes)
        self.assertEqual(projection["status"], "runtime_gate_not_met")
        self.assertGreater(projection["projected_minutes"], 60.0)


if __name__ == "__main__":
    unittest.main()
