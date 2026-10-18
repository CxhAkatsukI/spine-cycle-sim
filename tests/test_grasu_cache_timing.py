import copy
import hashlib
import json
from pathlib import Path
import unittest

from spine_cycle_sim.experiments.evaluation_impact.common_g.cache_probe.timing_analysis import compare


class CacheTimingTests(unittest.TestCase):
    def test_committed_raw_control_reproduces_analysis(self):
        evidence = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/cache_probe/timing_control")
        model = (evidence / "model.json").read_bytes()
        rtl = (evidence / "rtl.transaction.rpt").read_bytes()
        result = json.loads((evidence / "results.json").read_text())
        inputs = result.pop("inputs")
        self.assertEqual([item["sha256"] for item in inputs],
                         [hashlib.sha256(data).hexdigest() for data in (model, rtl)])
        self.assertEqual(result, compare(json.loads(model), rtl.decode("ascii")))
        execution = json.loads((evidence / "execution.json").read_text())
        self.assertEqual(execution["status"],
                         "MODEL_CACHE_STATE_TRAFFIC_AND_REGISTRATION_PASS_NOT_RTL_OR_BOARD_CALIBRATION")
        self.assertEqual([step["exit_code"] for step in execution["steps"]], [0] * 4)
        self.assertEqual(execution["errors"], [])

    def fixture(self):
        latencies = (278737, 278734, 278782, 282814, 344254, 291028)
        report = "latency interval\n" + "\n".join(
            f"transaction {index}: {latency} x" for index, latency in enumerate(latencies))
        model = {"schema": 1, "complete_state_and_traffic_checked": True,
                 "reverse_registration_checked": True, "input_fifo_depth": 2,
                 "memory_backend": "MockMemoryBackend", "rows": [
                     {"index": index, "updates": count, "conflict": index == 5,
                      "cycles": latency + 1000, "load_complete": 100000,
                      "store_issued": latency - 100000, "read_bytes": 8388608,
                      "write_bytes": 8388608, "lane_queue_stalls": 0}
                     for index, (count, latency) in enumerate(zip(
                         (0, 16, 64, 4096, 65536, 4096), latencies))]}
        return model, report

    def test_increments_do_not_admit_total_time_or_integrated_g(self):
        model, report = self.fixture()
        result = compare(model, report)
        self.assertEqual(result["balanced_4096_to_65536_increment"]["model_cycles_per_update"], 1)
        self.assertEqual(result["balanced_4096_to_65536_increment"]["absolute_difference_cycles_per_update"], 0)
        self.assertFalse(result["total_latency_comparable"])
        for flag in ("hardware_timing_admitted", "integrated_g_admitted",
                     "production_baseline_admitted", "publication_match_admitted"):
            self.assertIs(result[flag], False)

    def test_missing_or_changed_model_scope_is_rejected(self):
        model, report = self.fixture()
        for field, wrong in (("complete_state_and_traffic_checked", False),
                             ("reverse_registration_checked", False),
                             ("input_fifo_depth", 1), ("memory_backend", "DRAMSim3"),
                             ("rows", model["rows"][:-1])):
            with self.subTest(field=field), self.assertRaises(ValueError):
                compare({**model, field: wrong}, report)

    def test_invalid_observations_are_rejected(self):
        model, report = self.fixture()
        for field, wrong in (("updates", 1), ("conflict", 1), ("index", True),
                             ("read_bytes", 0), ("write_bytes", 0),
                             ("load_complete", 0), ("store_issued", 99999),
                             ("cycles", 1), ("lane_queue_stalls", -1)):
            changed = copy.deepcopy(model)
            changed["rows"][0][field] = wrong
            with self.subTest(field=field), self.assertRaises(ValueError):
                compare(changed, report)

    def test_changed_rtl_scope_and_nonpositive_latency_are_rejected(self):
        model, report = self.fixture()
        for wrong in (report.rsplit("\n", 1)[0], report.replace("transaction 5:", "transaction 6:"),
                      report.replace("278737", "0"), report.replace("latency interval", "latency")):
            with self.subTest(report=wrong), self.assertRaises(ValueError):
                compare(model, wrong)
