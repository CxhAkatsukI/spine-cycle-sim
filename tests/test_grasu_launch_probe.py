import unittest
from pathlib import Path
import tempfile

from spine_cycle_sim.experiments.publication_board_probe.grasu_launch import inspect
from spine_cycle_sim.experiments.publication_board_probe.grasu_launch_analysis import synthesis_loop


class GrasuLaunchProbeTests(unittest.TestCase):
    def lines(self):
        return ["GRASU_REGRAPH_DEVICE bdf=0000:c1:00.1",
                "GRASU_SHARDED_UPDATE_REPEAT_CONFIG repeats=4 restore_pma_between_repeats=1",
                *[f"GRASU_SHARDED_UPDATE_REPEAT repeat={i} final={int(i == 3)} update_ms={ms}"
                  for i, ms in enumerate((50, 20, 22, 21))],
                "GRASU_SHARDED_UPDATE_ONLY_RESULT status=PASS pma_mismatches=0 checked_words=32 repeats=4 update_ms=21"]

    def test_uses_warm_median_and_declares_limited_correctness_scope(self):
        report = inspect(self.lines(), "0000:c1:00.1")
        self.assertEqual(report["cold_ms"], 50)
        self.assertEqual(report["warm_median_ms"], 21)
        self.assertIn("last repeat", report["correctness_scope"])

    def test_rejects_incomplete_duplicate_failed_or_nonfinite_results(self):
        lines = self.lines()
        for changed in (lines[:-1], lines[:3] + lines[4:],
                        [line.replace("repeat=2", "repeat=1") for line in lines],
                        [line.replace("mismatches=0", "mismatches=1") for line in lines],
                        [line.replace("update_ms=22", "update_ms=nan") for line in lines],
                        [line.replace("update_ms=21", "update_ms=23") if line.startswith("GRASU_SHARDED_UPDATE_ONLY_RESULT") else line
                         for line in lines],
                        [line.replace("restore_pma_between_repeats=1", "restore_pma_between_repeats=0") for line in lines]):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                inspect(changed, "0000:c1:00.1")
        with self.assertRaises(ValueError):
            inspect(lines, "0000:82:00.1")

    def test_synthesis_schedule_is_read_from_xml(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthesis.xml"
            path.write_text("""<profile><PerformanceEstimates>
                <SummaryOfOverallLatency><Best-caseLatency>131075</Best-caseLatency></SummaryOfOverallLatency>
                <SummaryOfLoopLatency><preload_all><PipelineII>16</PipelineII>
                <TripCount>8192</TripCount></preload_all></SummaryOfLoopLatency>
                </PerformanceEstimates></profile>""")
            report = synthesis_loop(path, "preload_all")
            self.assertEqual(report["achieved_ii"], 16)
            self.assertEqual(report["trip_count"], 8192)
            self.assertEqual(report["best_case_cycles"], 131075)
            with self.assertRaises((TypeError, ValueError)):
                synthesis_loop(path, "missing_loop")
