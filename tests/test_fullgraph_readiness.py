import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import analysis, preparation


def prepared_log(row):
    prefix = preparation.PREFIXES[row["algorithm"]]
    partitions = (row["vertices"] + 65535) // 65536
    initial = (f"{prefix}_INPUT vertices={row['vertices']} static_edges={row['initial_edges']} "
               f"logical_updates={row['updates']} physical_updates={row['updates']} "
               f"destination_partitions={partitions} pma_slots_total=256 oracle_converged=1 "
               f"resident_state=old_graph_converged source_external={row['source']}")
    layout = (f"GRASU_SHARDED_UPDATE_LAYOUT shard=0 destination_base=0 destination_vertices=65536 "
              f"updates={row['updates']} cache_updates={row['updates']} ddr_updates=0")
    final = (f"{prefix}_PREP status=PASS vertices={row['vertices']} destination_partitions={partitions} "
             "pma_slots_total=256 pma_slots_max_shard=256 pma_destination_abi=local_dst19 "
             "k4_frontends=4 shared_regraph_downstream=1 conversion_cost=absent "
             "oracle_converged=1 hbm_graph_channels=23 hbm_max_channel_bytes=64")
    return "\n".join((initial, layout, final)) + "\n"


class PreparationTests(unittest.TestCase):
    def fixture(self, root):
        rows = []
        for dataset in preparation.DATASETS:
            for algorithm in preparation.ALGORITHMS:
                updates = 16 if algorithm == "connected_components" else 8
                graph = root / (dataset + "_" + algorithm + ".graph")
                graph.write_text(f"65537 1 {updates}\n0 1 1\n" + "1 2 1 1\n" * updates)
                rows.append({"dataset": dataset, "algorithm": algorithm, "vertices": 65537,
                             "initial_edges": 1, "updates": updates, "source": 0,
                             "graph": str(graph), "sha256": preparation.identity(graph)["sha256"]})
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({"status": "pass", "batch_size": 8, "records": rows}))
        return manifest, rows

    def test_exact_matrix_order_and_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, rows = self.fixture(Path(directory))
            result = preparation.matrix(manifest)
            self.assertEqual([(r["dataset"], r["algorithm"]) for r in result],
                             [(r["dataset"], r["algorithm"]) for r in rows])
            preparation.unchanged([r["input_identity"] for r in result], full=True)

    def test_missing_duplicate_batch_source_capacity_hash_and_header_rejected(self):
        for mutation in ("missing", "duplicate", "batch", "source", "capacity", "hash", "header"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                manifest, _ = self.fixture(Path(directory))
                contents = json.loads(manifest.read_text())
                row = contents["records"][0]
                if mutation == "missing":
                    contents["records"].pop()
                elif mutation == "duplicate":
                    contents["records"][-1] = copy.deepcopy(row)
                elif mutation == "batch":
                    contents["batch_size"] = 16
                elif mutation == "source":
                    row["source"] = row["vertices"]
                elif mutation == "capacity":
                    row["vertices"] = 255 * 65536 + 1
                elif mutation == "hash":
                    row["sha256"] = "0" * 64
                else:
                    graph = Path(row["graph"])
                    graph.write_text(graph.read_text().replace("65537 1 8", "65537 2 8"))
                    row["sha256"] = preparation.identity(graph)["sha256"]
                manifest.write_text(json.dumps(contents))
                with self.assertRaises(ValueError):
                    preparation.matrix(manifest)

    def test_fast_drift_check_rejects_same_size_restored_mtime_and_symlink_retarget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.write_text("abc")
            pin = preparation.identity(source)
            source.write_text("xyz")
            os.utime(source, ns=(source.stat().st_atime_ns, pin["stat"]["st_mtime_ns"]))
            with self.assertRaises(ValueError):
                preparation.unchanged([pin])
            alias = root / "alias"
            alias.symlink_to(source)
            pin = preparation.identity(alias)
            replacement = root / "replacement"
            replacement.write_text("xyz")
            alias.unlink()
            alias.symlink_to(replacement)
            with self.assertRaises(ValueError):
                preparation.unchanged([pin])

    def test_commands_use_full_cache_row_line_and_prepare_only_without_xclbin(self):
        for algorithm in preparation.ALGORITHMS:
            command = preparation.compile_command(Path("/compiler"), Path("/source"), algorithm,
                                                   Path("/output/host"), Path("/xrt"), Path("/hls"))
            self.assertIn("-DGRASU_MAX_CACHE_SEGMENT=131072", command)
            self.assertIn("-DGRASU_REGRAPH_HOST_ROW_LINE_READ=1", command)
            run = preparation.prepare_command(Path("/host"), {"algorithm": algorithm,
                "source": 7, "graph": "/graph"}, Path("/unused"))
            self.assertEqual(run[:4], ["/host", "--prepare-only", "/graph", "/unused"])
            self.assertEqual(run[4:], [] if algorithm == "residual_pagerank" else ["7", "256"])

    def test_smokes_cover_six_partitions_and_physical_cc_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = preparation.smokes(Path(directory))
            self.assertEqual(len(rows), 3)
            for row in rows:
                text = Path(row["graph"]).read_text().splitlines()
                self.assertEqual(list(map(int, text[0].split())),
                                 [row["vertices"], row["initial_edges"], row["updates"]])
                self.assertEqual(len(text) - 1, row["initial_edges"] + row["updates"])


class AnalysisTests(unittest.TestCase):
    row = {"dataset": "AU", "algorithm": "weighted_sssp", "vertices": 65537,
           "initial_edges": 1, "updates": 8, "source": 0}

    def test_all_algorithms_admit_only_cpu_layout_scope(self):
        for algorithm in preparation.ALGORITHMS:
            row = {**self.row, "algorithm": algorithm}
            result = analysis.analyze(row, prepared_log(row), "")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["claim"], "CPU_oracle_and_graph_HBM_layout_only_not_board_timing")

    def test_rejects_board_output_stderr_oracle_capacity_topology_and_lost_updates(self):
        good = prepared_log(self.row)
        for output, stderr in ((good, "warning"),
                (good.replace("oracle_converged=1", "oracle_converged=0"), ""),
                (good.replace("hbm_max_channel_bytes=64", "hbm_max_channel_bytes=536870913"), ""),
                (good.replace("k4_frontends=4", "k4_frontends=8"), ""),
                (good.replace("cache_updates=8", "cache_updates=7"), ""),
                (good.replace("shard=0", "shard=2"), ""),
                (good.replace("resident_state=old_graph_converged", "resident_state=cold_fallback"), ""),
                (good.replace("pma_slots_total=256", "pma_slots_total=128", 1), ""),
                (good.replace("\n", "\nBOARD_EXECUTED elapsed=1\n", 1), "")):
            with self.subTest(output=output, stderr=stderr), self.assertRaises(ValueError):
                analysis.analyze(self.row, output, stderr)

    def test_rejects_duplicate_fields_and_duplicate_shards(self):
        good = prepared_log(self.row)
        with self.assertRaises(ValueError):
            analysis.analyze(self.row, good.replace("status=PASS", "status=PASS status=PASS"), "")
        lines = good.splitlines()
        with self.assertRaises(ValueError):
            analysis.analyze(self.row, "\n".join([lines[0], lines[1], lines[1], lines[2]]), "")

    def test_decision_requires_exact_unique_24_case_coverage(self):
        cases = [{"dataset": d, "algorithm": a, "status": "PASS"}
                 for d in preparation.DATASETS for a in preparation.ALGORITHMS]
        self.assertEqual(analysis.decision(cases), analysis.PASS)
        self.assertEqual(analysis.decision([cases[0]] * 24), "FAILED_RETAINED")
        self.assertEqual(analysis.decision(cases[:-1]), "FAILED_RETAINED")
        cases[0]["status"] = "FAILED_RETAINED"
        self.assertEqual(analysis.decision(cases), "FAILED_RETAINED")
