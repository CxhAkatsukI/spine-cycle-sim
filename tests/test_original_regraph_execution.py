from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.analysis import analyze, analyze_matrix
from spine_cycle_sim.experiments.original_regraph_execution.preparation import verify_checkpoint, verify_inputs
from spine_cycle_sim.experiments.original_regraph_execution.study import source_identities
from spine_cycle_sim.experiments.original_regraph_execution.resource_evidence import instantiated_parameters
from spine_cycle_sim.experiments.original_regraph_execution.delivery import deliver
from spine_cycle_sim.experiments.campaign_runtime import sha256_file

ROOT = Path(__file__).resolve().parents[1]


class WholeA4AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.contract = json.loads((ROOT / "configs/experiments/original_regraph_a4_execution_v1.json").read_text())
        self.case = self.contract["cases"][0]
        summary = {"vertices": 65537, "aligned_vertices": 131072, "logical_edges": 2, "partitions": 1,
                   "task_physical_edges": 64, "task_dummy_edges": 62}
        self.input = {"layout": {"summary": summary}}
        self.row = {"kind": "original_a4_graph_iteration", "passed": True, "queues_and_requests_conserved": True,
            "iterations": 1, "little": 4, "big": 0, "argument": 0, "clock_mhz": 210,
            "state_parent_credits": 16, "memory_latency": 64, "outstanding_bursts": 16,
            "vertices": 65537, "aligned_vertices": 131072, "logical_edges": 2, "partitions": 1,
            "physical_edges": 64, "dummy_edges": 62, "published_vertices": 65536,
            "checked_sum_words": 65536, "checked_replica_words": 524288, "edge_read_bytes": 512,
            "source_read_bytes": 32768, "degree_read_bytes": 262144, "property_write_bytes": 1048576,
            "read_bytes": 295424, "write_bytes": 1048576, "cycles": 1000,
            "degree_peak_outstanding": 9, "writer_peak_outstanding": 9,
            "degree_request_stalls": 0, "contended_channel_cycles": 0, "overlapped_task_starts": 0,
            "paths": [{"kernel": index, "starts": [0], "completions": [900]} for index in range(4)]}
        for index in range(4):
            (self.directory / f"final_replica{index}.u32le").write_bytes(bytes(131072 * 4))

    def analyze(self):
        return analyze("A4_EXECUTION " + json.dumps(self.row), self.directory, self.case, self.input, self.contract)

    def test_complete_graph_admission_does_not_claim_FPGA_or_publication_match(self):
        result = self.analyze()
        self.assertIsNone(result["FPGA_measured_cycles"])
        self.assertIsNone(result["publication_rate_error_pct"])
        self.assertEqual(len(result["files"]), 4)

    def test_wrong_work_or_missing_conservation_and_pre_apply_scope_rejected(self):
        original = copy.deepcopy(self.row)
        for key, value in (("passed", 1), ("queues_and_requests_conserved", False), ("checked_sum_words", 1),
                           ("logical_edges", 2.0), ("argument", 3), ("degree_read_bytes", 1)):
            self.row = copy.deepcopy(original)
            self.row[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.analyze()

    def test_memory_ledger_extent_and_concurrency_limits_required(self):
        original = copy.deepcopy(self.row)
        for key, value in (("cycles", 0), ("cycles", 20000001), ("read_bytes", 1), ("write_bytes", 1),
                           ("source_read_bytes", 1), ("degree_peak_outstanding", 17), ("writer_peak_outstanding", 17)):
            self.row = copy.deepcopy(original)
            self.row[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.analyze()

    def test_missing_path_or_bad_partition_lifecycle_rejected(self):
        original = copy.deepcopy(self.row)
        for paths in (original["paths"][:-1], list(reversed(original["paths"])),
                      [{"kernel": index, "starts": [0], "completions": [1001]} for index in range(4)]):
            self.row = copy.deepcopy(original)
            self.row["paths"] = paths
            with self.assertRaises(ValueError):
                self.analyze()

    def test_missing_timing_and_untyped_path_metadata_are_rejected(self):
        original = copy.deepcopy(self.row)
        for name in ("cycles", "paths", "read_bytes"):
            self.row = copy.deepcopy(original)
            del self.row[name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.analyze()
        self.row = copy.deepcopy(original)
        self.row["paths"][-1]["starts"] = "0"
        with self.assertRaises(ValueError):
            self.analyze()

    def test_changed_replica_or_truncated_capture_rejected(self):
        path = self.directory / "final_replica3.u32le"
        with path.open("r+b") as stream:
            stream.write(b"wrong")
        with self.assertRaisesRegex(ValueError, "replicas disagree"):
            self.analyze()
        path.write_bytes(b"short")
        with self.assertRaisesRegex(ValueError, "extent"):
            self.analyze()

    def test_matrix_requires_repeatable_reverse_pressure_and_partition_overlap(self):
        reference = self.analyze()
        reference["result"]["overlapped_task_starts"] = 8
        rows = [{"id": case["id"], "runs": [{"analysis": copy.deepcopy(reference)}]} for case in self.contract["cases"]]
        for row in rows:
            if row["id"] in ("boundary_two_parents", "boundary_latency128"):
                row["runs"][0]["analysis"]["result"]["cycles"] = 2000
        self.assertTrue(analyze_matrix(rows)["independent_partition_progress_observed"])
        rows[-1]["runs"][0]["analysis"]["result"]["cycles"] = 999
        with self.assertRaisesRegex(ValueError, "registration order"):
            analyze_matrix(rows)


class WholeA4InputTests(unittest.TestCase):
    def test_reproduced_input_report_can_move_without_weakening_source_or_matrix_identity(self):
        frozen = {"source_identities": [{"path": "fixed", "sha256": "pin"}], "source_snapshot": {"revision": "pin"},
                  "cases": [{"id": "a4_fixture"}], "inputs": [{"id": "fixture"}]}
        report = {**copy.deepcopy(frozen), "status": "ORIGINAL_HOST_LAYOUT_PASS_NOT_DEVICE_TIMING",
                  "ubsan_identical_no_diagnostics": True, "different_location": "/new/path"}
        verify_checkpoint(report, {"seed": 73}, frozen, {"seed": 73}, frozen["source_identities"])
        report["source_snapshot"]["revision"] = "changed"
        with self.assertRaisesRegex(ValueError, "fixed passing"):
            verify_checkpoint(report, {"seed": 73}, frozen, {"seed": 73}, frozen["source_identities"])

    def test_instantiated_AXI_settings_override_unrelated_generic_defaults(self):
        text = "parameter C_M_AXI_DATA_WIDTH = 32; parameter C_M_AXI_GMEM0_DATA_WIDTH = 512; "
        text += ".C_M_AXI_DATA_WIDTH(C_M_AXI_GMEM0_DATA_WIDTH), .NUM_READ_OUTSTANDING(16)"
        parameters = instantiated_parameters(text)
        self.assertEqual(parameters["C_M_AXI_DATA_WIDTH"], [512])
        self.assertEqual(parameters["NUM_READ_OUTSTANDING"], [16])
        with self.assertRaisesRegex(ValueError, "unresolved"):
            instantiated_parameters(".C_M_AXI_DATA_WIDTH(unknown)")

    def test_changed_descriptor_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / "execution.u32le").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "descriptor changed"):
                verify_inputs([{"directory": temporary, "descriptor_sha256": "pinned", "files": []}])

    def test_model_identity_covers_core_and_owning_experiment(self):
        paths = {item["path"] for item in source_identities(ROOT)}
        for name in ("cpp/src/axi.cpp", "cpp/src/original_regraph/pr_apply.cpp",
                     "cpp/tests/original_regraph/memory_fixture.hpp",
                     "cpp/tests/original_regraph/whole_graph/a4_execution.cpp",
                     "cpp/tests/original_regraph/whole_graph/input.hpp",
                     "scripts/run_original_regraph_a4.py", "tests/test_original_regraph_execution.py"):
            self.assertIn(name, paths)


class WholeA4DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name) / "run"
        self.run.mkdir()
        self.destination = Path(self.temporary.name) / "delivery"
        self.contract = json.loads((ROOT / "configs/experiments/original_regraph_a4_execution_v1.json").read_text())
        (self.run / "contract.json").write_text(json.dumps(self.contract))
        self.report = {"status": "A4_FULL_GRAPH_FUNCTIONAL_PASS_TIMING_PREDICTED", "source_identities": [],
            "contract_sha256": sha256_file(self.run / "contract.json"), "ubsan_identical_no_diagnostics": True,
            "legacy_regression": {"default_component_and_full_source_comparison_outputs_identical": True},
            "negative_controls": [{"id": name, "expected_rejection": True} for name in
                ("header", "assignment", "source", "arithmetic", "edge_value", "truncated")],
            "cases": [{"id": item["id"]} for item in self.contract["cases"]],
            "inputs": [{"id": name} for name in ("boundary_ring", "skewed_sources", "amazon")], "binaries": [{}, {}]}

    def reject(self, message):
        (self.run / "report.json").write_text(json.dumps(self.report))
        with patch("spine_cycle_sim.experiments.original_regraph_execution.delivery.source_identities", return_value=[]):
            with self.assertRaisesRegex(ValueError, message):
                deliver(ROOT, self.run, self.destination, [])
        self.assertFalse(self.destination.exists())

    def test_missing_case_input_or_instrumented_binary_rejected(self):
        original = copy.deepcopy(self.report)
        for name in ("cases", "inputs", "binaries"):
            self.report = copy.deepcopy(original)
            self.report[name].pop()
            self.reject("missing declared")

    def test_missing_rejection_regression_or_ubsan_cannot_be_delivered(self):
        original = copy.deepcopy(self.report)
        for name in ("ubsan_identical_no_diagnostics", "negative_controls", "legacy_regression"):
            self.report = copy.deepcopy(original)
            if name == "negative_controls":
                self.report[name].pop()
            elif name == "legacy_regression":
                self.report[name]["default_component_and_full_source_comparison_outputs_identical"] = False
            else:
                self.report[name] = False
            self.reject("complete unchanged")

    def test_relaxed_contract_cannot_be_delivered(self):
        self.contract["max_cycles"] *= 2
        (self.run / "contract.json").write_text(json.dumps(self.contract))
        self.report["contract_sha256"] = sha256_file(self.run / "contract.json")
        self.reject("complete unchanged")


if __name__ == "__main__":
    unittest.main()
