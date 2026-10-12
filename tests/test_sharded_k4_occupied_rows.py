"""Check passive observation and reject changes to complete production replay."""

import copy
import json
from pathlib import Path
import tarfile
import unittest

from spine_cycle_sim.experiments.sharded_k4_stages.row_line.occupied_rows.analysis import (
    analyze, helper_instance, require_replay,
)
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.occupied_rows.delivery import verify


EVIDENCE = Path(__file__).resolve().parents[1] / (
    "docs/experiments/comparisons/grasu_regraph_stage_validation/actual_sharded_k4/"
    "adapter_optimization/row_line/occupied_rows/evidence")


class OccupiedRowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tarfile.open(EVIDENCE / "raw_occupied_rows.tar.gz", "r:gz") as bundle:
            cls.logs = {arm: bundle.extractfile(f"run/{arm}/simulate.stdout.txt").read().decode()
                        for arm in ("reference", "candidate")}
            baseline = next(member for member in bundle.getmembers() if member.name.startswith("run/sources/docs/")
                            and member.name.endswith("row_line/evidence/results.json"))
            cls.baseline = json.loads(bundle.extractfile(baseline).read())
        cls.report = json.loads((EVIDENCE / "results.json").read_text())

    def test_both_arms_complete_replay_and_raw_observation(self):
        for arm, log in self.logs.items():
            with self.subTest(arm=arm):
                cases, observed = analyze(log)
                require_replay(cases, self.baseline["arms"][arm])
                self.assertEqual(observed, self.report["arms"][arm])
                self.assertEqual(len(cases), 12)

    def test_no_source_lost_and_long_rows_overlap_reads(self):
        cases = self.report["arms"]["candidate"]
        self.assertEqual(cases[5]["median_helper_lifetime"], 81)
        self.assertEqual(cases[7]["median_helper_lifetime"], 85)
        self.assertEqual(cases[7]["cycles"] - cases[5]["cycles"], 68)
        self.assertEqual(cases[5]["maximum_outstanding"], 1)
        self.assertEqual(cases[7]["maximum_outstanding"], 3)
        self.assertEqual([r["source"] for r in cases[10]["rows"]], [0, 7, 14])
        self.assertFalse(cases[0]["rows"])

    def test_helper_done_is_not_output_completion(self):
        row = self.report["arms"]["candidate"][11]["rows"][0]
        self.assertGreater(row["first_packet"], row["done"])
        self.assertFalse(self.report["exclusive_stall_attribution"])
        self.assertFalse(self.report["FPGA_timing_admitted"])

    def test_missing_duplicate_and_unknown_observation_rejected(self):
        log = self.logs["candidate"]
        for kind in ("ROW_START", "ROW_DONE", "ROW_PACKET"):
            line = next(line for line in log.splitlines() if line.startswith(kind + " "))
            for changed in (log.replace(line + "\n", "", 1), log + line + "\n",
                            log + line.replace("trial=1 ", "trial=12 ") + "\n"):
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    analyze(changed)

    def test_row_geometry_cycle_and_packet_source_mutation_rejected(self):
        log = self.logs["candidate"]
        start = next(line for line in log.splitlines() if line.startswith("ROW_START trial=1 "))
        packet = next(line for line in log.splitlines() if line.startswith("ROW_PACKET trial=1 "))
        for before, after in ((start, start.replace("begin=0", "begin=1")),
                              (start, start.replace("cycle=", "cycle=999999")),
                              (packet, packet.replace("source=0", "source=1"))):
            with self.subTest(after=after), self.assertRaises(ValueError):
                analyze(log.replace(before, after, 1))

    def test_complete_replay_does_not_only_check_final_cycles(self):
        observed, _ = analyze(self.logs["candidate"])
        for key in ("requests", "responses"):
            changed = copy.deepcopy(observed)
            changed[1][key][0]["cycle"] += 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                require_replay(changed, self.baseline["arms"]["candidate"])

    def test_exactly_one_production_helper_required(self):
        text = "pma_to_regraph_adapter_emit_row_segments grp_emit_row_segments_fu_318 (\n"
        self.assertEqual(helper_instance(text), "grp_emit_row_segments_fu_318")
        for changed in ("", text + text):
            with self.assertRaises(ValueError):
                helper_instance(changed)

    def test_portable_sealed_raw_recheck(self):
        self.assertEqual(verify(EVIDENCE), self.report)


if __name__ == "__main__":
    unittest.main()
