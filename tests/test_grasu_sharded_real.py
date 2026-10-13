"""Check real-input admission, search work and complete prediction scope."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tarfile
import unittest

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.analysis import analyze as analyze_synthetic
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.preparation import input_contract
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.real_analysis import analyze
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.real_inputs import contract, facts
from spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.study import input_arguments
from spine_cycle_sim.experiments.shared_workloads import SliceGraph, SliceRecord

PARENT = Path(__file__).resolve().parents[1] / (
    "docs/experiments/comparisons/grasu_regraph_stage_validation/evaluation_impact/sharded_batch")


def observations(declared):
    rows = []
    for item in declared["matrix"]:
        case = declared["cases"][item["case"]]
        physical, probes = case["physical_updates"], case["binary_probes"]
        pma = 2 * 131072 * 64
        value = {**item, **{key: case[key] for key in ("vertices", "live_edges", "physical_updates",
            "binary_probes", "multi_segment_updates")}, "total_shards": 1, "updated_shards": 1,
            "cache_updates": physical, "ddr_updates": 0, "row_reads": physical,
            "pma_read_bytes": pma, "pma_write_bytes": pma, "read_bytes": pma + physical * 16 + probes * 8,
            "write_bytes": pma, "full_payload_pass": True, "timing_kind": "declared_prediction", "cycles": 100}
        rows.append({**item, "observation": value, "state_sha256": "a" * 64})
    return rows


class RealGTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.declared = contract()

    def test_frozen_inputs_cover_every_declared_real_case(self):
        self.assertEqual(len(self.declared["cases"]), 6)
        self.assertEqual(len(self.declared["input_pins"]), 13)
        self.assertEqual(len(self.declared["matrix"]), 36)
        for case in self.declared["cases"].values():
            self.assertEqual(case["live_edges"], 8192)
            self.assertEqual(case["final_edges"], 8192)
            self.assertGreater(case["binary_probes"], 0)
            self.assertGreater(case["multi_segment_updates"], 0)

    def test_generalized_runner_keeps_synthetic_argument_contract(self):
        original = input_contract()
        self.assertEqual(input_arguments(original["matrix"][0], original, "sharded_g_execution"), [])
        item = self.declared["matrix"][0]
        case = self.declared["cases"][item["case"]]
        self.assertEqual(input_arguments(item, self.declared, "real_sharded_g_execution"),
                         [case["graph"], case["updates"]])
        with self.assertRaises(ValueError): input_arguments(item, self.declared, "unknown")

    def test_independent_search_counts_and_invalid_mutations(self):
        graph = SliceGraph("g", 32, tuple(SliceRecord(0, dst) for dst in range(1, 21)))
        batch = SliceGraph("u", 32, (SliceRecord(0, 1, 1, -1), SliceRecord(0, 1, 2)))
        result = facts(graph, batch)
        self.assertEqual(result["vertices"], 33)
        self.assertEqual(result["final_edges"], 20)
        self.assertEqual(result["multi_segment_updates"], 2)
        self.assertEqual(result["binary_probes"], 2)
        for bad in ((SliceRecord(0, 1),), (SliceRecord(0, 31, 1, -1),),
                    (SliceRecord(0, 1, 1, 0),), (SliceRecord(32, 1),)):
            with self.assertRaises(ValueError): facts(graph, SliceGraph("bad", 32, bad))

    def test_no_search_coverage_or_vertex_mismatch_is_not_admitted(self):
        graph = SliceGraph("g", 32, (SliceRecord(0, 1),))
        for batch in (SliceGraph("u", 32, (SliceRecord(0, 2),)), SliceGraph("u", 31, ())):
            with self.assertRaises(ValueError): facts(graph, batch)

    def test_complete_analysis_does_not_admit_hardware_or_publication(self):
        result = analyze(observations(self.declared), self.declared)
        self.assertEqual(result["prediction_rows"], 36)
        self.assertEqual(len(result["comparisons"]), 12)
        self.assertTrue(result["four_bank_ten_percent_target_met"])
        self.assertFalse(result["production_baseline_admitted"])
        self.assertFalse(result["publication_match_admitted"])
        self.assertFalse(result["hardware_timing_admitted"])
        self.assertFalse(result["host_inclusive_timing_admitted"])

    def test_incomplete_or_altered_matrix_and_state_are_rejected(self):
        rows = observations(self.declared)
        for candidate in (rows[:-1], rows + rows[:1]):
            with self.assertRaises(ValueError): analyze(candidate, self.declared)
        altered = deepcopy(self.declared)
        altered["matrix"] = altered["matrix"][:-1]
        with self.assertRaises(ValueError): analyze(rows, altered)
        rows[0]["state_sha256"] = "b" * 64
        with self.assertRaises(ValueError): analyze(rows, self.declared)

    def test_omitted_cache_search_traffic_and_wrong_identity_are_rejected(self):
        for field, value in (("pma_read_bytes", 0), ("read_bytes", 0), ("binary_probes", 0),
                ("physical_updates", 1), ("ddr_updates", 1), ("full_payload_pass", False),
                ("cycles", 0), ("arm", "candidate-runtime-23"), ("timing_kind", "measured")):
            rows = observations(self.declared)
            rows[0]["observation"][field] = value
            with self.assertRaises(ValueError): analyze(rows, self.declared)

    def test_timing_failure_remains_a_finding_not_a_dropped_row(self):
        rows = observations(self.declared)
        rows[1]["observation"]["cycles"] = 200
        result = analyze(rows, self.declared)
        self.assertFalse(result["four_bank_ten_percent_target_met"])
        self.assertTrue(result["full_payload_and_traffic_pass"])
        self.assertEqual(result["prediction_rows"], 36)


class RealGDeliveryTests(unittest.TestCase):
    def test_capsules_recompute_and_retain_all_raw_logs_and_frozen_inputs(self):
        for name in ("evidence", "regression"):
            folder = PARENT / "real_inputs" / name
            index = json.loads((folder / "index.json").read_text())
            report = json.loads((folder / "matrix.json").read_text())
            checked = (analyze(report["rows"], report["contract"]) if name == "evidence"
                       else analyze_synthetic(report["rows"]))
            for key, value in checked.items():
                self.assertEqual(index[key], value)
                self.assertEqual(report[key], value)
            self.assertFalse(index["new_spine_comparison_executed"])
            self.assertEqual(report["errors"], [])
            for entry in index["reports"]:
                path = folder / entry["file"]
                self.assertEqual(sha256_file(path), entry["sha256"])
                self.assertEqual(path.stat().st_size, entry["bytes"])
            with tarfile.open(folder / "raw_runs.tar.gz") as archive:
                self.assertEqual(sorted(archive.getnames()), sorted(r["member"] for r in index["raw_members"]))
                for entry in index["raw_members"]:
                    payload = archive.extractfile(entry["member"]).read()
                    self.assertEqual(len(payload), entry["bytes"])
                    self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["sha256"])
                self.assertEqual(json.loads(archive.extractfile("input_contract.json").read()), report["contract"])
                for entry in report["input_pins"]:
                    self.assertEqual(hashlib.sha256(archive.extractfile(entry["member"]).read()).hexdigest(), entry["sha256"])
                for row in report["rows"]:
                    label = f"lat{row['latency']}_{row['case']}_{row['arm']}"
                    tag, _, body = archive.extractfile("raw/" + label + ".stdout.txt").read().decode().strip().partition(" ")
                    self.assertEqual(tag, "REAL_G_RESULT" if name == "evidence" else "SHARDED_G_RESULT")
                    self.assertEqual(json.loads(body), row["observation"])
                for step in report["steps"]:
                    self.assertEqual(step["exit_code"], 0)
                    self.assertFalse(step["timed_out"])
                    self.assertEqual(step["memory_limit_gib"], 2)
                    self.assertGreaterEqual(step["reserve_gib"], 8)
                    resource_name = Path(step["stdout"]).name.replace(".stdout.txt", ".resources.json")
                    self.assertEqual(json.loads(archive.extractfile("raw/" + resource_name).read()), step)

    def test_generalized_execution_reproduces_all_old_observations_and_state_hashes(self):
        original = json.loads((PARENT / "evidence/matrix.json").read_text())
        replay = json.loads((PARENT / "real_inputs/regression/matrix.json").read_text())
        def values(report):
            return {(r["case"], r["latency"], r["arm"]): (r["observation"], r["state_sha256"])
                    for r in report["rows"]}
        self.assertEqual(values(original), values(replay))
        self.assertEqual(len(replay["rows"]), 24)


if __name__ == "__main__":
    unittest.main()
