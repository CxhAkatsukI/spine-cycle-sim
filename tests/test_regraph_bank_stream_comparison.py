import copy
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.analysis import MATRIX, identity, summarize
from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.study import configure_command
from tests.test_regraph_credit_controls import fixture as credit_fixture


def fixture():
    reference, _ = credit_fixture()
    old = {identity(row): row for row in reference}
    rows = []
    for latency, reverse, arm in MATRIX:
        row = copy.deepcopy(old[(latency, reverse, "candidate" if arm == "bank_stream" else arm)])
        row["arm"] = arm
        row["observations"]["result"]["arm"] = arm
        for part in row["observations"]["trajectory"]:
            part["arm"] = arm
        rows.append(row)
    return rows, reference


class BankStreamComparisonTests(unittest.TestCase):
    def test_build_pins_gcc_not_environment_default(self):
        command = configure_command(Path("/fresh/build"))
        self.assertIn("-DCMAKE_CXX_COMPILER=/usr/bin/g++", command)
        self.assertIn("-DCMAKE_BUILD_TYPE=Release", command)
        self.assertEqual(command[command.index("-B") + 1], "/fresh/build")

    def test_all_rows_and_non_admission_claims(self):
        result = summarize(*fixture())
        self.assertEqual(result["legacy_rows_replayed_exactly"], 28)
        self.assertEqual([r["bank_stream_over"]["candidate"] for r in result["comparisons"]], [1, 1])
        for key in ("strict_resource_match_admitted", "hardware_timing_admitted",
                    "publication_match_admitted", "production_baseline_admitted", "new_spine_comparison_executed"):
            self.assertIs(result[key], False)

    def test_missing_duplicate_reordered_matrix(self):
        rows, reference = fixture()
        for changed in (rows[:-1], rows[:-1] + rows[:1], rows[::-1]):
            with self.subTest(), self.assertRaisesRegex(ValueError, "32-row"):
                summarize(changed, reference)
        with self.assertRaisesRegex(ValueError, "28-row"):
            summarize(rows, reference[:-1])

    def test_every_old_arm_is_frozen_not_just_original_twelve(self):
        for field in ("cycles", "read_bytes", "write_bytes"):
            rows, reference = fixture()
            row = next(row for row in rows if row["arm"] == "candidate_both2")
            row["observations"]["result"][field] += 1
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "legacy"):
                summarize(rows, reference)

    def test_new_topology_registration_order(self):
        rows, reference = fixture()
        rows[7]["observations"]["result"]["read_bytes"] += 64
        with self.assertRaisesRegex(ValueError, "registration"):
            summarize(rows, reference)

    def test_new_topology_state_and_convergence_must_match(self):
        for kind in ("state", "trajectory", "missing_replica"):
            rows, reference = fixture()
            for row in rows:
                if row["arm"] != "bank_stream":
                    continue
                if kind == "state":
                    for output in row["outputs"]:
                        output["sha256"] = "changed"
                elif kind == "trajectory":
                    row["observations"]["trajectory"][0]["active"] += 1
                else:
                    row["outputs"].pop()
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "replicas|semantics"):
                summarize(rows, reference)

    def test_unclosed_cycles_nonconverged_wrong_arm_invalid_traffic(self):
        for kind in ("cycles", "active", "arm", "traffic"):
            rows, reference = fixture()
            for row in rows:
                if row["arm"] != "bank_stream":
                    continue
                observation = row["observations"]
                if kind == "cycles":
                    observation["result"]["cycles"] += 1
                elif kind == "active":
                    observation["trajectory"][-1]["active"] = 1
                elif kind == "arm":
                    observation["result"]["arm"] = "candidate"
                else:
                    observation["result"]["read_bytes"] = -1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                summarize(rows, reference)


if __name__ == "__main__":
    unittest.main()
