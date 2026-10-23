"""A retained AXI bug fix may change R timing, never answers or byte ledgers."""

import copy
import unittest

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.multialgorithm import (
    sssp_replay, validation,
)


def report():
    rows = []
    for workload in ("smoke", "amazon"):
        for latency in (64, 128):
            for arm, reverse in (("gr", 0), ("gr", 1), ("spine", 0)):
                result = dict(arm=arm, cycles=110, rounds=2, read_bytes=640, write_bytes=128,
                              correctness=True, ledger_closed=True)
                if arm == "gr":
                    result.update(g_cycles=10, r_cycles=100, handoff_cycle_gap=0)
                rows.append(dict(workload=workload, latency=latency, arm=arm, reverse=reverse,
                    input=dict(batch="same", old="same"), result=result,
                    state_hashes=dict(old_state="old", expected="answer", final="answer")))
    return dict(pins_unchanged=True, failures=[], rows=rows)


class ReadCreditReplayTests(unittest.TestCase):
    def test_only_explicit_r_timing_changes_are_accepted_and_exported(self):
        before = report()
        after = copy.deepcopy(before)
        for row in after["rows"]:
            if row["arm"] == "gr":
                row["result"]["cycles"] += 7
                row["result"]["r_cycles"] += 7
        checked = sssp_replay.compare(before, after)
        self.assertEqual(checked["status"], "SSSP_READ_CREDIT_CORRECTION")
        self.assertEqual(len(checked["cycle_deltas"]), 12)
        self.assertEqual({r["delta_cycles"] for r in checked["cycle_deltas"]}, {0, 7})

    def test_byte_state_input_or_spine_timing_changes_are_rejected(self):
        for field in ("bytes", "state", "input", "spine", "g", "gap", "correctness"):
            after = report()
            first = after["rows"][0]
            if field == "bytes":
                first["result"]["read_bytes"] += 64
            elif field == "state":
                first["state_hashes"]["final"] = "different"
            elif field == "input":
                first["input"]["batch"] = "different"
            elif field == "spine":
                after["rows"][2]["result"]["cycles"] += 1
            elif field == "g":
                first["result"]["g_cycles"] += 1
            elif field == "gap":
                first["result"]["cycles"] += 1
            else:
                first["result"]["correctness"] = False
            with self.subTest(field=field), self.assertRaises(ValueError):
                sssp_replay.compare(report(), after)

    def test_registration_order_cannot_change_timing(self):
        after = report()
        after["rows"][0]["result"]["cycles"] += 1
        after["rows"][0]["result"]["r_cycles"] += 1
        with self.assertRaisesRegex(ValueError, "registration order"):
            sssp_replay.compare(report(), after)

    def test_duplicate_missing_or_incomplete_runs_are_rejected(self):
        for mode in ("duplicate", "missing", "failure", "changed"):
            after = report()
            if mode == "duplicate":
                after["rows"][1] = copy.deepcopy(after["rows"][0])
            elif mode == "missing":
                after["rows"].pop()
            elif mode == "failure":
                after["failures"] = ["failed"]
            else:
                after["pins_unchanged"] = False
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                sssp_replay.compare(report(), after)

    def test_replay_requires_the_same_core_libraries_and_shared_harness(self):
        pins = [dict(path=path, sha256="same", bytes=1) for path in (
            "/build/libspine_cycle_core.a", "/build/liboriginal_regraph_cycle.a",
            "/repo/cpp/tests/evaluation_impact/warm_comparison/main.cpp",
        )]
        matrix = dict(pins=copy.deepcopy(pins))
        replay = dict(status="SSSP_READ_CREDIT_CORRECTION", pins=copy.deepcopy(pins))
        validation.replay_sources(replay, matrix)
        for mode in ("library", "harness", "missing_library", "missing_harness", "status"):
            changed = copy.deepcopy(replay)
            if mode == "library":
                changed["pins"][0]["sha256"] = "different"
            elif mode == "harness":
                changed["pins"][2]["sha256"] = "different"
            elif mode == "missing_library":
                changed["pins"].pop(0)
            elif mode == "missing_harness":
                changed["pins"].pop(2)
            else:
                changed["status"] = "FAILED_RETAINED"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                validation.replay_sources(changed, matrix)


if __name__ == "__main__":
    unittest.main()
