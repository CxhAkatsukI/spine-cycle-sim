"""New CC checkpoints never promote pending, stale-route or mismatched-control rows."""

import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import cc_checkpoint as cc


class CcCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.matrix = dict(status="RUNNING_SINGLE_PASS", runner_pins=[],
            cases={ds: dict(status="NOT_REQUESTED") for ds in cc.figure.DATASETS},
            baseline=dict(algorithm="cc", image=dict(sha256="image"), resident_mhz=[150, 500, 450, 0]),
            parent=dict(route=dict(sha256="route")), odd_r={})
        self.checked = dict(workload=dict(updates=16), same_driver_clocks=True,
            clocks_mhz=dict(gr=[150, 500, 450, 0]), images=dict(gr=dict(sha256="image")),
            spine_ms=20, gr_ms=10, gr_over_spine=0.5, spine_rounds=0, gr_rounds=1)

    def test_pending_and_failed_parent_retained_without_loading_any_board_sample(self):
        self.matrix.update(status="FAILED_RETAINED", error="route failed")
        with patch.object(cc.figure, "load") as load:
            rows, evidence = cc.collect(self.matrix, "image")
        load.assert_not_called()
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(row["parent_error"] == "route failed" for row in rows))
        self.assertEqual(evidence, [])

    def test_requires_every_declared_dataset(self):
        del self.matrix["cases"]["AU"]
        with self.assertRaisesRegex(ValueError, "all eight"):
            cc.collect(self.matrix, "image")

    def au(self):
        self.matrix["cases"]["AU"] = dict(status=cc.figure.MEASURED, kind="replacement_au",
            result=dict(path="receipt", sha256="sha", bytes=10))

    def test_replacement_au_replays_and_retains_a_loss_and_reused_gr(self):
        self.au()
        with patch.object(cc, "unchanged"), \
                patch.object(cc.figure, "cc_replacement_au", return_value=self.checked) as replay, \
                patch.object(cc.figure, "load", return_value={}):
            rows, evidence = cc.collect(self.matrix, "image")
        replay.assert_called_once_with(self.matrix, self.matrix["cases"]["AU"])
        au = next(row for row in rows if row["dataset"] == "AU")
        self.assertEqual(au["pair"]["speedup_gr_over_spine"], 0.5)
        self.assertEqual((au["pair"]["logical_updates"], au["pair"]["physical_updates"]), (8, 16))
        self.assertTrue(au["gr_sample_reused"])
        self.assertEqual(len(evidence), 1)

    def test_rejects_wrong_baseline_clock_batch_and_legacy_au(self):
        self.au()
        with patch.object(cc, "unchanged"):
            with self.assertRaisesRegex(ValueError, "current G/R"):
                cc.collect(self.matrix, "other-image")
            self.matrix["cases"]["AU"]["kind"] = "legacy_au"
            with self.assertRaisesRegex(ValueError, "replacement-route"):
                cc.collect(self.matrix, "image")
            self.matrix["cases"]["AU"]["kind"] = "replacement_au"
            for changes in (dict(workload=dict(updates=8)), dict(same_driver_clocks=False)):
                with self.subTest(changes=changes), \
                        patch.object(cc.figure, "cc_replacement_au", return_value=dict(self.checked, **changes)), \
                        self.assertRaisesRegex(ValueError, "changed the batch"):
                    cc.collect(self.matrix, "image")

    def test_non_au_requires_exact_replacement_and_one_attempt_per_arm(self):
        self.matrix["cases"]["SU"] = dict(status=cc.figure.MEASURED, result={}, attempts=["spine", "gr"])
        child = dict(status=cc.figure.MEASURED, warm_candidate=self.matrix["parent"]["route"])
        with patch.object(cc, "unchanged"), patch.object(cc.figure, "load", return_value=child), \
                patch.object(cc.figure, "measured", return_value=self.checked) as measured, \
                patch.object(cc.figure, "record_cc_topology") as topology:
            rows, _ = cc.collect(self.matrix, "image")
            self.assertFalse(next(row for row in rows if row["dataset"] == "SU")["gr_sample_reused"])
            measured.assert_called_once()
            topology.assert_called_once()
            child["warm_candidate"] = {}
            with self.assertRaisesRegex(ValueError, "new route"):
                cc.collect(self.matrix, "image")


if __name__ == "__main__":
    unittest.main()
