"""Exact affected-fraction labels, not initial-frontier counts."""

import math
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.affected_fraction.sssp import Graph, distances, relax
from spine_cycle_sim.experiments.evaluation_impact.affected_fraction import cc
from spine_cycle_sim.experiments.evaluation_impact.affected_fraction.pagerank import fan_in_batches
from spine_cycle_sim.experiments.evaluation_impact.affected_fraction.analyze import crossings, export
from spine_cycle_sim.experiments.evaluation_impact.affected_fraction.select import select
from spine_cycle_sim.experiments.evaluation_impact.affected_fraction.input_archive import update_text
from spine_cycle_sim.experiments.evaluation_impact.affected_fraction.delivery import completion, deliver


class SsspReferenceTest(unittest.TestCase):
    def test_propagation_and_disconnected_vertices(self):
        graph = Graph(5, [(0, 1, 10), (1, 2, 2), (2, 3, 2)],
                      [[(1, 10)], [(2, 2)], [(3, 2)], [], []])
        old = distances(graph, 0)
        final = distances(graph, 0, [(0, 1, 1), (0, 4, 3)])
        self.assertEqual(old, [0, 10, 12, 14, math.inf])
        self.assertEqual(final, [0, 1, 3, 5, 3])
        incremental = old.copy()
        self.assertEqual(relax(graph.adjacency, incremental, [(1, 1), (4, 3)]), {1, 2, 3, 4})
        self.assertEqual(incremental, final)

    def test_no_change_is_not_counted(self):
        graph = Graph(3, [(0, 1, 1)], [[(1, 1)], [], []])
        old = distances(graph, 0)
        self.assertEqual(relax(graph.adjacency, old, [(1, 4)]), set())

    def test_rejected_candidate_restores_every_distance(self):
        adjacency = [[(1, 1)], [(2, 1)], [(3, 1)], []]
        state = [10, 11, 12, 13]
        self.assertIsNone(relax(adjacency, state, [(0, 0)], max_changes=2))
        self.assertEqual(state, [10, 11, 12, 13])


class CcReferenceTest(unittest.TestCase):
    def test_canonical_labels_count_relabelled_not_just_endpoint_vertices(self):
        graph = Graph(5, [(1, 2, 1), (2, 3, 1)], [])
        self.assertEqual(cc.labels(graph), [0, 1, 1, 1, 4])
        self.assertEqual(cc.labels(graph, [(0, 3, 1), (3, 0, 1)]), [0, 0, 0, 0, 4])


class PageRankBatchTest(unittest.TestCase):
    def test_fan_in_has_disjoint_triples_and_no_existing_edges(self):
        graph = Graph(48, [(src, src, 1) for src in range(48)],
                      [[(src, 1)] for src in range(48)])
        rows = list(fan_in_batches(graph, (2, 4, 8), 10))
        batch = rows[-1][1]
        self.assertEqual(len(batch), 8)
        self.assertEqual(len(set((src, dst) for src, dst, _ in batch)), 8)
        self.assertTrue(all(src != dst for src, dst, _ in batch))
        for index in range(0, len(batch), 2):
            self.assertEqual(batch[index][1], batch[index + 1][1])
        self.assertEqual(rows[0][1], batch[:2])

    def test_selection_uses_cpu_impact_and_keeps_zero_and_ordinary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            rows = [dict(name=name, kind=kind, changed_fraction=fraction) for name, kind, fraction in (
                ("zero", "target-candidate", 0), ("small", "target-candidate", 1e-5),
                ("large", "target-candidate", .1), ("ordinary-8", "ordinary", .001))]
            path.write_text(json.dumps(dict(algorithm="residual_pagerank", vertices=100,
                                           edges=100, original={}, epsilon=1e-6, points=rows)))
            result = select([path], Path(directory) / "output.json")
            self.assertEqual({row["name"] for row in result["points"]}, {row["name"] for row in rows})
            self.assertFalse(result["selection"]["uses_hardware_timings"])


