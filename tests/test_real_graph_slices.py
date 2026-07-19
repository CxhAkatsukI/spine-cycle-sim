from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.compare_dstage_tile_schedule import workload_from_case
from scripts.extract_real_graph_slices import (
    SourceSelection,
    exact_slice_case_rows,
    scan_graph,
    translated_case_rows,
)
from spine_cycle_sim.models import load_config


class RealGraphSliceExtractionTests(unittest.TestCase):
    def test_bare_one_based_edge_list_generates_avg_case(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            graph = Path(tmp) / "small.edgelist"
            graph.write_text(
                "\n".join(
                    [
                        "1 2",
                        "1 70000",
                        "2 3",
                        "2 70001",
                        "3 4",
                    ]
                )
                + "\n"
            )
            config = load_config("configs/spine_current.yaml")
            stats = scan_graph(graph)
            selections = [SourceSelection("top2", (0, 1))]
            cases, rows, summary = translated_case_rows(graph, stats, config, selections)

        self.assertEqual(stats.id_offset, 1)
        self.assertEqual(stats.edge_count, 5)
        self.assertEqual(summary["graph_edges"], 5)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].case, "amazon_top2_avg")
        self.assertIn("--multi-source-tile-work", cases[0].args)
        self.assertEqual(rows[0]["raw_active_sources"], 2)
        self.assertGreaterEqual(rows[0]["translated_touched_tiles"], 1)

    def test_exact_slice_generation_is_readable_by_schedule_compare(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            graph = root / "small.edgelist"
            graph.write_text(
                "\n".join(
                    [
                        "1 2",
                        "1 70000",
                        "2 3",
                        "2 70001",
                    ]
                )
                + "\n"
            )
            config = load_config("configs/spine_current.yaml")
            stats = scan_graph(graph)
            selections = [SourceSelection("top2", (0, 1))]
            cases, rows = exact_slice_case_rows(
                graph,
                stats,
                config,
                selections,
                root / "out",
            )
            slice_exists = cases[0].slice_path.exists()
            workload = workload_from_case(
                {"case": cases[0].case, "args": list(cases[0].args)},
                config,
            )

        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].case, "amazon_top2_exact")
        self.assertTrue(slice_exists)
        self.assertEqual(workload.vertices, stats.vertex_count)
        self.assertEqual(workload.edge_count, cases[0].raw_edges)
        self.assertEqual(rows[0]["translation"], "exact_edge_list")


if __name__ == "__main__":
    unittest.main()
