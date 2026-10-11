"""Reject incomplete or mismatched whole-system validation reports."""

import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.model_system import FIELDS, REPORT, require_system_report


def report():
    cases = []
    for vertices, pressure, rounds in ((129, 0, 4), (65569, 0, 4), (262273, 0, 5), (129, 1, 4)):
        for reverse in (0, 1): cases.append((vertices, reverse, 1, pressure, 0, 128, rounds, 0))
    cases += [(129, reverse, 0, 0, 0, 128, 4, 0) for reverse in (0, 1)]
    cases += [(129, 0, 1, 0, 0, 128, 1, 0), (129, 0, 1, 0, 2, 128, 2, 0), (129, 0, 1, 0, 0, 1, 1, 1)]
    return "\n".join(["case " + " ".join(f"{field}={value}" for field, value in zip(FIELDS, (*row, 200, 10, 12)))
                      for row in cases] + [REPORT])


class WholeSystemReport(unittest.TestCase):
    def test_complete_report(self):
        rows = require_system_report(report())
        self.assertEqual(len(rows), 13)
        self.assertEqual(sum(row["failed"] for row in rows), 1)

    def test_order_not_significant(self):
        lines = report().splitlines()
        self.assertEqual(sorted(require_system_report("\n".join(reversed(lines[:-1])) + "\n" + REPORT), key=str),
                         sorted(require_system_report(report()), key=str))

    def test_reject_missing_execution(self):
        with self.assertRaises(ValueError): require_system_report("\n".join(report().splitlines()[1:]))

    def test_reject_duplicate(self):
        lines = report().splitlines()
        lines[0] = lines[1]
        with self.assertRaisesRegex(ValueError, "duplicated"): require_system_report("\n".join(lines))

    def test_reject_different_reverse_cycles(self):
        text = report().replace("reverse=1 stop=1 pressure=0 fixed=0 limit=128 rounds=4 failed=0 cycles=200",
                                "reverse=1 stop=1 pressure=0 fixed=0 limit=128 rounds=4 failed=0 cycles=201", 1)
        with self.assertRaisesRegex(ValueError, "registration-order"): require_system_report(text)

    def test_reject_failed_limit_relabel(self):
        with self.assertRaisesRegex(ValueError, "matrix"):
            require_system_report(report().replace("limit=1 rounds=1 failed=1", "limit=1 rounds=1 failed=0"))

    def test_reject_changed_round_count(self):
        with self.assertRaisesRegex(ValueError, "matrix"):
            require_system_report(report().replace("rounds=5", "rounds=4"))

    def test_reject_empty_count(self):
        with self.assertRaisesRegex(ValueError, "transaction"):
            require_system_report(report().replace("parents=10", "parents=0"))

    def test_reject_unrelated_success(self):
        with self.assertRaises(ValueError): require_system_report("PASS")


if __name__ == "__main__":
    unittest.main()
