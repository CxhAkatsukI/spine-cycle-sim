import copy
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.mixed.preparation import geometry
from spine_cycle_sim.experiments.original_regraph_execution.mixed.analysis import analyze, matrix, STATUS
from spine_cycle_sim.experiments.original_regraph_execution.mixed.regression import archived
from spine_cycle_sim.experiments.original_regraph_execution.mixed.delivery import should_archive


class MixedTests(unittest.TestCase):
    def test_original_host_capacity_audit(self):
        for aligned, dense, sparse, published, extra in ((196608, 1, 1, 589824, 393216),
                (131072, 1, 0, 65536, 0), (786432, 1, 2, 1114112, 327680)):
            shape = geometry({"aligned_vertices": aligned, "dense_partitions": dense, "sparse_groups": sparse})
            self.assertEqual(shape["published_vertices"], published)
            self.assertEqual(shape["extra_padding_vertices"], extra)
            self.assertEqual(shape["original_host_capacity_pass"], extra == 0)

    def fixture(self, directory):
        shape = geometry({"aligned_vertices": 131072, "dense_partitions": 1, "sparse_groups": 0})
        source = {"vertices": 65537, "logical_edges": 8193, "dense_partitions": 1, "sparse_groups": 0,
                  "task_physical_edges": 8208, "task_dummy_edges": 15}
        row = {"kind": "original_mixed_graph_iteration_padded_control", "passed": True, "queues_and_requests_conserved": True,
            **shape, "vertices": source["vertices"], "logical_edges": source["logical_edges"], "iterations": 1,
            "little": 11, "big": 3, "clock_mhz": 210, "argument": 0, "dense": 1, "sparse": 0,
            "state_parent_credits": 16, "memory_latency": 64, "physical_edges": 8208, "dummy_edges": 15,
            "checked_sum_words": 65536, "checked_replica_words": 131072 * 14, "edge_read_bytes": 8208 * 8,
            "degree_read_bytes": 65536 * 4, "write_bytes": 65536 * 4 * 14, "cycles": 100,
            "big_logical_requests": 0, "big_reads": 0, "big_cache_hits": 0, "big_source_bytes": 0,
            "little_source_bytes": 16384, "read_bytes": 8208 * 8 + 65536 * 4 + 16384,
            "big_before_little_finished": 0, "paths": [{"kernel": i, "starts": [0] if i < 11 else [],
                "completions": [90] if i < 11 else []} for i in range(14)]}
        for i in range(14): (directory / f"final_replica{i}.u32le").write_bytes(bytes(131072 * 4))
        admitted = {"geometry": shape, "layout": {"summary": source}}
        return row, {"state_parents": 16, "latency": 64}, admitted, {"max_cycles": 1000}

    def test_full_scope_and_counter_rejections(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name); row, case, admitted, contract = self.fixture(directory)
            def check(value): return analyze("MIXED_EXECUTION " + json.dumps(value), directory, case, admitted, contract)
            self.assertEqual(check(row)["status"], STATUS)
            for field, value in (("iterations", 2), ("cycles", 0), ("cycles", 1001), ("cycles", 3.5),
                    ("little", True), ("original_host_capacity_pass", 1), ("big_logical_requests", 1),
                    ("read_bytes", 0), ("little_source_bytes", 1), ("checked_sum_words", 16),
                    ("write_bytes", 0), ("queues_and_requests_conserved", False)):
                bad = copy.deepcopy(row); bad[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError): check(bad)

    def test_lifecycle_and_replica_rejections(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name); row, case, admitted, contract = self.fixture(directory)
            bad = copy.deepcopy(row); bad["paths"][0]["completions"] = [0]
            with self.assertRaises(ValueError): analyze("MIXED_EXECUTION " + json.dumps(bad), directory, case, admitted, contract)
            (directory / "final_replica13.u32le").write_bytes(bytes(4))
            with self.assertRaises(ValueError): analyze("MIXED_EXECUTION " + json.dumps(row), directory, case, admitted, contract)

    def test_archive_reference_and_tamper(self):
        with tempfile.TemporaryDirectory() as name:
            folder = Path(name); payload = b"indexed reference"; digest = hashlib.sha256(payload).hexdigest()
            source = folder / "source"; source.write_bytes(payload)
            archive = folder / "raw_big_gather.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle: bundle.add(source, arcname="ref")
            record = {"archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                      "files": [{"path": "ref", "bytes": len(payload), "sha256": digest}]}
            (folder / "big_gather_verification.json").write_text(json.dumps(record))
            self.assertEqual(archived(folder, "big_gather", digest), payload)
            with self.assertRaises(ValueError): archived(folder, "big_gather", "0" * 64)
            archive.write_bytes(b"damaged")
            with self.assertRaises(ValueError): archived(folder, "big_gather", digest)

    def test_fixed_matrix_and_boundary(self):
        root = Path(__file__).resolve().parents[1]
        contract = json.loads((root / "configs/experiments/original_regraph_mixed_execution_v1.json").read_text())
        self.assertEqual((contract["little"], contract["big"], contract["iterations"]), (11, 3, 1))
        self.assertEqual([row["id"] for row in contract["cases"]], ["boundary", "boundary_reverse", "boundary_latency128",
            "boundary_one_parent", "skewed", "skewed_reverse", "amazon", "amazon_reverse"])
        self.assertIn("FPGA_or_RTL_or_publication_timing_match", contract["not_claimed"])

    def test_raw_archive_keeps_rejection_logs(self):
        for name in ("negative_header.stdout.txt", "negative_capacity_amazon.stderr.txt", "negative_source.resources.json",
                     "build/compile_commands.json", "inputs/amazon/mixed.u32le", "amazon/first/analysis.json"):
            with self.subTest(name=name): self.assertTrue(should_archive(Path(name)))
        for name in ("negative_header/tasks.u32le", "negative_header/state/analysis.json", "legacy_a4/amazon/final_replica0.u32le",
                     "build/cpp/CMakeFiles/flags.make", "ubsan_mixed"):
            with self.subTest(name=name): self.assertFalse(should_archive(Path(name)))


if __name__ == "__main__": unittest.main()
