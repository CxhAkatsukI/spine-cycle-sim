import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.cc_resident_results import analyze


WORKLOAD = {"vertices": 12, "edges": 22, "updates": 2}
BDF = "0000:82:00.1"
DIMS = ("vertices=12 logical_updates=2 physical_updates=2 final_edges=24 "
        "resident_state=old_graph_converged oracle_converged=1")
GR = f"""GRASU_REGRAPH_DEVICE bdf={BDF}
GRASU_SHARDED_UPDATE_REPEAT_CONFIG repeats=1 restore_pma_between_repeats=1
CC_PMA_NATIVE_SHARDED_INPUT {DIMS} static_edges=22
SHARDED_RESIDENT_BATCH_WALL algorithm=CC_PMA_NATIVE status=PASS layout=trace_aware physical_update_mapping=offline pack_upload_and_host_seed_ms=1 pack_to_final_readback_ms=3
CC_PMA_NATIVE_SHARDED_RESULT {DIMS} status=PASS mismatches=0 hardware_converged=1 k4_frontends=4 shared_regraph_downstream=1 conversion_cost=absent executed_supersteps=1
"""
CONTEXT = "sample=0 order=0 hot=1 full=0 batch=0"
SPINE = f"""CC_BOOTSTRAP_PASS {CONTEXT} valid=1
CC_RESIDENT_WALL {CONTEXT} vertices=12 physical_records=2 host_pack_to_final_readback_ms=2 batch_resident_to_final_readback_ms=1.5
CC_UPDATE_PASS {CONTEXT} valid=1 physical_records=2 logical_deletions=0 rounds=0
CC_REPAIR_PASS vertices=12 updates=1 all_raw_labels_checked=1 all_raw_graphs_checked=1 all_round_work_checked=1
"""


class CCResidentResultsTest(unittest.TestCase):
    def test_same_boundary_uses_outer_window_and_retains_both_outcomes(self):
        win = analyze(WORKLOAD, GR, SPINE, bdf=BDF)
        self.assertEqual(win["gr_over_spine"], 1.5)
        self.assertEqual(win["spine_rounds"], 0)
        self.assertTrue(win["spine_hot_layout"])
        cold = SPINE.replace("hot=1", "hot=0").replace(
            "host_pack_to_final_readback_ms=2", "host_pack_to_final_readback_ms=4")
        loss = analyze(WORKLOAD, GR, cold, bdf=BDF)
        self.assertEqual(loss["gr_over_spine"], .75)
        self.assertFalse(loss["spine_hot_layout"])

    def test_rejects_legacy_or_unmatched_run(self):
        for gr, spine in (
            (GR.replace("SHARDED_RESIDENT_BATCH_WALL", "CC_PMA_NATIVE_SHARDED_TIMING"), SPINE),
            (GR, SPINE.replace("CC_RESIDENT_WALL", "CC_TIMING")),
            (GR.replace("repeats=1 ", "repeats=3 "), SPINE),
            (GR.replace(BDF, "0000:17:00.1"), SPINE),
            (GR.replace("old_graph_converged", "cold_fallback"), SPINE),
            (GR.replace("final_edges=24", "final_edges=23"), SPINE),
            (GR.replace("mismatches=0", "mismatches=1"), SPINE),
            (GR.replace("pack_to_final_readback_ms=3", "pack_to_final_readback_ms=nan"), SPINE),
            (GR, SPINE.replace("valid=1", "valid=0", 1)),
            (GR, SPINE.replace("all_raw_labels_checked=1", "all_raw_labels_checked=0")),
            (GR, SPINE.replace("logical_deletions=0", "logical_deletions=1")),
            (GR, SPINE.replace("readback_ms=1.5", "readback_ms=2.5")),
            (GR, SPINE + SPINE),
        ):
            with self.subTest(gr=gr, spine=spine), self.assertRaises(ValueError):
                analyze(WORKLOAD, gr, spine, bdf=BDF)
