"""Check portable resident evidence and the complete pre-extraction replay."""

import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.delivery import package
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.lifecycle.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.lifecycle.preparation import STATUS

FOLDER = (Path(__file__).resolve().parents[1] / "docs/experiments/comparisons/"
          "grasu_regraph_stage_validation/evaluation_impact/sharded_batch/metadata_layout/lifecycle")


def check_capsule(test, folder):
    index = json.loads((folder / "index.json").read_text())
    for item in index["reports"]:
        path = folder / item["file"]
        test.assertEqual(sha256_file(path), item["sha256"])
        test.assertEqual(path.stat().st_size, item["bytes"])
    with tarfile.open(folder / "raw_runs.tar.gz") as archive:
        test.assertEqual(sorted(archive.getnames()), sorted(i["member"] for i in index["raw_members"]))
        for item in index["raw_members"]:
            payload = archive.extractfile(item["member"]).read()
            test.assertEqual(hashlib.sha256(payload).hexdigest(), item["sha256"])
            test.assertEqual(len(payload), item["bytes"])


class ResidentMetadataDeliveryTests(unittest.TestCase):
    def test_changed_intermediate_state_is_rejected_before_creating_capsule(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "final.u32le"
            state.write_bytes(b"checked final state")
            intermediate = root / "batch.u32le"
            intermediate.write_bytes(b"changed intermediate state")
            report = root / "matrix.json"
            report.write_text(json.dumps({"status": STATUS, "errors": [], "pins": [],
                "rows": [{"state_path": str(state), "state_sha256": sha256_file(state),
                          "batch_states": [{"path": str(intermediate), "sha256": "0" * 64}]}]}))
            with self.assertRaises(ValueError):
                package(root / "evidence", report, status=STATUS, analyze_rows=lambda rows: {})
            self.assertFalse((root / "evidence").exists())

    def test_complete_matrix_reanalyzes_without_baseline_admission(self):
        report = json.loads((FOLDER / "evidence/matrix.json").read_text())
        index = json.loads((FOLDER / "evidence/index.json").read_text())
        self.assertEqual(report["status"], STATUS)
        self.assertEqual(report["errors"], [])
        summary = analyze(report["rows"])
        self.assertEqual(summary["prediction_rows"], 12)
        self.assertEqual(summary["batch_observations"], 36)
        self.assertTrue(summary["lifecycle_payload_and_traffic_pass"])
        for key, value in summary.items():
            self.assertEqual(report[key], value)
            self.assertEqual(index[key], value)
        for key in ("production_baseline_admitted", "hardware_timing_admitted",
                    "publication_match_admitted", "host_inclusive_timing_admitted",
                    "production_layout_changed", "new_spine_comparison_executed"):
            self.assertFalse(index[key])

    def test_raw_observations_resource_logs_and_contract_are_preserved(self):
        check_capsule(self, FOLDER / "evidence")
        report = json.loads((FOLDER / "evidence/matrix.json").read_text())
        with tarfile.open(FOLDER / "evidence/raw_runs.tar.gz") as archive:
            self.assertEqual(json.loads(archive.extractfile("input_contract.json").read()), report["contract"])
            for row in report["rows"]:
                label = f"lat{row['latency']}_{row['case']}_{row['arm']}"
                payload = archive.extractfile("raw/" + label + ".stdout.txt").read().decode().strip()
                tag, _, body = payload.partition(" ")
                self.assertEqual(tag, "RESIDENT_G_RESULT")
                self.assertEqual(json.loads(body), row["observation"])
            for step in report["steps"]:
                name = Path(step["stdout"]).name.replace(".stdout.txt", ".resources.json")
                self.assertEqual(json.loads(archive.extractfile("raw/" + name).read()), step)
                self.assertEqual(step["exit_code"], 0)
                self.assertFalse(step["timed_out"])
                self.assertEqual(step["memory_limit_gib"], 2)
                self.assertEqual(step["reserve_gib"], 8)
                self.assertGreaterEqual(step["available_before_bytes"], (2 + 8) * 2**30)

    def test_fixed_reservation_copy_storage_and_upload_are_not_free(self):
        report = json.loads((FOLDER / "evidence/matrix.json").read_text())
        for row in report["rows"]:
            if row["arm"] == "original-prepared-shards":
                continue
            resource = row["observation"]["resources"]
            self.assertTrue(resource["metadata_reservations_fixed"])
            self.assertEqual(resource["interbatch_metadata_upload_bytes"], 0)
            self.assertEqual(resource["used_channels"], 23)
            self.assertEqual(resource["allocated_bytes"], 56709120 + resource["extra_metadata_bytes"])
            copies = row["arm"] == "runtime-both-copies"
            self.assertEqual(resource["extra_metadata_bytes"], 25214976 if copies else 0)
            self.assertEqual(resource["initial_metadata_upload_bytes"], 31476720 if copies else 6295344)
            self.assertEqual(resource["channel_span_bytes"], 113360896 if copies else 56709120)

    def test_failed_build_and_duplicate_initiator_attempts_remain_failures(self):
        folder = FOLDER / "preflight"
        check_capsule(self, folder)
        index = json.loads((folder / "index.json").read_text())
        self.assertEqual(index["status"], "FAILED_PREFLIGHT_RETAINED")
        self.assertEqual(index["accepted_full_matrix_rows"], 0)
        with tarfile.open(folder / "raw_runs.tar.gz") as archive:
            build = json.loads(archive.extractfile("attempt-v1/results.json").read())
            duplicate = json.loads(archive.extractfile("attempt-v2/results.json").read())
            self.assertEqual(build["status"], "FAILED_RETAINED")
            self.assertEqual(build["rows"], [])
            self.assertNotEqual(build["steps"][-1]["exit_code"], 0)
            self.assertEqual(duplicate["status"], "FAILED_RETAINED")
            self.assertEqual(len(duplicate["rows"]), 4)
            self.assertEqual(len(duplicate["errors"]), 8)
            self.assertTrue(all(r["arm"] == "original-prepared-shards" for r in duplicate["rows"]))

    def test_complete_72_row_replay_is_exact_after_replica_helper_extraction(self):
        from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.analysis import analyze as analyze_layout

        previous = json.loads((FOLDER.parent / "evidence/matrix.json").read_text())
        replay = json.loads((FOLDER / "replay/matrix.json").read_text())
        index = json.loads((FOLDER / "replay/index.json").read_text())
        self.assertEqual(replay["errors"], [])
        self.assertEqual(len(replay["rows"]), 72)
        self.assertEqual(len(previous["rows"]), 72)

        def observations(rows):
            return {(r["case"], r["latency"], r["arm"]):
                    (r["observation"], r["state_sha256"]) for r in rows}

        self.assertEqual(observations(previous["rows"]), observations(replay["rows"]))
        for key, value in analyze_layout(replay["rows"], replay["contract"]).items():
            self.assertEqual(replay[key], value)
            self.assertEqual(index[key], value)
        check_capsule(self, FOLDER / "replay")


if __name__ == "__main__":
    unittest.main()
