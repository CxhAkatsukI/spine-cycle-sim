import copy
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.analysis import analyze, parse
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.admission import GIB, decision
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline import admission
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import freeze_runner, unchanged
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.preparation import CASES, MODES, tcl
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.rtl_analysis import (
    analyze_rtl, parse_bench, transactions,
)


class SearchPipelineTests(unittest.TestCase):
    def test_committed_capsule_keeps_complete_controls_and_closed_admission(self):
        folder = Path(__file__).resolve().parents[1] / (
            "docs/experiments/comparisons/grasu_regraph_stage_validation/"
            "evaluation_impact/search_pipeline/evidence")
        index = json.loads((folder / "index.json").read_text())
        self.assertEqual(index["executions"], 38)
        self.assertEqual(index["cu_controls"], 152)
        self.assertEqual(index["rtl_bench_source"]["calls"], 18)
        for key in ("hardware_timing_admitted", "production_baseline_admitted",
                    "publication_match_admitted", "new_spine_comparison_executed",
                    "core_or_sst_numerical_code_changed"):
            self.assertIs(index[key], False)
        for report in index["reports"]:
            self.assertEqual(hashlib.sha256((folder / report["file"]).read_bytes()).hexdigest(),
                             report["sha256"])
        matrix = json.loads((folder / "matrix.json").read_text())
        previous = json.loads((folder / "previous_metadata.json").read_text())
        self.assertEqual(analyze(matrix, previous), matrix["analysis"])
        with tarfile.open(folder / "raw_controls.tar.gz") as archive:
            self.assertEqual(sorted(archive.getnames()), sorted(row["member"] for row in index["raw_members"]))
            for row in index["raw_members"]:
                contents = archive.extractfile(row["member"]).read()
                self.assertEqual(len(contents), row["bytes"])
                self.assertEqual(hashlib.sha256(contents).hexdigest(), row["sha256"])
            stdout = archive.extractfile("controls/rtl-bench.stdout.txt").read().decode()
            self.assertEqual(parse_bench(stdout), index["rtl_bench_source"])

    def stdout(self, count, mode):
        rows = []
        for cu in range(4):
            size = (count + 3 - cu) // 4
            rows.append(f"SEARCH_PIPELINE_PASS updates={size} probes={2 * size} "
                        f"stalled={int(mode == 'stalled')} channels=339 "
                        "output_blocked=0 host_vendor_keep_bits=16")
        rows.append(f"SEARCH_PIPELINE_FIXTURE_PASS updates={count} probes={2 * count}")
        return "\n".join(rows)

    def fixture(self):
        rows = [{"case": name, "updates": count, "mode": mode,
                 "control": parse(self.stdout(count, mode), count, mode),
                 "execution": {"exit_code": 0, "timed_out": False}}
                for name, count, _ in CASES for mode in MODES]
        previous = {"status": "G_METADATA_CREDIT_PREDICTIONS_VALIDATED", "errors": [],
                    "rows": [{"case": name, "updates": count, "arm": "cached_hot64_m32",
                              "latency": 64, "observation": {"binary_probes": 2 * count}}
                             for name, count, _ in CASES]}
        report = {"rows": rows, "errors": [],
                  "matrix": [(name, count, mode) for name, count, _ in CASES for mode in MODES],
                  "hardware_timing_admitted": False, "production_baseline_admitted": False,
                  "publication_match_admitted": False}
        return report, previous

    def test_complete_declaration_without_timing_admission(self):
        report, previous = self.fixture()
        result = analyze(report, previous)
        self.assertEqual(result["executions"], 38)
        self.assertEqual(result["cu_controls"], 152)
        self.assertTrue(result["work_matches_cycle_engine"])
        self.assertIn("not_RTL", result["claim"])

    def test_parse_rejects_scope_topology_and_ledger_errors(self):
        stdout = self.stdout(257, "stalled")
        for wrong in (stdout.replace("channels=339", "channels=338", 1),
                      stdout.replace("stalled=1", "stalled=0", 1),
                      stdout.replace("updates=65", "updates=64", 1),
                      stdout.replace("probes=514", "probes=513"),
                      stdout.replace("keep_bits=16", "keep_bits=12", 1),
                      stdout + "\n" + stdout):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                parse(wrong, 257, "stalled")
        with self.assertRaises(ValueError):
            parse(self.stdout(0, "unblocked").replace("probes=0", "probes=1"), 0, "unblocked")
        with self.assertRaises(ValueError):
            parse(stdout, 257, "unknown")

    def test_analysis_refuses_missing_work_or_false_admission(self):
        for fault in ("missing", "duplicate", "matrix", "failed", "timeout", "error",
                      "work", "ordered", "channels", "previous", "reference", "duplicate_reference",
                      "hardware_timing_admitted", "production_baseline_admitted", "publication_match_admitted"):
            with self.subTest(fault=fault):
                report, previous = self.fixture()
                row = report["rows"][-1]
                if fault == "missing": report["rows"].pop()
                elif fault == "duplicate": report["rows"].append(copy.deepcopy(row))
                elif fault == "matrix": report["matrix"].pop()
                elif fault == "failed": row["execution"]["exit_code"] = 1
                elif fault == "timeout": row["execution"]["timed_out"] = True
                elif fault == "error": report["errors"].append("retained")
                elif fault == "work": row["control"]["binary_probes"] += 1
                elif fault == "ordered": row["control"]["ordered_packets_pass"] = False
                elif fault == "channels": row["control"]["finite_channels_conserved"] = False
                elif fault == "previous": previous["status"] = "RUNNING"
                elif fault == "reference": previous["rows"].pop()
                elif fault == "duplicate_reference": previous["rows"].append(previous["rows"][0])
                else: report[fault] = True
                with self.assertRaises(ValueError): analyze(report, previous)

    def test_hls_keeps_clock_and_finite_rtl_gate(self):
        script = tcl()
        self.assertIn("create_clock -period 5", script)
        self.assertIn("csim_design", script)
        self.assertIn("csynth_design", script)
        self.assertIn("cosim_design -rtl verilog -tool xsim", script)
        self.assertIn("-deadlock_detection sim", script)

    def test_top_pointer_avoids_vendor_testbench_scalar_count_collision(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "cpp/tests/evaluation_impact/common_g/hls/search_pipeline/top.cpp").read_text()
        self.assertIn("const search_pipeline::Raw* binary_nodes", source)
        self.assertIn("m_axi port=binary_nodes ", source)
        self.assertIn("s_axilite port=binary_nodes ", source)
        self.assertNotIn("port=binary ", source)
        self.assertNotIn("const search_pipeline::Raw* binary,", source)

    def test_search_worker_keeps_blocking_handshakes_in_separate_iterations(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "cpp/tests/evaluation_impact/common_g/hls/"
                         "search_pipeline/search_worker.hpp").read_text()
        self.assertIn("#pragma HLS PIPELINE off", source)
        self.assertNotIn("#pragma HLS PIPELINE II=1", source)
        for phase in ("row_decode", "binary_compare", "midpoint", "choose"):
            self.assertIn(f"case SearchPhase::{phase}:", source)
        self.assertEqual(source.count("metadata = responses.read();"), 2)

    def test_gather_registers_selection_before_fifo_transfer(self):
        source = (Path(__file__).resolve().parents[1] /
                  "cpp/tests/evaluation_impact/common_g/hls/search_pipeline/transport.hpp").read_text()
        gathers = source[:source.index("inline void memory(")]
        self.assertEqual(gathers.count("#pragma HLS PIPELINE off"), 2)
        self.assertNotIn("#pragma HLS PIPELINE II=1", gathers)
        self.assertEqual(gathers.count("selected = select_ready(ready, cursor);"), 2)
        self.assertEqual(gathers.count("if (!pending)"), 2)
        self.assertEqual(gathers.count("pending = false;"), 4)
        for fifo in ("requests", "input"):
            self.assertIn(f"{fifo}[selected].read()", gathers)
        self.assertEqual(gathers.count("cursor = selected + 1;"), 2)

    def test_feedback_pipelines_insert_bubbles_on_empty_input(self):
        source = (Path(__file__).resolve().parents[1] /
                  "cpp/tests/evaluation_impact/common_g/hls/search_pipeline/transport.hpp").read_text()
        feedback = source[source.index("inline void memory("):]
        self.assertEqual(feedback.count("#pragma HLS PIPELINE II=1"), 3)
        self.assertNotIn("input.read()", feedback)
        self.assertEqual(feedback.count("if (!input.read_nb("), 3)
        self.assertIn("if (request[33]) break;", feedback)
        self.assertIn("if (response[70]) break;", feedback)

    def test_empty_host_polls_yield_after_releasing_the_queue_lock(self):
        root = Path(__file__).resolve().parents[1]
        folder = root / "cpp/tests/evaluation_impact/common_g/hls/search_pipeline"
        source = (folder / "finite_host.hpp").read_text()
        for begin, end in (("  bool read_nb(", "  size_t size("),
                           ("  size_t size(", "  ChannelStats stats(")):
            method = source[source.index(begin):source.index(end)]
            self.assertLess(method.index("lock.unlock();"),
                            method.index("std::this_thread::yield();"))
        network = (folder / "network.hpp").read_text()
        self.assertIn('#ifndef __SYNTHESIS__\n#include "finite_host.hpp"\n#endif', network)
        self.assertNotIn("std::this_thread", (folder / "transport.hpp").read_text())

    def test_concurrent_component_tools_require_all_declared_memory_budgets(self):
        previous = {"LoadState": "loaded", "ActiveState": "active", "MemoryMax": str(512 * 1024**2)}
        route = {"LoadState": "loaded", "ActiveState": "active", "MemoryMax": str(40 * GIB)}
        self.assertTrue(decision(previous, route, 200 * GIB)["admitted"])
        self.assertEqual(decision(previous, route, 78 * GIB)["required_bytes"], 78 * GIB)
        self.assertFalse(decision(previous, route, 77 * GIB)["admitted"])
        self.assertFalse(decision(previous, route, 83 * GIB, 6)["admitted"])
        self.assertTrue(decision(previous, route, 84 * GIB, 6)["admitted"])
        previous["ActiveState"] = "inactive"
        result = decision(previous, route, 64 * GIB)
        self.assertEqual(result["required_bytes"], 72 * GIB)
        self.assertFalse(result["admitted"])
        self.assertTrue(decision(previous, route, 72 * GIB)["admitted"])
        route["ActiveState"] = "failed"
        self.assertTrue(decision(previous, route, 32 * GIB)["admitted"])
        self.assertFalse(decision(previous, route, 31 * GIB)["admitted"])

    def test_component_and_background_limits_fail_closed(self):
        inactive = {"LoadState": "loaded", "ActiveState": "inactive"}
        for limit in ("0", "-1", "infinity", str(7 * GIB)):
            active = {"LoadState": "loaded", "ActiveState": "active", "MemoryMax": limit}
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                decision(active, inactive, 200 * GIB)
        for invalid in (-1, 41, 1.5, True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                decision(inactive, inactive, 200 * GIB, invalid)

    def test_hls_attempt_freezes_actual_runner_separately_from_control_basis(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            pins = freeze_runner(folder)
            unchanged(pins)
            self.assertTrue(any(Path(pin["path"]).name == "admission.py" for pin in pins))
            self.assertTrue(any(Path(pin["path"]).name == "execution.py" for pin in pins))
            for pin in pins:
                frozen = Path(pin["frozen_path"])
                self.assertTrue(frozen.is_relative_to(folder / "runner"))
                self.assertEqual(hashlib.sha256(frozen.read_bytes()).hexdigest(), pin["sha256"])

    def test_collected_transient_unit_is_explicitly_absent_not_unknown(self):
        absent = {"LoadState": "not-found", "ActiveState": "inactive", "SubState": "dead",
                  "MemoryMax": "infinity"}
        with patch.object(admission.subprocess, "run") as probe:
            probe.return_value.stdout = "\n".join(f"{k}={v}" for k, v in absent.items())
            self.assertEqual(admission.unit_state("collected.service"), absent)
        self.assertTrue(decision(absent, absent, 32 * GIB)["admitted"])
        self.assertEqual(decision(absent, absent, 32 * GIB)["route_reservation_bytes"], 0)
        for changed in ({}, {**absent, "ActiveState": "active"},
                        {**absent, "SubState": "running"},
                        {**absent, "LoadState": "error"},
                        {**absent, "LoadState": "loaded", "ActiveState": "unknown"}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                admission.terminal(changed)

    def test_active_route_requires_a_finite_positive_limit(self):
        previous = {"LoadState": "loaded", "ActiveState": "inactive"}
        for limit in ("0", "-1", "infinity", str(252 * GIB)):
            route = {"LoadState": "loaded", "ActiveState": "active", "MemoryMax": limit}
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                decision(previous, route, 251 * GIB)

    def test_rtl_transactions_require_all_18_calls(self):
        report = "latency interval\n" + "\n".join(
            f"transaction {i}: {100 + i} x" for i in range(18))
        rows = transactions(report)
        self.assertEqual(len(rows), 18)
        self.assertEqual(rows[-1]["updates"], 257)
        self.assertTrue(rows[-1]["same_key"])
        for bad in (report + "\ntransaction 18: 1 x", report.replace("transaction 17:", "transaction 16:"),
                    report.replace("latency interval", "other header"),
                    report.replace("transaction 17: 117 x", "bad row")):
            with self.assertRaises(ValueError): transactions(bad)

    def test_testbench_source_is_not_rtl_or_finite_fifo_evidence(self):
        contents = "\n".join(
            f"SEARCH_PIPELINE_PASS updates={count} probes={count} stalled=0 "
            "channels=0 output_blocked=0 host_vendor_keep_bits=16"
            for count in (0, 1, 63, 64, 65, 127, 128, 129, 257) for _ in range(2))
        result = parse_bench(contents)
        self.assertEqual(result["calls"], 18)
        self.assertEqual(result["claim"], "testbench_source_not_RTL_execution")
        for bad in (contents.replace("channels=0", "channels=339", 1),
                    contents.replace("stalled=0", "stalled=1", 1),
                    contents + "\n" + contents):
            with self.assertRaises(ValueError): parse_bench(bad)

    def test_rtl_state_pass_cannot_hide_clock_failure_or_promote_whole_g(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            project = folder / "project/solution"
            for relative in ("syn/report", "csim/report", "sim/report/verilog"):
                (project / relative).mkdir(parents=True)
            source = "\n".join(
                f"SEARCH_PIPELINE_PASS updates={count} probes={count} stalled=0 "
                "channels=0 output_blocked=0 host_vendor_keep_bits=16"
                for count in (0, 1, 63, 64, 65, 127, 128, 129, 257) for _ in range(2))
            (project / "csim/report/bin_search_pipeline_csim.log").write_text(source)
            cosim = project / "sim/report/bin_search_pipeline_cosim.rpt"
            cosim.write_text("| Verilog | Pass |\n")
            (project / "sim/report/verilog/result.transaction.rpt").write_text(
                "latency interval\n" + "\n".join(f"transaction {i}: 100 x" for i in range(18)))
            tree = ET.Element("profile")
            performance = ET.SubElement(tree, "PerformanceEstimates")
            timing = ET.SubElement(performance, "SummaryOfTimingAnalysis")
            clock = ET.SubElement(timing, "EstimatedClockPeriod")
            resources = ET.SubElement(ET.SubElement(tree, "AreaEstimates"), "Resources")
            ET.SubElement(resources, "LUT").text = "100"
            path = project / "syn/report/bin_search_pipeline_csynth.xml"
            for value, passed in (("8.036", False), ("5", True)):
                clock.text = value
                ET.ElementTree(tree).write(path)
                result = analyze_rtl(folder)
                self.assertEqual(result["target_5ns_met"], passed)
                self.assertFalse(result["hardware_timing_admitted"])
                self.assertFalse(result["integrated_g_admitted"])
                self.assertFalse(result["external_RTL_backpressure_tested"])
            clock.text = "nan"
            ET.ElementTree(tree).write(path)
            with self.assertRaises(ValueError): analyze_rtl(folder)
            cosim.write_text("| Verilog | Fail |\n")
            with self.assertRaises(ValueError): analyze_rtl(folder)


if __name__ == "__main__":
    unittest.main()
