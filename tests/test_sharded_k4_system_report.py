"""Exercise current topology report gates without discarding frozen report support."""

import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.model_system import require_system_report
from spine_cycle_sim.experiments.sharded_k4_stages.system_report import (
    BASE_REPORT, LINE_REPORT, PAIR_BEGIN, PAIR_REPORT, KEYS, base_matrix, line_matrix,
    pair_matrix, extended_scope,
)


def group(expected):
    lines = []
    for key in sorted(expected):
        row = dict(zip(KEYS, key))
        line = "case " + " ".join(f"{name}={row[name]}" for name in (
            "vertices", "reverse", "stop", "pressure", "fixed", "limit", "independent", "stream_depth"))
        line += f" rounds={row['rounds']} failed={row['failed']} cycles=200 parents=10 beats=12"
        if row["row_line_reads"]:
            line += " row_line_reads=1"
        if row["source_topology"] == "two_pairwise":
            line += " source_topology=two_pairwise"
        lines.append(line)
    return lines


def report(paired=True):
    lines = [*group(base_matrix()), BASE_REPORT, *group(line_matrix()), LINE_REPORT]
    if paired:
        lines.extend([PAIR_BEGIN, *group(pair_matrix()), PAIR_REPORT])
    return "\n".join(lines)


class ExtendedSystemReport(unittest.TestCase):
    def test_all_three_sections(self):
        self.assertEqual(len(require_system_report(report())), 42)
        self.assertEqual(extended_scope(report()), {"report_version": "source_pairs_v1",
            "converged_executions": 38, "fixed_round_executions": 2, "expected_limit_failures": 2,
            "admission_rejections": 13})

    def test_preceding_whole_line_report_still_readable(self):
        self.assertEqual(len(require_system_report(report(False))), 30)

    def test_reject_missing_or_duplicate_case(self):
        lines = report().splitlines()
        with self.assertRaises(ValueError):
            require_system_report("\n".join(lines[1:]))
        lines[0] = lines[1]
        with self.assertRaisesRegex(ValueError, "duplicated"):
            require_system_report("\n".join(lines))

    def test_reject_different_pair_registration_cycles(self):
        lines = report().splitlines()
        index = next(i for i, line in enumerate(lines) if "reverse=1" in line and "two_pairwise" in line)
        lines[index] = lines[index].replace("cycles=200", "cycles=201")
        with self.assertRaisesRegex(ValueError, "registration-order"):
            require_system_report("\n".join(lines))

    def test_reject_changed_topology(self):
        with self.assertRaisesRegex(ValueError, "matrix"):
            require_system_report(report().replace(" source_topology=two_pairwise", "", 1))

    def test_reject_incomplete_summary(self):
        with self.assertRaises(ValueError):
            require_system_report(report().replace(PAIR_REPORT, "PASS"))

    def test_reject_unknown_and_negative_count(self):
        for replacement in ("parents=0", "parents=-1", "parents=10 extra=1"):
            with self.assertRaises(ValueError):
                require_system_report(report().replace("parents=10", replacement, 1))


if __name__ == "__main__":
    unittest.main()
