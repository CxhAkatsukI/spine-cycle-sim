from __future__ import annotations

import unittest

from spine_cycle_sim.calibration.bridge import (
    BridgeModels,
    predict_e2e,
    predict_e2e_from_results,
    sim_result_to_evidence,
    write_sim_evidence_dir,
)
from spine_cycle_sim.calibration.reader import load_reader_rows

FREQ = 134.0


# --- lightweight stubs so tests don't fit the heavy real models --------------


class _StubB:
    def predicted_cycles(self, record) -> float:
        return 1000.0 + float(record.batch_edges)

    def predict(self, record) -> dict:
        return {
            "whatifs": {
                "halve_repeated_filter_scans": {"speedup": 1.05},
                "halve_level_write_path": {"speedup": 1.5},
            }
        }


class _StubReader:
    def predicted_cycles(self, row) -> float:
        return 5000.0


def _stub_models() -> BridgeModels:
    return BridgeModels(
        b_model=_StubB(),
        reader_model=_StubReader(),
        dspan_predict=lambda row: {"d_span": 6000.0, "full_sweep_half": 5000.0,
                                   "replay_to_clipped": 4000.0},
        overhead_cycles=100.0,
        freq_mhz=FREQ,
    )


def _sim_result(case="t", edges=256, records=64, tiles=4, fallback=0):
    entries = []
    for tile in range(tiles):
        entries.append({
            "partition": 0, "tile": tile, "tile_begin": tile * 65536,
            "tile_end": tile * 65536 + 1, "tile_size": 1, "tile_work": edges // tiles,
            "path": "fast" if not fallback else "full", "fallback_used": fallback,
            "nonempty": 1, "clipped_ranges": 1,
            "gathered_vertex_words": edges // tiles, "swept_vertex_words": 0,
            "scattered_vertex_words": edges // tiles,
        })
    return {
        "case": case, "edges": edges,
        "dstage_tile_active_records": records, "dstage_tile_active_sources": records,
        "dstage_tile_touched_tiles": tiles, "dstage_tile_traversed_edges": edges,
        "dstage_tile_fast_path_tiles": tiles if not fallback else 0,
        "dstage_tile_full_path_tiles": 0 if not fallback else tiles,
        "dstage_tile_fallback_used": fallback,
        "dstage_tile_schedule": entries,
    }


class EvidenceMappingTests(unittest.TestCase):
    def test_sim_result_to_evidence_fields(self) -> None:
        summary, tiles = sim_result_to_evidence(_sim_result(edges=256, records=64, tiles=4),
                                                "t", "reader_replay")
        self.assertEqual(summary["case"], "t")
        self.assertEqual(summary["median_traversed_edges"], 256.0)
        self.assertEqual(summary["median_active_records"], 64.0)
        self.assertEqual(summary["median_touched_tiles"], 4.0)
        self.assertEqual(summary["successful_repeats"], summary["repeats"])
        self.assertEqual(len(tiles), 4)
        self.assertTrue(all(t["case"] == "t" and t["repeat"] == 1 for t in tiles))

    def test_write_and_reload_matches_structural_features(self) -> None:
        import tempfile

        result = _sim_result(edges=512, records=4, tiles=8)
        with tempfile.TemporaryDirectory() as tmp:
            sim_dir = write_sim_evidence_dir(
                [sim_result_to_evidence(result, "c", "reader_partition_spread")], tmp
            )
            rows = load_reader_rows(sim_dir)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            # Loader-derived features round-trip from the sim tile schedule.
            self.assertEqual(row["tile_fast_count"], 8.0)
            self.assertEqual(row["active_records_x_touched_tiles"], 4.0 * 8.0)


class PredictTests(unittest.TestCase):
    def test_serial_excludes_reader(self) -> None:
        reader_row = {"median_traversed_edges": 256, "tile_partition_count": 1,
                      "median_active_records": 64}
        dstage_row = {}
        out = predict_e2e(_stub_models(), reader_row, dstage_row, case="t", sweep="s")
        # serial = B(1000+256) + D(6000) + overhead(100); R(5000) NOT included.
        self.assertAlmostEqual(out["serial_pred_cycles"], 1256.0 + 6000.0 + 100.0, places=3)
        self.assertAlmostEqual(out["R_pred_cycles"], 5000.0, places=3)
        self.assertNotAlmostEqual(out["serial_pred_cycles"],
                                  1256.0 + 5000.0 + 6000.0 + 100.0, places=3)

    def test_actuals_drive_error(self) -> None:
        reader_row = {"median_traversed_edges": 256, "tile_partition_count": 1,
                      "median_active_records": 64}
        actuals = {"B_actual": 1256.0, "R_actual": 5000.0, "D_span_actual": 6000.0,
                   "kernel_e2e_actual": 7356.0}
        out = predict_e2e(_stub_models(), reader_row, {}, case="t", sweep="s", actuals=actuals)
        # serial_pred = 7356 == kernel actual -> ~0 error.
        self.assertAlmostEqual(out["serial_error_pct"], 0.0, places=3)
        self.assertAlmostEqual(out["B_error_pct"], 0.0, places=3)

    def test_from_results_integration(self) -> None:
        result = _sim_result(case="int", edges=256, records=64, tiles=4)
        preds = predict_e2e_from_results(_stub_models(), [("int", "reader_replay", result)])
        self.assertEqual(len(preds), 1)
        p = preds[0]
        self.assertEqual(p["case"], "int")
        self.assertIn("serial_pred_cycles", p)
        self.assertIn("bottleneck_pred", p)
        # R still out of serial in the full pipeline.
        self.assertAlmostEqual(p["serial_pred_cycles"],
                               p["B_pred_cycles"] + p["D_span_pred_cycles"]
                               + p["overhead_model_cycles"], places=3)


if __name__ == "__main__":
    unittest.main()
