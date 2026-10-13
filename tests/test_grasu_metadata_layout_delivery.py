"""Verify the frozen layout diagnostic without machine-local raw artifacts."""

import hashlib
import json
from pathlib import Path
import tarfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.metadata_layout.preparation import (
    ARMS, CONTROLS, PREVIOUS, STATUS, baseline_value)
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.preparation import ARMS as BASE_ARMS

FOLDER = PREVIOUS.parent.parent.parent / "metadata_layout/evidence"


class MetadataLayoutDeliveryTests(unittest.TestCase):
    def test_complete_matrix_reanalyzes_without_admitting_a_baseline(self):
        report = json.loads((FOLDER / "matrix.json").read_text())
        index = json.loads((FOLDER / "index.json").read_text())
        result = analyze(report["rows"], report["contract"])
        self.assertEqual(report["status"], STATUS)
        self.assertEqual(report["errors"], [])
        self.assertEqual(len(report["rows"]), 72)
        self.assertEqual(set(ARMS), {row["arm"] for row in report["rows"]})
        for key, value in result.items():
            self.assertEqual(report[key], value)
            self.assertEqual(index[key], value)
        for key in ("production_baseline_admitted", "hardware_timing_admitted",
                    "publication_match_admitted", "host_inclusive_timing_admitted",
                    "production_layout_changed", "new_spine_comparison_executed"):
            self.assertFalse(index[key])

    def test_old_36_rows_replay_exactly_with_read_only_instrumentation(self):
        report = json.loads((FOLDER / "matrix.json").read_text())
        previous = json.loads(PREVIOUS.read_text())
        def values(rows):
            return {(row["case"], row["latency"], row["arm"]): baseline_value(row) for row in rows}
        replay = [row for row in report["rows"] if row["arm"] in BASE_ARMS]
        self.assertEqual(len(replay), 36)
        self.assertEqual(values(previous["rows"]), values(replay))
        self.assertEqual(values(previous["rows"]), values(report["contract"]["baseline_rows"]))

    def test_frozen_inputs_raw_observations_and_resource_logs_are_complete(self):
        report = json.loads((FOLDER / "matrix.json").read_text())
        index = json.loads((FOLDER / "index.json").read_text())
        for entry in index["reports"]:
            path = FOLDER / entry["file"]
            self.assertEqual(sha256_file(path), entry["sha256"])
            self.assertEqual(path.stat().st_size, entry["bytes"])
        with tarfile.open(FOLDER / "raw_runs.tar.gz") as archive:
            self.assertEqual(sorted(archive.getnames()), sorted(e["member"] for e in index["raw_members"]))
            for entry in index["raw_members"]:
                payload = archive.extractfile(entry["member"]).read()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["sha256"])
                self.assertEqual(len(payload), entry["bytes"])
            for pin in report["input_pins"]:
                payload = archive.extractfile(pin["member"]).read()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), pin["sha256"])
            for row in report["rows"]:
                label = f"lat{row['latency']}_{row['case']}_{row['arm']}"
                text = archive.extractfile("raw/" + label + ".stdout.txt").read().decode().strip()
                tag, _, body = text.partition(" ")
                self.assertEqual(tag, "METADATA_G_RESULT")
                self.assertEqual(json.loads(body), row["observation"])
            for step in report["steps"]:
                resource = Path(step["stdout"]).name.replace(".stdout.txt", ".resources.json")
                self.assertEqual(json.loads(archive.extractfile("raw/" + resource).read()), step)
                self.assertEqual(step["exit_code"], 0)
                self.assertFalse(step["timed_out"])
                self.assertEqual(step["memory_limit_gib"], 2)
                self.assertGreaterEqual(step["reserve_gib"], 8)

    def test_replica_resources_are_charged_on_every_control(self):
        report = json.loads((FOLDER / "matrix.json").read_text())
        observations = {(row["case"], row["latency"], row["arm"]): row["observation"] for row in report["rows"]}
        for row in report["rows"]:
            if row["arm"] not in CONTROLS:
                continue
            baseline = observations[row["case"], row["latency"], BASE_ARMS[2]]["resources"]
            resource = row["observation"]["resources"]
            extra = 4 * (baseline["row_allocated_bytes"] * (row["arm"] != CONTROLS[1]) +
                         baseline["binary_allocated_bytes"] * (row["arm"] != CONTROLS[0]))
            self.assertEqual(resource["extra_metadata_bytes"], extra)
            self.assertEqual(resource["allocated_bytes"], baseline["allocated_bytes"] + extra)
            self.assertGreaterEqual(resource["channel_span_bytes"], resource["allocated_bytes"])
            self.assertGreater(extra, 0)

    def test_preflight_failures_smokes_and_partial_attempt_are_retained(self):
        folder = FOLDER.parent / "preflight"
        index = json.loads((folder / "index.json").read_text())
        self.assertEqual(index["status"], "PREFLIGHT_AND_INTERRUPTED_DIAGNOSTIC_RETAINED")
        self.assertEqual(index["accepted_full_matrix_rows"], 0)
        self.assertEqual(index["partial_accepted_rows"], 7)
        for entry in index["reports"]:
            path = folder / entry["file"]
            self.assertEqual(sha256_file(path), entry["sha256"])
            self.assertEqual(path.stat().st_size, entry["bytes"])
        with tarfile.open(folder / "raw_runs.tar.gz") as archive:
            self.assertEqual(sorted(archive.getnames()), sorted(e["member"] for e in index["raw_members"]))
            for entry in index["raw_members"]:
                payload = archive.extractfile(entry["member"]).read()
                self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["sha256"])
                self.assertEqual(len(payload), entry["bytes"])
            failed = json.loads(archive.extractfile("smoke-v1/steps.json").read())
            self.assertEqual(failed[-1]["exit_code"], 2)
            smoke = json.loads(archive.extractfile("smoke-v2/steps.json").read())
            self.assertEqual(len(smoke), 8)
            self.assertTrue(all(step["exit_code"] == 0 and not step["timed_out"] for step in smoke))
            partial = json.loads(archive.extractfile("attempt-v1/results.json").read())
            self.assertEqual(partial["status"], "FAILED_RETAINED")
            self.assertEqual(partial["error"], "KeyboardInterrupt()")
            self.assertEqual(len(partial["rows"]), 7)


if __name__ == "__main__":
    unittest.main()
