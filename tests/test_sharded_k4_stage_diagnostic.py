import unittest
from pathlib import Path
import tempfile

from spine_cycle_sim.experiments.sharded_k4_stages.analysis import analyze_log, peak_concurrency, union_ns
from spine_cycle_sim.experiments.sharded_k4_stages.execution import select_case
from spine_cycle_sim.experiments.sharded_k4_stages.synthesis import read_report


def fixture():
    lines = ["TEST_SHARDED_RESULT status=PASS destination_partitions=5 k4_frontends=4 "
             "shared_regraph_downstream=1 executed_supersteps=1 conversion_cost=absent",
             "TEST_SHARDED_TIMING event_e2e_ms=0.001 setup_inclusive_ms=0.002"]
    for stage in ("hbm", "apply", "adapter", "gather", "mux"):
        for shard in (range(5) if stage in ("adapter", "gather", "mux") else (-1,)):
            start = 10 if shard < 0 else 10 + shard * 10
            worker = -1 if shard < 0 else shard % 4
            lines.append(f"SHARDED_DEVICE_EVENT stage={stage} round=0 shard={shard} "
                         f"worker={worker} queued_ns=1 submit_ns=2 start_ns={start} end_ns={start + 10}")
    return "\n".join(lines)


class TimelineTests(unittest.TestCase):
    def test_union_does_not_double_count(self):
        self.assertEqual(union_ns([(0, 10), (2, 5), (9, 12), (20, 22)]), 14)
        self.assertEqual(peak_concurrency([(0, 10), (2, 5), (10, 12)]), 2)

    def test_complete_round(self):
        report = analyze_log(fixture(), require_trace=True)
        self.assertEqual(report["event_count"], 17)
        self.assertEqual(report["compute_span_ms"], 50 / 1e6)
        self.assertEqual(report["compute_union_ms"], 50 / 1e6)

    def test_missing_duplicate_and_wrong_dependency_rejected(self):
        log = fixture()
        bad = ["\n".join(log.splitlines()[:-1]), log + "\n" + log.splitlines()[-1],
               log.replace("start_ns=50 end_ns=60", "start_ns=11 end_ns=21")]
        for candidate in bad:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                analyze_log(candidate, require_trace=True)

    def test_disabled_trace_and_nonpassing_result(self):
        log = "\n".join(fixture().splitlines()[:2])
        self.assertEqual(analyze_log(log, require_trace=False)["event_count"], 0)
        with self.assertRaises(ValueError):
            analyze_log(log, require_trace=True)
        with self.assertRaises(ValueError):
            analyze_log(log.replace("status=PASS", "status=FAIL"), require_trace=False)

    def test_tail_is_union_not_sum(self):
        log = fixture().replace("stage=adapter round=0 shard=0 worker=0 queued_ns=1 submit_ns=2 start_ns=10 end_ns=20",
                                "stage=adapter round=0 shard=0 worker=0 queued_ns=1 submit_ns=2 start_ns=10 end_ns=25")
        self.assertEqual(analyze_log(log, require_trace=True)["adapter_after_gather_union_ms"], 5 / 1e6)

    def test_select_case_requires_unique_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            matrix = Path(directory) / "matrix.tsv"
            matrix.write_text("case\talgorithm\nx\tweighted_sssp\n")
            self.assertEqual(select_case(matrix, "x")["algorithm"], "weighted_sssp")
            with self.assertRaises(ValueError):
                select_case(matrix, "missing")
            matrix.write_text(matrix.read_text() + "x\tweighted_sssp\n")
            with self.assertRaises(ValueError):
                select_case(matrix, "x")

    def test_synthesis_uses_structured_reports_and_binds_vitis_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reports = root / "build/kernel/solution/syn/report"
            reports.mkdir(parents=True)
            (reports / "pma_to_regraph_adapter_csynth.xml").write_text(
                "<Report><AreaEstimates><Resources><LUT>42</LUT></Resources></AreaEstimates>"
                "<PerformanceEstimates><SummaryOfTimingAnalysis><EstimatedClockPeriod>4.867</EstimatedClockPeriod>"
                "</SummaryOfTimingAnalysis><SummaryOfLoopLatency><Loop><Name>source_loop</Name>"
                "<IterationLatency>77</IterationLatency></Loop></SummaryOfLoopLatency>"
                "</PerformanceEstimates></Report>")
            db = root / "build/kernel/solution/.autopilot/db"
            db.mkdir(parents=True)
            (db / "burst.xml").write_text('<VitisHLS:BurstInfo><burst VarName="row_offset" '
                                          'group="BURST_VERBOSE_PASSED"/></VitisHLS:BurstInfo>')
            report = read_report(root)
            self.assertEqual(report["resources"]["LUT"], 42)
            self.assertEqual(report["loops"][0]["IterationLatency"], "77")
            self.assertEqual(report["row_burst_findings"][0]["group"], "BURST_VERBOSE_PASSED")
            report_file = reports / "pma_to_regraph_adapter_csynth.xml"
            report_file.write_text(report_file.read_text().replace(
                "<IterationLatency>77</IterationLatency>",
                "<IterationLatency><range><min>6</min><max>99</max></range></IterationLatency>"))
            self.assertEqual(read_report(root)["loops"][0]["IterationLatency"]["range"]["min"], "6")


if __name__ == "__main__":
    unittest.main()
