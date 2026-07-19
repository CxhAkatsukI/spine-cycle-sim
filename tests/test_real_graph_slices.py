from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.extract_real_graph_slices import (
    SourceSelection,
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


if __name__ == "__main__":
    unittest.main()
