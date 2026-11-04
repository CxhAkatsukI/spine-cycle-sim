import copy
import unittest

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.figure9_directory_receipts import (
    comparison,
)


def simulation_row():
    spine = dict(correctness=True, ledger_closed=True, read_bytes=16, write_bytes=4, energy_pj=10,
                 state_hashes={"old_state": "a", "final": "b", "expected": "b"})
    gr = dict(copy.deepcopy(spine), read_bytes=36, energy_pj=30)
    return dict(status="PREDICTION_ONLY", baseline_admitted=False, updates=8,
                spine=spine, gr=gr, accepted_bytes_ratio=2, hbm_energy_ratio=3)


class DirectoryReceiptsTest(unittest.TestCase):
    def test_reconstructs_absolute_totals_and_ratios(self):
        frozen = simulation_row()
        directory = simulation_row()
        directory["gr"].update(read_bytes=56, energy_pj=60)
        directory.update(accepted_bytes_ratio=3, hbm_energy_ratio=6)
        result = comparison(frozen, directory)
        self.assertEqual(result["frozen_gr_accepted_bytes"], 40)
        self.assertEqual(result["directory_gr_accepted_bytes"], 60)
        self.assertEqual(result["directory_accepted_bytes_ratio_gr_over_spine"], 3)
        self.assertEqual(result["directory_hbm_energy_ratio_gr_over_spine"], 6)

    def test_rejects_incorrect_state_ledger_ratio_or_admission(self):
        for target, key, value in [
            (("gr", "state_hashes"), "old_state", "changed"),
            (("gr",), "ledger_closed", False),
            (("spine",), "correctness", False),
            ((), "hbm_energy_ratio", 4),
            ((), "baseline_admitted", True),
        ]:
            with self.subTest(key=key):
                directory = simulation_row()
                node = directory
                for field in target:
                    node = node[field]
                node[key] = value
                with self.assertRaises(ValueError):
                    comparison(simulation_row(), directory)
