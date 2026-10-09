from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_inputs.analysis import analyze_layout
from spine_cycle_sim.experiments.original_regraph_inputs.delivery import deliver
from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_inputs.preparation import compiler_command, inspect_graph, write_fixture
from spine_cycle_sim.experiments.original_regraph_inputs.study import source_identities

ROOT = Path(__file__).resolve().parents[1]


class OriginalInputPreparationTests(unittest.TestCase):
    def test_fixture_counts_and_file_identity_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name, vertices, edges in (("boundary_ring", 131073, 131137), ("skewed_sources", 65537, 8193)):
                path = Path(temporary) / name
                write_fixture(name, path)
                first = inspect_graph(path)
                self.assertEqual((first["vertices"], first["logical_edges"]), (vertices, edges))
                other = path.with_suffix(".repeat")
                write_fixture(name, other)
                self.assertEqual(first["sha256"], inspect_graph(other)["sha256"])
                with self.assertRaises(FileExistsError):
                    write_fixture(name, path)

    def test_unsafe_loader_inputs_are_rejected_before_author_code(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "graph.edges"
            for text in ("", "# comment\n", "\n", "-1 0\n", "0 1 2\n", "0 2147483647\n", "0 16711680\n"):
                path.write_text(text)
                with self.subTest(text=text), self.assertRaises(ValueError):
                    inspect_graph(path)
            path = Path(temporary) / "ungraph.edges"
            path.write_text("0 1\n")
            with self.assertRaises(ValueError):
                inspect_graph(path)

    def test_build_uses_real_OpenCL_headers_original_functions_and_no_fake_device(self):
        command = compiler_command(ROOT, Path("prepared"), {"little": 4, "big": 0}, Path("out"), "g++", Path("xrt"))
        self.assertIn("-DBIG_KERNEL_NUM=0", command)
        self.assertIn("-Iprepared/host/preprocess", command)
        self.assertIn("-lOpenCL", command)
        self.assertNotIn("-DSW_EMU", command)
        self.assertIn(str(ROOT / "cpp/tests/publication_sources/regraph_layout_probe.cpp"), command)

    def test_identity_includes_probe_validation_and_input_runner(self):
        paths = {item["path"] for item in source_identities(ROOT)}
        for name in ("cpp/tests/publication_sources/regraph_layout_validation.hpp",
                     "scripts/run_original_regraph_inputs.py", "tests/test_original_regraph_inputs.py"):
            self.assertIn(name, paths)


class OriginalLayoutAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / "configs/experiments/original_regraph_inputs_v1.json").read_text())
        self.topology = self.contract["topologies"][0]
        self.graph = {"vertices": 65537, "logical_edges": 2}
        self.summary = {"kind": "original_regraph_host_layout", "passed": True, **self.graph,
            "little": 4, "big": 0, "seed": 73, "partitions": 2, "dense_partitions": 2, "sparse_groups": 0,
            "aligned_vertices": 131072, "task_physical_edges": 64, "task_dummy_edges": 62,
            "source_allocation_rejections": 0, "initial_arithmetic_rejections": 0, "max_initial_sum": 10,
            "edge_bytes_max_channel": 128}
        self.partitions = [{"id": index, "offset_words": index * 16, "words": 16,
                            "dst_offset": index * 65536, "dst_len": 65536} for index in range(2)]
        self.tasks = [{"kind": "dense", "partition": part, "subpartition": sub,
                       "kernel": sub if part == 0 else 3 - sub, "offset_words": (part * 4 + sub) * 16,
                       "words": 16, "dst_offset": part * 65536, "dst_len": 65536}
                      for part in range(2) for sub in range(4)]
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        counts = [65537, 65538, 2, 131072, 131072, 32, 128]
        for name, count in zip(self.contract["capture_files"], counts, strict=True):
            (self.directory / name).write_bytes(bytes(count * 4))

    def stdout(self):
        return "\n".join(["PUBLICATION_LAYOUT " + json.dumps(self.summary),
            *["ORIGINAL_LAYOUT_PARTITION " + json.dumps(row) for row in self.partitions],
            *["ORIGINAL_LAYOUT_TASK " + json.dumps(row) for row in self.tasks]])

    def analyze(self):
        return analyze_layout(self.stdout(), self.directory, self.topology, self.graph, self.contract)

    def test_layout_admission_does_not_invent_device_timing(self):
        result = self.analyze()
        self.assertIsNone(result["device_cycles"])
        self.assertIsNone(result["publication_rate_error_pct"])
        self.assertEqual(len(result["files"]), 7)

    def test_work_types_seed_allocation_and_arithmetic_guards_are_required(self):
        original = copy.deepcopy(self.summary)
        for key, value in (("passed", 1), ("logical_edges", 2.0), ("seed", 74), ("task_dummy_edges", 0),
                           ("source_allocation_rejections", 1), ("initial_arithmetic_rejections", 1)):
            self.summary = copy.deepcopy(original)
            self.summary[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.analyze()

    def test_missing_duplicate_or_wrong_task_kernel_and_offset_rejected(self):
        original = copy.deepcopy(self.tasks)
        for rows in (original[:-1], original + original[:1], list(reversed(original))):
            self.tasks = rows
            with self.assertRaises(ValueError):
                self.analyze()
        for key, value in (("kernel", 0), ("offset_words", 0), ("dst_offset", 0), ("words", 15)):
            self.tasks = copy.deepcopy(original)
            self.tasks[-1][key] = value
            if self.tasks[-1] == original[-1]:
                self.tasks[-1][key] = 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.analyze()

    def test_capture_truncation_and_changed_values_are_detectable(self):
        before = self.analyze()
        path = self.directory / "csr_destinations.u32le"
        path.write_bytes(b"changed!")
        self.assertNotEqual(before["files"], self.analyze()["files"])
        path.write_bytes(b"short")
        with self.assertRaises(ValueError):
            self.analyze()


class OriginalLayoutDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name) / "run"
        self.run.mkdir()
        self.destination = Path(self.temporary.name) / "delivery"
        self.contract = json.loads((ROOT / "configs/experiments/original_regraph_inputs_v1.json").read_text())
        (self.run / "contract.json").write_text(json.dumps(self.contract))
        self.report = {"status": "ORIGINAL_HOST_LAYOUT_PASS_NOT_DEVICE_TIMING",
            "ubsan_identical_no_diagnostics": True, "source_identities": [],
            "contract_sha256": sha256_file(self.run / "contract.json"),
            "cases": [{"id": f"{top['id']}_{graph['id']}"}
                      for top in self.contract["topologies"] for graph in self.contract["inputs"]],
            "topologies": copy.deepcopy(self.contract["topologies"]),
            "inputs": copy.deepcopy(self.contract["inputs"]), "steps": [],
            "instrumented_binaries": [{"topology_id": top["id"]} for top in self.contract["topologies"]]}

    def reject(self, message):
        (self.run / "report.json").write_text(json.dumps(self.report))
        with patch("spine_cycle_sim.experiments.original_regraph_inputs.delivery.source_identities", return_value=[]):
            with self.assertRaisesRegex(ValueError, message):
                deliver(ROOT, self.run, self.destination, [])
        self.assertFalse(self.destination.exists())

    def test_missing_or_reordered_topology_cannot_skip_raw_validation(self):
        original = copy.deepcopy(self.report["topologies"])
        for topologies in ([], original[:-1], list(reversed(original))):
            self.report["topologies"] = topologies
            self.reject("topology or graph")

    def test_undeclared_or_changed_graph_and_topology_are_rejected(self):
        self.report["inputs"][-1]["sha256"] = "changed"
        self.reject("graph differs")
        self.report["inputs"] = copy.deepcopy(self.contract["inputs"])
        self.report["topologies"][0]["little"] = 11
        self.reject("topology differs")

    def test_missing_instrumentation_and_duplicate_steps_are_rejected(self):
        self.report["instrumented_binaries"] = []
        self.reject("instrumented original-host matrix missing")
        self.report["steps"] = [{"id": "duplicate"}, {"id": "duplicate"}]
        self.reject("duplicate execution steps")

    def test_contract_and_instrumentation_status_cannot_be_relaxed(self):
        self.report["ubsan_identical_no_diagnostics"] = False
        self.reject("incomplete or changed")
        self.contract["seed"] = 74
        (self.run / "contract.json").write_text(json.dumps(self.contract))
        self.report["contract_sha256"] = sha256_file(self.run / "contract.json")
        self.reject("canonical contract")


if __name__ == "__main__":
    unittest.main()
