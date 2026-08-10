from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from scripts.convert_grasu_graph_to_slices import convert_graph
from scripts.run_sst_grasu_regraph_partitioned_dynamic_pagerank import load_slice


ROOT = Path(__file__).resolve().parents[1]
HARDWARE_ALIGNMENT_GRAPH = (
    ROOT / "tests" / "data" / "grasu_native_small_star_v4096_u1024.graph"
)
HARDWARE_ALIGNMENT_SHA256 = (
    "c5199f90e7dca0bd93da23570f6ab0e65af4e0710879e90deed3823701dd5248"
)


class ConvertGraSuGraphTests(unittest.TestCase):
    def test_preserves_header_split_and_update_operations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph = root / "case.graph"
            graph.write_text(
                "4 2 2\n0 1\n1 2\n0 1 0\n2 3 1\n", encoding="ascii"
            )
            initial = root / "initial.slice"
            update = root / "update.slice"
            metadata = convert_graph(graph, initial, update, root / "meta.json")
            initial_vertices, initial_edges = load_slice(initial)
            update_vertices, update_edges = load_slice(update)
            self.assertEqual(metadata["vertices"], 4)
            self.assertEqual(initial_vertices, 4)
            self.assertEqual(update_vertices, 4)
            self.assertEqual(len(initial_edges), 2)
            self.assertEqual([edge[3] for edge in update_edges], [-1, 1])
            self.assertTrue(all(edge[2] == 1 for edge in update_edges))

    def test_rejects_mismatched_header_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph = root / "bad.graph"
            graph.write_text("4 2 0\n0 1\n", encoding="ascii")
            with self.assertRaises(ValueError):
                convert_graph(
                    graph,
                    root / "initial.slice",
                    root / "update.slice",
                    root / "meta.json",
                )

    def test_preserves_weighted_reciprocal_pma_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph = root / "weighted.graph"
            graph.write_text(
                "4 4 2\n"
                "0 1 7\n"
                "1 0 7\n"
                "2 3 11\n"
                "3 2 11\n"
                "1 2 13 1\n"
                "2 1 13 1\n",
                encoding="ascii",
            )
            initial = root / "initial.slice"
            update = root / "update.slice"
            metadata = convert_graph(
                graph,
                initial,
                update,
                root / "meta.json",
                require_reciprocal=True,
                sort_records=True,
            )
            _vertices, initial_edges = load_slice(initial)
            _vertices, update_edges = load_slice(update)
            self.assertEqual([edge[2] for edge in initial_edges], [7, 7, 11, 11])
            self.assertEqual([edge[2] for edge in update_edges], [13, 13])
            self.assertTrue(metadata["weights_preserved"])
            self.assertTrue(metadata["reciprocal_validated"])
            self.assertIsNone(metadata["unit_weight"])
            self.assertEqual(
                metadata["record_order"], "deterministic_src_dst_weight_diff"
            )

    def test_converts_committed_hardware_alignment_workload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            initial = root / "initial.slice"
            update = root / "update.slice"
            metadata = convert_graph(
                HARDWARE_ALIGNMENT_GRAPH, initial, update, root / "meta.json"
            )
            initial_vertices, initial_edges = load_slice(initial)
            update_vertices, update_edges = load_slice(update)
            self.assertEqual(metadata["source_graph_sha256"], HARDWARE_ALIGNMENT_SHA256)
            self.assertEqual((initial_vertices, len(initial_edges)), (4096, 4096))
            self.assertEqual((update_vertices, len(update_edges)), (4096, 1024))
            self.assertTrue(all(edge[3] == 1 for edge in update_edges))


if __name__ == "__main__":
    unittest.main()
