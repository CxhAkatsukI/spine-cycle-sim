from __future__ import annotations

import unittest
from types import SimpleNamespace

from scripts.compare_dstage_tile_schedule import compare_counters


class DStageScheduleCompareTests(unittest.TestCase):
    def test_split_swept_words_accepts_host_range(self) -> None:
        sim = SimpleNamespace(
            active_sources=1,
            active_records=1,
            traversed_edges=1,
            touched_tiles=1,
            nonempty_tiles=1,
            empty_tile_passes=0,
            fast_path_tiles=0,
            full_path_tiles=1,
            gathered_vertex_words=0,
            swept_vertex_words=200,
            marked_tiles=1,
            fallback_used=0,
            row_lookups=1,
            clipped_ranges=1,
            active_record_replays=1,
            scattered_vertex_words=0,
        )
        hw = {
            "case": "case",
            "repeat": "1",
            "active_sources": "1",
            "active_records": "1",
            "traversed_edges": "1",
            "touched_tiles": "1",
            "nonempty_tiles": "1",
            "empty_tile_passes": "0",
            "fast_path_tiles": "0",
            "full_path_tiles": "1",
            "gathered_vertex_words": "0",
            "swept_vertex_words": "150",
        }

        rows = compare_counters([hw], {"case": sim}, split_kernels=True)

        self.assertEqual(rows[0]["status"], "PASS")

    def test_muxed_swept_words_stays_exact(self) -> None:
        sim = SimpleNamespace(
            active_sources=1,
            active_records=1,
            traversed_edges=1,
            touched_tiles=1,
            nonempty_tiles=1,
            empty_tile_passes=0,
            fast_path_tiles=0,
            full_path_tiles=1,
            gathered_vertex_words=0,
            swept_vertex_words=200,
            marked_tiles=1,
            fallback_used=0,
            row_lookups=1,
            clipped_ranges=1,
            active_record_replays=1,
            scattered_vertex_words=0,
        )
        hw = {
            "case": "case",
            "repeat": "1",
            "active_sources": "1",
            "active_records": "1",
            "traversed_edges": "1",
            "touched_tiles": "1",
            "nonempty_tiles": "1",
            "empty_tile_passes": "0",
            "fast_path_tiles": "0",
            "full_path_tiles": "1",
            "gathered_vertex_words": "0",
            "swept_vertex_words": "150",
        }

        rows = compare_counters([hw], {"case": sim}, split_kernels=False)

        self.assertEqual(rows[0]["status"], "FAIL")
        self.assertIn("swept_vertex_words", rows[0]["mismatch_fields"])


if __name__ == "__main__":
    unittest.main()
