"""Synthetic acceptance cases; no FPGA or runtime is used by these tests."""

import unittest

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import board_analysis, preparation

BDF = "0000:01:00.1"
ROW = {"dataset": "AU", "algorithm": "weighted_sssp", "vertices": 327681,
       "initial_edges": 3, "updates": 1, "source": 0}


def fixture(algorithm="weighted_sssp"):
    row = {**ROW, "algorithm": algorithm}
    pr = algorithm == "residual_pagerank"
    prefix = preparation.PREFIXES[algorithm]
    common = "vertices=327681 logical_updates=1 physical_updates=1 destination_partitions=6 pma_slots_total=256"
    lines = [f"GRASU_REGRAPH_DEVICE bdf={BDF}",
             "GRASU_SHARDED_UPDATE_REPEAT_CONFIG repeats=1 restore_pma_between_repeats=1",
             f"{prefix}_INPUT {common} static_edges=3 oracle_converged=1 "
             "resident_state=old_graph_converged source_external=0",
             f"{prefix}_RESULT {common} status=PASS hardware_converged=1 oracle_converged=1 "
             "resident_state=old_graph_converged conversion_cost=absent k4_frontends=4 shared_regraph_downstream=1 "
             + ("rank_mismatches=0 degree_mismatches=0 threshold_semantics=direct_per_vertex max_abs_error=0.00001 "
                "propagation_rounds=1 pipeline_executions=1 processed_edge_slots_per_execution=256" if pr else
                "mismatches=0 source_external=0 executed_supersteps=1 processed_edge_slots_per_superstep=256"),
             f"{prefix}_TIMING setup_inclusive_ms=0.004 "
             + ("device_e2e_ms=0.002" if pr else "event_e2e_ms=0.002")]
    stages = ["hbm", "apply", "adapter", "gather", "mux"] + (["source_prepare"] if pr else [])
    for stage in stages:
        for shard in (range(6) if stage in ("adapter", "gather", "mux") else (-1,)):
            start = 10 if shard < 0 else 10 + shard * 10
            worker = -1 if shard < 0 else shard % 4
            lines.append(f"SHARDED_DEVICE_EVENT stage={stage} round=0 shard={shard} worker={worker} "
                         f"queued_ns=1 submit_ns=2 start_ns={start} end_ns={start + 10}")
    return row, "\n".join(lines) + "\n"


class BoardAnalysisTests(unittest.TestCase):
    def test_three_algorithms_keep_wall_span_and_busy_union_distinct(self):
        for algorithm in preparation.ALGORITHMS:
            row, log = fixture(algorithm)
            report = board_analysis.analyze(row, log, "", bdf=BDF)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["resident_wall_ms"], .004)
            self.assertEqual(report["device_event_span_ms"], .002)
            self.assertEqual(report["compute_timeline"]["compute_union_ms"], 60 / 1e6)
            self.assertIn("initial graph/state preload", report["excluded"])

    def test_wrong_board_duplicate_fields_bad_dimensions_cold_or_partial_execution_rejected(self):
        row, log = fixture()
        for old, new in ((BDF, "0000:02:00.1"), ("repeats=1", "repeats=2"),
                ("vertices=327681", "vertices=327680"), ("static_edges=3", "static_edges=4"),
                ("hardware_converged=1", "hardware_converged=0"), ("oracle_converged=1", "oracle_converged=0"),
                ("old_graph_converged", "cold_fallback"), ("mismatches=0", "mismatches=1"),
                ("k4_frontends=4", "k4_frontends=8"), ("source_external=0", "source_external=1"),
                ("processed_edge_slots_per_superstep=256", "processed_edge_slots_per_superstep=128"),
                ("event_e2e_ms=0.002", "event_e2e_ms=nan"),
                ("setup_inclusive_ms=0.004", "setup_inclusive_ms=0"),
                ("status=PASS", "status=PASS status=PASS"),
                ("worker=0 queued_ns=1", "worker=0 worker=0 queued_ns=1"),
                ("stage=mux round=0 shard=5", "stage=mux round=1 shard=5")):
            with self.subTest(new=new), self.assertRaises((ValueError, KeyError)):
                board_analysis.analyze(row, log.replace(old, new), "", bdf=BDF)
        for bad, stderr in ((log, "warning"), (log + log.splitlines()[2] + "\n", ""),
                            ("\n".join(log.splitlines()[:-1]), "")):
            with self.assertRaises(ValueError):
                board_analysis.analyze(row, bad, stderr, bdf=BDF)

    def test_residual_threshold_and_degree_oracle_required(self):
        row, log = fixture("residual_pagerank")
        for old, new in (("degree_mismatches=0", "degree_mismatches=1"),
                ("direct_per_vertex", "degree_normalized"), ("max_abs_error=0.00001", "max_abs_error=inf"),
                ("propagation_rounds=1", "propagation_rounds=0")):
            with self.subTest(new=new), self.assertRaises(ValueError):
                board_analysis.analyze(row, log.replace(old, new), "", bdf=BDF)

    def test_trace_cannot_exceed_reported_event_span(self):
        row, log = fixture()
        log = log.replace("end_ns=70", "end_ns=10000000")
        with self.assertRaisesRegex(ValueError, "timeline exceeds"):
            board_analysis.analyze(row, log, "", bdf=BDF)


if __name__ == "__main__":
    unittest.main()
