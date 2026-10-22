import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.analysis import MATRIX, identity, summarize
from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream.study import REGRESSION_TIMEOUT_SECONDS, configure_command
from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import runtime
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
    def test_memory_profiles_do_not_weaken_remote_or_permit_local_parallelism(self):
        remote = runtime.settings(runtime.memory_profiles.SEELE, 4)
        self.assertEqual(remote["policy"]["reserve_gib"], 128)
        self.assertEqual(remote["policy"]["tree_memory_gib"], 40)
        self.assertEqual(remote["high_gib"], 36)
        local = runtime.settings(runtime.LOCAL, 1)
        self.assertEqual(local["policy"], dict(tree_memory_gib=6, reserve_gib=24,
            background_memory_gib=8, allow_bounded_builds=True))
        self.assertFalse(runtime.memory_profiles.observed(local["policy"]))
        for profile, workers in ((runtime.LOCAL, 2), (runtime.LOCAL, 0),
                                 (runtime.LOCAL, True), (runtime.memory_profiles.SEELE, 5), ("anything", 1)):
            with self.subTest(profile=profile, workers=workers), self.assertRaises(ValueError):
                runtime.settings(profile, workers)

    def test_local_guard_requires_exact_limits_and_zero_swap_verifier(self):
        selected = runtime.settings(runtime.LOCAL, 1)
        limits = {"memory.max": str(6 * 1024**3), "memory.high": str(5 * 1024**3)}
        with patch.object(runtime, "verify", return_value={"limits": limits}) as verify:
            self.assertEqual(runtime.containment(Path("/group"), selected), {"limits": limits})
            verify.assert_called_once_with(Path("/group"), memory_gib=6)
        for key in limits:
            with patch.object(runtime, "verify", return_value={"limits": {**limits, key: "max"}}), \
                    self.subTest(key=key), self.assertRaisesRegex(ValueError, "exact"):
                runtime.containment(Path("/group"), selected)

    def test_local_admission_reserves_full_peer_limits_and_rejects_unbounded(self):
        local = runtime.settings(runtime.LOCAL, 1)["policy"]
        peers = [{"bounded": True, "memory_max_bytes": 32 * 1024**3} for _ in range(2)]
        self.assertEqual(runtime.high_memory.required_bytes(local, peers), 102 * 1024**3)
        self.assertFalse(runtime.high_memory.eligible(101 * 1024**3, peers, local))
        self.assertTrue(runtime.high_memory.eligible(102 * 1024**3, peers, local))
        self.assertFalse(runtime.high_memory.eligible(251 * 1024**3,
            [{"bounded": False, "reason": "missing cgroup limit"}], local))

    def test_admission_wait_is_finite_and_zero_wait_never_enters_execution(self):
        for seconds in (-1, True, 86401, 0.5):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                runtime.wait_budget(seconds)
        self.assertEqual(runtime.wait_budget(0), 0)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(runtime, "current", return_value=Path("/own")), \
                patch.object(runtime, "containment", return_value={}), \
                patch.object(runtime.high_memory, "lease") as factory, \
                patch.object(runtime, "available_memory_bytes", return_value=1), \
                patch.object(runtime, "other_builds", return_value=[]):
            lease = factory.return_value
            lease.sample.return_value = {"admitted": False}
            with self.assertRaises(runtime.AdmissionUnavailable):
                with runtime.reservation(Path(directory), runtime.settings(runtime.LOCAL, 1), 0):
                    self.fail("denied admission entered execution")
            lease.sample.assert_called_once()
            lease.release.assert_called_once()
            self.assertTrue((Path(directory) / "admission.json").is_file())

    def test_build_pins_gcc_not_environment_default(self):
        command = configure_command(Path("/fresh/build"))
        self.assertIn("-DCMAKE_CXX_COMPILER=/usr/bin/g++", command)
        self.assertIn("-DCMAKE_BUILD_TYPE=Release", command)
        self.assertEqual(command[command.index("-B") + 1], "/fresh/build")
        self.assertEqual(REGRESSION_TIMEOUT_SECONDS, 600)

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
