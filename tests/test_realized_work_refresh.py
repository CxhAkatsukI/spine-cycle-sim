from __future__ import annotations

from collections import Counter
import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.analysis import stage_rows, write_csv
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.delivery import (
    archive, merge_fig9, read_csv,
)
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.matrix import (
    FRESH, OLD, ROOT, SELECTION,
)
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.run import admit
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.verify import (
    verify_archive, verify_comparisons,
)
from spine_cycle_sim.experiments.rq3 import TEN_STAGE_KEYS


class RealizedWorkRefreshTests(unittest.TestCase):
    def test_csv_output_uses_lf_and_preserves_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "table.csv"
            rows = [{"case": "a,b", "cycles": "12.5"}]
            write_csv(path, rows)
            self.assertNotIn(b"\r", path.read_bytes())
            self.assertEqual(read_csv(path), rows)

    def test_frozen_selection_covers_old_split_and_eleven_bars(self):
        template = read_csv(OLD / "data/fig11_rq3_prediction_rows.csv")
        self.assertEqual(Counter(r["role"] for r in template), {
            "synthetic_calibration": 18, "trace_calibration": 6, "trace_holdout": 17,
        })
        self.assertEqual(len(SELECTION), 11)
        self.assertEqual(len({r[2] for r in SELECTION}), 11)
        selected = {row[2] for row in SELECTION} - {"zero_net_sssp"}
        self.assertTrue(selected <= {row["execution_id"] for row in template})

    def test_fixed_threshold_replaces_only_respr_and_rejects_duplicate(self):
        original = [{"algorithm": a, "dataset": d, "value": "old"}
                    for a in ("SSSP", "CC", "ResPR") for d in ("AU", "SU", "WK")]
        fixed = [{"algorithm": "ResPR", "dataset": d, "value": "fixed"}
                 for d in ("AU", "SU", "WK")]
        rows = merge_fig9(original, fixed)
        self.assertEqual([r["value"] for r in rows], ["old"] * 6 + ["fixed"] * 3)
        fixed[2]["dataset"] = "AU"
        with self.assertRaisesRegex(ValueError, "duplicate"):
            merge_fig9(original, fixed)

    def test_stage_ledger_requires_actual_conservation_and_admission(self):
        rows = []
        for _, _, previous in SELECTION:
            row = dict.fromkeys(TEN_STAGE_KEYS, 1)
            row.update(execution_id=FRESH + previous, total_cycles=10,
                       ten_stage_supported=True, ten_stage_ledger_closed=True, ledger_closed=True)
            rows.append(row)
        self.assertEqual(len(stage_rows({"latency_rows": rows})), 11)
        invalid = copy.deepcopy(rows)
        invalid[0]["t_app_cycles"] += 1
        with self.assertRaisesRegex(ValueError, "conserve"):
            stage_rows({"latency_rows": invalid})
        rows[0]["ten_stage_supported"] = False
        with self.assertRaisesRegex(ValueError, "unsupported"):
            stage_rows({"latency_rows": rows})

    def test_carry_admission_uses_input_header_when_raw_vertices_absent(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            workload = ROOT / "tests/data/dynamic_nonmonotonic_initial.slice"
            raw = {"success": True, "correctness_mismatches": 0,
                   "maintenance_stage_ledger_closed": True, "cycles": 123}
            (directory / "result.json").write_text(json.dumps(raw))
            (directory / "summary.json").write_text(json.dumps({
                "status": "PASS", "sst_plugin_sha256": "test-plugin",
            }))
            case = {"out_dir": str(directory), "previous_execution_id": "rq3_trace_carry_l1_e8",
                    "execution_id": "test", "dataset_id": "test", "algorithm": "weighted_sssp",
                    "batch_size": 8, "physical_records": 8, "dataset_kind": "synthetic",
                    "role": "synthetic_calibration", "inputs": {"--workload": {"path": str(workload)}}}
            result = admit(case, "test-plugin")
            self.assertGreater(result["scalar_metrics"]["vertices"], 0)
            self.assertEqual(result["row"]["cycles"], 123)
            self.assertEqual(result["row"]["validation_contract"], "carry_fixture")
            self.assertNotIn("architecture_correctness_mismatches", result["row"])
            self.assertNotIn("mathematical_correctness_mismatches", result["row"])
            with self.assertRaisesRegex(ValueError, "plugin"):
                admit(case, "other-plugin")

    def test_archive_verification_detects_changed_index_and_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "input.json"
            source.write_text('{"status":"PASS"}\n')
            path = directory / "raw.tar.gz"
            index = archive(path, [(source, "runs/input.json")])
            self.assertEqual(verify_archive(path, index), 1)
            index["members"][0]["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "member changed"):
                verify_archive(path, index)
            index["sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "archive hash"):
                verify_archive(path, index)

    def test_large_archives_are_split_and_joined_with_hash_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "input.json"
            source.write_text('{"status":"PASS"}\n')
            path = directory / "raw.tar.gz"
            index = archive(path, [(source, "runs/input.json")], part_bytes=80)
            self.assertFalse(path.exists())
            self.assertGreater(len(index["parts"]), 1)
            self.assertEqual(verify_archive(path, index), 1)
            part = directory / index["parts"][0]["path"]
            part.write_bytes(b"bad")
            with self.assertRaisesRegex(ValueError, "part changed"):
                verify_archive(path, index)

    def test_comparison_verification_checks_counts_ratios_and_single_batch(self):
        source = ROOT / "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/figure_refresh"
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ("fig8_update_cross_dataset.csv", "fig8_update_batch_sensitivity.csv"):
                write_csv(directory / "data" / name, read_csv(source / "data" / name))
            for name in ("fig9_memory_energy_rows.csv", "fig9_arms.csv"):
                original = read_csv(source / "multialgorithm/data" / name)
                fixed = read_csv(source / "respr_fixed_epsilon/data" / name)
                rows = [r for r in original if r["algorithm"] != "ResPR"] + fixed
                write_csv(directory / "data" / name, rows)
            self.assertEqual(verify_comparisons(directory)["fig9_pairs"], 9)
            path = directory / "data/fig8_update_cross_dataset.csv"
            rows = read_csv(path)
            rows[0]["batch_count"] = 10
            write_csv(path, rows)
            with self.assertRaisesRegex(ValueError, "one-batch"):
                verify_comparisons(directory)
            rows[0]["batch_count"] = 1
            write_csv(path, rows)
            path = directory / "data/fig9_arms.csv"
            rows = read_csv(path)
            rows[0]["read_bytes"] = int(rows[0]["read_bytes"]) + 1
            write_csv(path, rows)
            with self.assertRaisesRegex(ValueError, "byte ledger"):
                verify_comparisons(directory)


if __name__ == "__main__":
    unittest.main()
