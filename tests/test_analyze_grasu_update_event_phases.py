from pathlib import Path
import tempfile
import unittest

from scripts.analyze_grasu_update_event_phases import (
    collect_case,
    correlation_rows,
    parse_fields,
    pearson_r2,
    provenance_for_case,
)


class AnalyzeGrasuUpdateEventPhasesTests(unittest.TestCase):
    def test_parse_fields_ignores_prefix(self) -> None:
        self.assertEqual(
            parse_fields("PREFIX shard=2 union_ms=3.5"),
            {"shard": "2", "union_ms": "3.5"},
        )

    def test_collect_case_joins_layout_event_and_phases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = Path(temporary) / "au_weighted_sssp"
            case.mkdir()
            (case / "run.log").write_text(
                "\n".join(
                    (
                        "GRASU_SHARDED_UPDATE_LAYOUT shard=1 updates=2 unique_sources=1 pma_slots=64 source_segments=3 binary_probes=2 cache_updates=2 ddr_updates=0",
                        "GRASU_SHARDED_UPDATE_EVENTS shard=1 gap_from_previous_ms=0 union_ms=4",
                        "GRASU_SHARDED_UPDATE_EVENTS_PHASE shard=1 cu=dispatch queued_offset_ms=0 queued_to_submit_ms=1 submit_to_start_ms=0.001 execute_ms=4 start_offset_ms=0 end_offset_ms=4",
                        "GRASU_SHARDED_UPDATE_EVENTS_PHASE shard=1 cu=search0 queued_offset_ms=0.1 queued_to_submit_ms=3 submit_to_start_ms=0.002 execute_ms=0.5 start_offset_ms=3 end_offset_ms=3.5",
                    )
                )
                + "\n",
                encoding="ascii",
            )
            shards, phases = collect_case(case)
            self.assertEqual(len(shards), 1)
            self.assertEqual(len(phases), 2)
            self.assertEqual(shards[0]["updates"], 2)
            self.assertEqual(shards[0]["max_queued_to_submit_ms"], 3.0)
            self.assertEqual(shards[0]["max_submit_to_start_ms"], 0.002)

    def test_collect_case_rejects_missing_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = Path(temporary) / "au_weighted_sssp"
            case.mkdir()
            (case / "run.log").write_text(
                "GRASU_SHARDED_UPDATE_EVENTS shard=1 union_ms=4\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(ValueError, "incomplete"):
                collect_case(case)

    def test_provenance_requires_passing_hardware_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            case = Path(temporary) / "au_weighted_sssp"
            case.mkdir()
            (case / "run.log").write_text("routed evidence\n", encoding="ascii")
            (case / "run.env").write_text(
                "STATUS=PASS TARGET=hw ALGORITHM=weighted_sssp "
                "REPO_HEAD=abc REPO_DIRTY=0 HOST_SHA256=host "
                "XCLBIN_SHA256=xclbin GRAPH_SHA256=graph\n",
                encoding="ascii",
            )
            row = provenance_for_case(case)
            self.assertEqual(row["status"], "PASS")
            self.assertEqual(len(str(row["run_log_sha256"])), 64)

    def test_pearson_r2_detects_linear_relation(self) -> None:
        self.assertAlmostEqual(pearson_r2((1, 2, 3), (2, 4, 6)), 1.0)

    def test_correlations_keep_sample_count(self) -> None:
        rows = [
            {
                "algorithm": "weighted_sssp",
                "updates": value,
                "unique_sources": value,
                "pma_slots": 10 * value,
                "source_segments": value,
                "binary_probes": value,
                "union_ms": 2 * value,
            }
            for value in (1, 2, 3)
        ]
        correlations = correlation_rows(rows)
        self.assertTrue(all(row["samples"] == 3 for row in correlations))


if __name__ == "__main__":
    unittest.main()