@unittest.skipUnless(shutil.which("g++"), "g++ unavailable")
class PageRankOracleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)
        cls.binary = cls.root / "oracle"
        source = Path(__file__).resolve().parents[1] / "spine_cycle_sim/experiments/evaluation_impact/affected_fraction/pagerank_reference.cpp"
        subprocess.run(["g++", "-std=c++17", "-O2", "-ffp-contract=off", str(source), "-o", str(cls.binary)],
                       check=True, capture_output=True, timeout=60)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_two_sources_really_change_final_rank(self):
        graph = Graph(4, [(src, src, 1) for src in range(4)], [])
        path = self.root / "graph"
        graph.write(path, [(0, 2, 1), (1, 2, 1)])
        result = subprocess.run([str(self.binary), str(path), "0.000001"],
                                capture_output=True, text=True, check=True, timeout=10)
        stats = json.loads(result.stdout)
        self.assertTrue(stats["converged"])
        self.assertEqual(stats["changed_vertices"], 3)
        self.assertEqual(stats["initial_active"], 3)
        self.assertGreater(stats["rounds"], 1)
        suppressed = subprocess.run([str(self.binary), str(path), "1"],
                                    capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(json.loads(suppressed.stdout)["changed_vertices"], 0)


class AnalysisTest(unittest.TestCase):
    def test_delivery_requires_every_planned_point(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "workloads.json"
            manifest.write_text(json.dumps(dict(algorithm="weighted_sssp", dataset="fixture",
                                                points=[dict(name="first"), dict(name="second")])))
            campaign = root / "campaign.json"
            document = dict(status="COMPLETED", workloads=dict(path=str(manifest)),
                            cases=[dict(name="first", status="MEASURED")])
            campaign.write_text(json.dumps(document))
            result = completion([campaign])
            self.assertEqual(result["status"], "PARTIAL_RETAINED")
            self.assertEqual(result["studies"][0]["missing_points"], ["second"])
            document["cases"].append(dict(name="second", status="MEASURED"))
            campaign.write_text(json.dumps(document))
            self.assertEqual(completion([campaign])["status"], "COMPLETED")

    def test_delivery_timeout_does_not_export_a_mutating_campaign(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "workloads.json"
            manifest.write_text(json.dumps(dict(algorithm="weighted_sssp", dataset="fixture",
                                                points=[dict(name="first")])))
            campaign = root / "campaign.json"
            campaign.write_text(json.dumps(dict(status="RUNNING", workloads=dict(path=str(manifest)), cases=[])))
            output = root / "delivery"
            result = deliver([campaign], [], output, hardware=root / "unused", wait_seconds=0)
            self.assertEqual(result["status"], "WAIT_TIMEOUT")
            self.assertFalse((output / "data").exists())

    def test_export_keeps_failed_logs_and_warmups_without_inventing_work(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph = root / "graph"
            Graph(3, [(0, 1, 2)], []).write(graph, [(0, 2, 1)])
            point = dict(name="target", kind="target", status="FAILED_RETAINED",
                         graph={"path": str(graph)}, updates=1, changed_vertices=1,
                         changed_fraction=1 / 3, samples=[])
            folder = root / "target/sample-0"
            folder.mkdir(parents=True)
            (folder / "spine.stderr.txt").write_text("retained device error\n")
            sample = dict(sample_index=0, warmup=True, order=["spine", "gr"],
                          status="FAILED_RETAINED", arms={}, error="device error")
            point["samples"].append(sample)
            manifest = dict(algorithm="weighted_sssp", dataset="fixture", vertices=3,
                            edges=1, points=[point])
            manifest_path = root / "workloads.json"
            manifest_path.write_text(json.dumps(manifest))
            campaign_path = root / "campaign.json"
            campaign_path.write_text(json.dumps(dict(status="FAILED_RETAINED", cases=[point],
                                                       workloads={"path": str(manifest_path)})))
            output = root / "export"
            result = export([campaign_path], output)
            self.assertEqual(result["measured_points"], 0)
            self.assertEqual(result["total_samples"], 1)
            self.assertNotIn(b"\r", (output / "points.csv").read_bytes())
            self.assertNotIn(b"\r", (output / "samples.csv").read_bytes())
            with tarfile.open(output / "host-logs.tar.gz") as archive:
                self.assertEqual(archive.getnames(), ["campaign-0/target/sample-0/spine.stderr.txt"])
            with tarfile.open(output / "updates.tar.gz") as archive:
                self.assertEqual(archive.extractfile("campaign-0/target.updates.txt").read(), b"0 2 1 1\n")

    def test_exported_updates_preserve_the_exact_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            graph = Graph(3, [(0, 1, 2), (1, 2, 3)], [])
            path = Path(directory) / "graph"
            graph.write(path, [(0, 2, 1)])
            self.assertEqual(update_text(path, 3, 2, 1), b"0 2 1 1\n")
            with self.assertRaises(ValueError):
                update_text(path, 3, 2, 2)

    def test_crossing_does_not_use_failed_or_ordinary_points(self):
        rows = [dict(name="left", status="MEASURED", kind="target", changed_fraction=.001, speedup=2),
                dict(name="failed", status="FAILED_RETAINED", kind="target", changed_fraction=.002, speedup=.1),
                dict(name="ordinary", status="MEASURED", kind="ordinary", changed_fraction=.003, speedup=.2),
                dict(name="right", status="MEASURED", kind="target", changed_fraction=.01, speedup=.5)]
        result = crossings(rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["changed_fraction_bounds"], [.001, .01])


if __name__ == "__main__":
    unittest.main()
