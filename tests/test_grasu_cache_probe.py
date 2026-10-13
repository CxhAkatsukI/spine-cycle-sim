import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.analysis import analyze, transactions
from spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.preparation import ARMS, FULL_ARMS, tcl
from spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.study import wait_for_memory


class CacheProbeTests(unittest.TestCase):
    def transaction_text(self, full=False):
        latencies = (100, 200) if full else (17617, 17728, 17800, 18376, 20680, 20680)
        return " latency interval\n" + "".join(
            f"transaction {i}: {latency} x\n" for i, latency in enumerate(latencies))

    def test_transaction_scope_and_same_row_trajectory(self):
        rows = transactions(self.transaction_text())
        self.assertEqual([row["updates"] for row in rows], [0, 40, 64, 256, 1024, 1024])
        self.assertEqual((rows[4]["latency"] - rows[2]["latency"]) / 960, 3)
        self.assertEqual([row["updates"] for row in transactions(self.transaction_text(True), full=True)], [16, 64])

    def test_incomplete_duplicate_or_unexpected_report_rejected(self):
        text = self.transaction_text()
        for bad in (text.replace(" latency interval", "wrong"),
                    text.rsplit("transaction", 1)[0], text + "transaction 5: 20680 x\n",
                    text.replace("transaction 3:", "transaction 2:"),
                    text.replace("18376", "NaN")):
            with self.assertRaises(ValueError):
                transactions(bad)

    def fixture(self, folder, clock="6.804", full=False, cosim_pass=True, extended=False):
        top = "cache_full_probe" if full else "cache_bank_probe"
        syn = folder / "project/solution/syn/report"
        syn.mkdir(parents=True)
        (syn / (top + "_csynth.xml")).write_text(f"""<profile>
<PerformanceEstimates><SummaryOfTimingAnalysis><EstimatedClockPeriod>{clock}</EstimatedClockPeriod>
</SummaryOfTimingAnalysis></PerformanceEstimates><AreaEstimates><Resources><URAM>16</URAM>
</Resources></AreaEstimates></profile>""")
        sim = folder / "project/solution/sim/report"
        (sim / "verilog").mkdir(parents=True)
        (sim / (top + "_cosim.rpt")).write_text("| Verilog | " + ("Pass" if cosim_pass else "Fail") + " |")
        (sim / "verilog/result.transaction.rpt").write_text(self.transaction_text(full))
        csim = folder / "project/solution/csim/report"
        csim.mkdir(parents=True)
        if extended:
            (sim / "verilog/result.transaction.rpt").write_text(self.transaction_text())
        marker, count = ("CACHE_FULL_PASS", 6 if extended else 2) if full else ("CACHE_BANK_PASS", 6)
        (csim / (top + "_csim.log")).write_text((marker + "\n") * count)

    def test_functional_pass_does_not_promote_failed_clock_or_integrated_g(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.fixture(folder)
            result = analyze(folder)
        self.assertFalse(result["target_5ns_met"])
        self.assertFalse(result["hardware_timing_admitted"])
        self.assertFalse(result["integrated_g_admitted"])
        self.assertEqual(result["same_row_incremental_cycles_per_update"], 3)

    def test_full_scope_not_summarized_as_single_bank(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.fixture(folder, "3.65", full=True)
            result = analyze(folder, full=True)
        self.assertEqual(result["state_control_calls"], 2)
        self.assertEqual(result["complete_bank_segments"], 131072)
        self.assertIn("sixteen_bank", result["claim"])
        self.assertIsNone(result["same_row_incremental_cycles_per_update"])

    def test_failed_rtl_cannot_be_analyzed_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.fixture(folder, cosim_pass=False)
            with self.assertRaises(ValueError):
                analyze(folder)

    def test_extended_full_scope_and_same_bank_case(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            self.fixture(folder, "3.65", full=True, extended=True)
            result = analyze(folder, full=True, full_extended=True)
            with self.assertRaises(ValueError):
                analyze(folder, full=True)
        self.assertEqual(result["state_control_calls"], 6)
        self.assertEqual([row["updates"] for row in result["transactions"]],
                         [0, 16, 64, 4096, 65536, 4096])
        self.assertEqual(result["transactions"][-1]["pattern"], "single_bank_same_row")
        with self.assertRaises(ValueError):
            transactions(self.transaction_text(), full_extended=True)

    def test_low_memory_never_launches_or_shrinks_the_reserve(self):
        record, saves = {}, []
        with patch("spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.study.available_memory_bytes",
                   return_value=29 * 1024**3):
            with self.assertRaisesRegex(RuntimeError, "no tool launched"):
                wait_for_memory(record, lambda: saves.append(True), maximum_wait=0)
        self.assertFalse(record["memory_admission"]["admitted"])
        self.assertEqual(record["memory_admission"]["required_bytes"], 30 * 1024**3)
        self.assertEqual(len(saves), 1)

    def test_memory_wait_recovers_without_changing_resource_budget(self):
        record = {}
        module = "spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.study"
        with patch(module + ".available_memory_bytes", side_effect=[29 * 1024**3, 31 * 1024**3]), \
                patch(module + ".time.sleep"):
            wait_for_memory(record, lambda: None)
        self.assertTrue(record["memory_admission"]["admitted"])
        self.assertEqual(len(record["memory_admission"]["samples"]), 2)

    def test_declared_arms_and_unchanged_source_wrapper(self):
        self.assertEqual(ARMS, ("original", "lane_wiring", "registered_wiring"))
        for arm in (*ARMS, *FULL_ARMS):
            script = tcl(arm)
            self.assertIn("create_clock -period 5", script)
            self.assertIn("cosim_design -rtl verilog -tool xsim", script)
            self.assertNotIn("config_dataflow", script)
        self.assertIn("set_top cache_full_probe", tcl(FULL_ARMS[0]))
        self.assertIn("../source/cache_full.cpp", tcl(FULL_ARMS[0]))
        with self.assertRaises(ValueError):
            tcl("unknown")


if __name__ == "__main__":
    unittest.main()
