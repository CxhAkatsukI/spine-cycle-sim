import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.sst_input_audit import INF, synchronous_sssp


class OldStateAuditTests(unittest.TestCase):
    def test_synchronous_rounds_and_unreachable(self):
        values, rounds = synchronous_sssp([[(1, 2), (2, 9)], [(2, 3)], [], []], 0)
        self.assertEqual(values, [0, 2, 5, INF])
        self.assertEqual(rounds, 3)

    def test_cycles_do_not_reactivate_without_improvement(self):
        self.assertEqual(synchronous_sssp([[(1, 2)], [(0, 2)]], 0), ([0, 2], 2))

    def test_host_oracle_cap_is_not_silently_increased(self):
        with self.assertRaises(ValueError):
            synchronous_sssp([[(1, 2)], [(2, 3)], []], 0, limit=1)


if __name__ == "__main__":
    unittest.main()
