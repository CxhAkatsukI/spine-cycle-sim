"""Verify portable chronological evidence, layout checks and exact old replay."""

import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.shared_workloads import load_slice
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.resident_real.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.resident_real.preparation import (
    STATUS, facts)
from tests.test_grasu_metadata_lifecycle_delivery import check_capsule

FOLDER = (Path(__file__).resolve().parents[1] / "docs/experiments/comparisons/"
          "grasu_regraph_stage_validation/evaluation_impact/sharded_batch/metadata_layout/resident_real")


class ResidentChronologicalDeliveryTests(unittest.TestCase):
    def test_complete_matrix_reanalyzes_without_baseline_admission(self):
        report = json.loads((FOLDER / "evidence/matrix.json").read_text())
        index = json.loads((FOLDER / "evidence/index.json").read_text())
        self.assertEqual(report["status"], STATUS)
        self.assertEqual(report["errors"], [])
        summary = analyze(report["rows"], contract=report["contract"])
        self.assertEqual(summary["prediction_rows"], 18)
        self.assertEqual(summary["batch_observations"], 54)
        for key, value in summary.items():
            self.assertEqual(report[key], value)
            self.assertEqual(index[key], value)
        for key in ("production_baseline_admitted", "hardware_timing_admitted",
                    "publication_match_admitted", "host_inclusive_timing_admitted",
                    "production_layout_changed", "new_spine_comparison_executed"):
            self.assertFalse(index[key])
        check_capsule(self, FOLDER / "evidence")

    def test_portable_inputs_reconstruct_independent_work_counts(self):
        report = json.loads((FOLDER / "evidence/matrix.json").read_text())
        with tarfile.open(FOLDER / "evidence/raw_runs.tar.gz") as archive, tempfile.TemporaryDirectory() as directory:
            self.assertEqual(json.loads(archive.extractfile("input_contract.json").read()), report["contract"])
            for name, expected in report["contract"]["cases"].items():
                dataset = name.split("-", 1)[0]
                paths = []
                for filename in ("base.slice", "insert-65536.slice"):
                    path = Path(directory) / (dataset + "-" + filename)
                    path.write_bytes(archive.extractfile(f"inputs/{dataset}/{filename}").read())
                    paths.append(path)
                actual = facts(*(load_slice(path) for path in paths))
                self.assertEqual(actual, {key: expected[key] for key in actual})

    def test_stdout_and_each_layout_equivalence_check_are_retained(self):
        report = json.loads((FOLDER / "evidence/matrix.json").read_text())
        checks = []
        with tarfile.open(FOLDER / "evidence/raw_runs.tar.gz") as archive:
            for row in report["rows"]:
                label = f"lat{row['latency']}_{row['case']}_{row['arm']}"
                payload = archive.extractfile(f"raw/{label}.stdout.txt").read().decode().strip()
                tag, _, body = payload.partition(" ")
                self.assertEqual(tag, "RESIDENT_G_RESULT")
                self.assertEqual(json.loads(body), row["observation"])
                stderr = archive.extractfile(f"raw/{label}.stderr.txt").read().decode().splitlines()
                values = [json.loads(line.partition(" ")[2]) for line in stderr
                          if line.startswith("RESIDENT_WRAPPER_CHECK ")]
                if row["arm"] != "candidate-runtime-23":
                    self.assertEqual(values, [])
                    continue
                self.assertEqual([v["batch"] for v in values], [0, 1, 2])
                for value, batch in zip(values, row["observation"]["batches"]):
                    self.assertTrue(value["full_counters_equal_in_each_layout"])
                    self.assertEqual(value["wrapper_cycles"], value["manual_wrapper_cycles"])
                    self.assertEqual(value["resident_cycles"], value["fresh_resident_cycles"])
                    self.assertEqual(value["resident_cycles"], batch["cycles"])
                    self.assertEqual(value["resident_matches_wrapper_layout"], not value["changed_regions"])
                    if value["resident_matches_wrapper_layout"]:
                        self.assertEqual(value["wrapper_cycles"], value["resident_cycles"])
                    checks.append((row["case"], value))
        self.assertEqual(len(checks), 18)
        su_first = [v for case, v in checks if case.startswith("SU-") and v["batch"] == 0]
        self.assertEqual(len(su_first), 2)
        self.assertTrue(all(any(r["name"].startswith("row")
                               and r["resident_channel"] != r["wrapper_channel"]
                               for r in v["changed_regions"]) for v in su_first))

    def test_execution_limits_and_copy_costs_are_explicit(self):
        report = json.loads((FOLDER / "evidence/matrix.json").read_text())
        for step in report["steps"]:
            self.assertEqual(step["exit_code"], 0)
            self.assertFalse(step["timed_out"])
            self.assertEqual(step["memory_limit_gib"], 2)
            self.assertEqual(step["reserve_gib"], 8)
            self.assertGreaterEqual(step["available_before_bytes"], 10 * 2**30)
        for row in report["rows"]:
            resource = row["observation"]["resources"]
            if resource is None:
                continue
            self.assertEqual(resource["interbatch_metadata_upload_bytes"], 0)
            copies = [r for r in resource["regions"] if "-cu" in r["name"]]
            self.assertEqual(resource["extra_metadata_bytes"], sum(r["allocated_bytes"] for r in copies))
            self.assertEqual(len(copies), row["observation"]["total_shards"] * 8
                             if row["arm"] == "runtime-both-copies" else 0)
            self.assertGreater(resource["initial_metadata_upload_bytes"], resource["extra_metadata_bytes"])

    def test_failed_su_attempt_is_not_silently_discarded(self):
        folder = FOLDER / "preflight"
        check_capsule(self, folder)
        index = json.loads((folder / "index.json").read_text())
        report = json.loads((folder / "matrix.json").read_text())
        self.assertEqual(index["status"], "FAILED_PREFLIGHT_RETAINED")
        self.assertEqual(index["accepted_full_matrix_rows"], 0)
        self.assertEqual(report["status"], "FAILED_RETAINED")
        self.assertEqual(len(report["rows"]), 16)
        self.assertEqual(len(report["errors"]), 2)
        self.assertEqual({(e["case"], e["latency"], e["arm"]) for e in report["errors"]}, {
            ("SU-resident-chronological", latency, "candidate-runtime-23") for latency in (64, 128)})

    def test_old_full_lifecycle_is_exact_after_both_extractions(self):
        previous = json.loads((FOLDER.parent / "lifecycle/evidence/matrix.json").read_text())

        def observations(report):
            return {(r["case"], r["latency"], r["arm"]):
                    (r["observation"], r["state_sha256"], [s["sha256"] for s in r["batch_states"]])
                    for r in report["rows"]}

        for name in ("replay", "replay_final"):
            folder = FOLDER / name
            check_capsule(self, folder)
            replay = json.loads((folder / "matrix.json").read_text())
            self.assertEqual(replay["errors"], [])
            self.assertEqual(len(replay["rows"]), 12)
            self.assertEqual(observations(previous), observations(replay))


if __name__ == "__main__":
    unittest.main()
