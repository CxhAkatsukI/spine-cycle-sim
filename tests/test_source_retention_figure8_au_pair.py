"""Native Figure 8 receipts must use matching inputs, one batch, and complete timers."""

import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.figure8_au_pair import (
    record, timer,
)


SPINE = ("SPINE_UPDATE_SETUP_ONCE status=PASS vertices=515281 initial_edges=390847 "
         "logical_updates=512 layout_ns=1 bootstrap_ns=2 batch_ns=3 update_wall_ns=4 "
         "setup_inclusive_ns=10 repeats=1 checked_edges=391359")
GR = ("GRASU_SHARDED_UPDATE_SETUP_ONCE status=PASS vertices=515281 initial_edges=390847 "
      "logical_updates=512 layout_ns=1 upload_ns=2 update_wall_ns=4 setup_inclusive_ns=7 "
      "repeats=1 trace_aware_pma=1 pma_mismatches=0")


class NativeAuPairTest(unittest.TestCase):
    def test_valid_disjoint_timers(self):
        self.assertEqual(timer(SPINE, "spine")["setup_inclusive_ns"], 10)
        self.assertEqual(timer(GR, "gr")["setup_inclusive_ns"], 7)

    def test_reject_incorrect_timers(self):
        for original, replacement in (("repeats=1", "repeats=3"), ("logical_updates=512", "logical_updates=64"),
                                      ("pma_mismatches=0", "pma_mismatches=1"),
                                      ("setup_inclusive_ns=7", "setup_inclusive_ns=6"),
                                      ("update_wall_ns=4", "update_wall_ns=-4")):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                timer(GR.replace(original, replacement), "gr")

    def test_reject_duplicate_records_and_fields(self):
        with self.assertRaises(ValueError):
            timer(SPINE + "\n" + SPINE, "spine")
        with self.assertRaises(ValueError):
            record("PMA status=FAIL status=PASS", "PMA")
