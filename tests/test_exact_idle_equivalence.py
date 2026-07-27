from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.evidence.exact_idle import (
    ExactIdleEquivalenceError,
    FULL_PAGERANK_SPINE_ADDITIONS,
    analyze_exact_idle_equivalence,
)


class ExactIdleEquivalenceTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        baseline = root / "baseline"
        candidate = root / "candidate"
        run_id = "case__full_pagerank"
        manifest = {
            "status": "PASS",
            "failure": None,
            "selected_run_ids": [run_id],
            "result_rows": 2,
            "paired_rows": 1,
        }
        for matrix in (baseline, candidate):
            matrix.mkdir()
            (matrix / "comparison_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            for system in ("spine", "grasu_regraph"):
                system_root = matrix / run_id / system
                dram = system_root / "dram/channel0"
                dram.mkdir(parents=True)
                result = {
                    "algorithm": "full_pagerank",
                    "cycles": 123,
                    "correctness_mismatches": 0,
                }
                if matrix == candidate and system == "spine":
                    result.update(
                        {key: index for index, key in enumerate(FULL_PAGERANK_SPINE_ADDITIONS)}
                    )
                (system_root / "result.json").write_text(
                    json.dumps(result, sort_keys=True), encoding="utf-8"
                )
                (system_root / "shared_run.json").write_text(
                    json.dumps({"wall_seconds": 2.0 if matrix == baseline else 1.0}),
                    encoding="utf-8",
                )
                (dram / "dramsim3.json").write_text("same\n", encoding="utf-8")
                (dram / "dramsim3epoch.json").write_text(
                    "same epoch\n", encoding="utf-8"
                )
        return baseline, candidate

    def test_accepts_old_fields_and_frozen_observability_additions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = analyze_exact_idle_equivalence(
                *self._fixture(Path(temporary))
            )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["system_results"], 2)
        self.assertEqual(result["dram_json_files_compared"], 4)
        self.assertEqual(result["host_speedup_geomean"], 2.0)

    def test_rejects_changed_preexisting_field(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            baseline, candidate = self._fixture(Path(temporary))
            path = candidate / "case__full_pagerank/spine/result.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            result["cycles"] += 1
            path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaisesRegex(ExactIdleEquivalenceError, "changed"):
                analyze_exact_idle_equivalence(baseline, candidate)

    def test_rejects_unexpected_or_missing_addition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            baseline, candidate = self._fixture(Path(temporary))
            path = candidate / "case__full_pagerank/spine/result.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            result.pop(next(iter(FULL_PAGERANK_SPINE_ADDITIONS)))
            path.write_text(json.dumps(result), encoding="utf-8")
            with self.assertRaisesRegex(ExactIdleEquivalenceError, "expected_added"):
                analyze_exact_idle_equivalence(baseline, candidate)

    def test_rejects_changed_dram_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            baseline, candidate = self._fixture(Path(temporary))
            path = candidate / "case__full_pagerank/grasu_regraph/dram/channel0/dramsim3.json"
            path.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ExactIdleEquivalenceError, "DRAM JSON changed"):
                analyze_exact_idle_equivalence(baseline, candidate)


if __name__ == "__main__":
    unittest.main()
