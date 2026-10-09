from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.upstream_controls.hls_preparation import (
    _include_flag, _tcl_string, prepare_hls_job, validate_synthesis_contract,
)
from spine_cycle_sim.experiments.upstream_controls.hls_analysis import (
    _normalized_locations, analyze_run, analyze_study, compare_repetitions, read_loop_schedules,
)
from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.hls_reports import (
    collect_interfaces, collect_reports, log_diagnostics, read_csynth_report,
)


ROOT = Path(__file__).resolve().parents[1]
REPORT = """<profile>
<UserAssignments><TopModelName>process_cache</TopModelName><Part>xcu250</Part></UserAssignments>
<PerformanceEstimates>
  <SummaryOfOverallLatency><Best-caseLatency>undef</Best-caseLatency></SummaryOfOverallLatency>
  <SummaryOfLoopLatency>
    <LoopLatency name="load"><PipelineII>16</PipelineII></LoopLatency>
    <LoopLatency name="update"><PipelineII>undef</PipelineII></LoopLatency>
  </SummaryOfLoopLatency>
</PerformanceEstimates>
<AreaEstimates><Resources><URAM>256</URAM></Resources></AreaEstimates>
</profile>"""


class SynthesisContractTests(unittest.TestCase):
    def setUp(self):
        self.contract = json.loads((ROOT / (
            "configs/experiments/grasu_regraph_upstream_synthesis_v1.json")).read_text())

    def test_full_declared_matrix_has_distinct_identity(self):
        validate_synthesis_contract(self.contract)
        self.assertEqual(len(self.contract["jobs"]), 12)
        self.assertNotIn("SW_EMU", json.dumps(self.contract))
        for name in ("grasu_regraph_upstream_synthesis_u55c_v2.json",
                     "grasu_regraph_upstream_synthesis_apply_compat_v3.json"):
            validate_synthesis_contract(json.loads((ROOT / "configs/experiments" / name).read_text()))

    def test_empty_duplicate_unsafe_and_unsupported_jobs_reject(self):
        for jobs in ([], self.contract["jobs"] * 2,
                     [{"id": "../escape", "family": "grasu", "kernel": "cache"}],
                     [{"id": "g", "family": "grasu", "kernel": "arbitrary.cpp"}],
                     [{"id": "r", "family": "regraph", "kernel": "big", "little": 4, "big": 0}]):
            self.contract["jobs"] = jobs
            with self.assertRaises(ValueError):
                validate_synthesis_contract(self.contract)

    def test_invalid_clock_part_and_resource_budget_reject(self):
        for field, value in (("grasu_clock_ns", float("nan")),
                             ("regraph_clock_ns", True), ("grasu_part", "part;exit"),
                             ("reserve_gib", 15), ("memory_limit_gib", 0),
                             ("timeout_seconds", False)):
            contract = copy.deepcopy(self.contract)
            contract[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_synthesis_contract(contract)

    def test_control_binding_cannot_change_arbitrary_kernel_ports(self):
        self.contract["jobs"][0]["bind_arg_reg_control"] = True
        with self.assertRaises(ValueError):
            validate_synthesis_contract(self.contract)

    def test_tcl_quoting_keeps_spaces_but_rejects_interpretation(self):
        self.assertEqual(_tcl_string("/with space/top.cpp"), "{/with space/top.cpp}")
        for text in ("{x}", "a\\b", "x\nexit", "x\rexit"):
            with self.assertRaises(ValueError):
                _tcl_string(text)

    def test_include_tokens_do_not_retain_literal_quotes(self):
        self.assertEqual(_include_flag(Path("/example/include")), "-I/example/include")
        for text in ("/with space", '/with"quote', "/with\\slash"):
            with self.assertRaises(ValueError):
                _include_flag(Path(text))

    def test_preparation_preserves_original_grasu_source_and_full_geometry(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "inputs/grasu/GraSU/GraSU_kernels/src"
            original.mkdir(parents=True)
            (original / "kernel_process_cache.cpp").write_text("unmodified source\n")
            (original / "kernel_config.h").write_text("#define SEGMENT_SIZE 16\n")
            case = root / "case"
            case.mkdir()
            result = prepare_hls_job(self.contract["jobs"][0], self.contract,
                                     root / "inputs", case)
            self.assertEqual((case / "source/kernel_process_cache.cpp").read_bytes(),
                             (original / "kernel_process_cache.cpp").read_bytes())
            tcl = (case / "synthesis.tcl").read_text()
            self.assertIn("set_top process_cache", tcl)
            self.assertIn("create_clock -period 5.0", tcl)
            self.assertNotIn("set_directive", tcl)
            self.assertEqual(len(result["source_files"]), 2)
            self.assertNotIn('"', result["flags"])


class HlsReportTests(unittest.TestCase):
    def test_unknown_latency_repeated_loops_attributes_and_hash_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "top_csynth.xml"
            path.write_text(REPORT)
            row = read_csynth_report(path)
            performance = row["performance"]
            self.assertEqual(performance["SummaryOfOverallLatency"]["Best-caseLatency"], "undef")
            loops = performance["SummaryOfLoopLatency"]["LoopLatency"]
            self.assertEqual(len(loops), 2)
            self.assertEqual(loops[0]["attributes"]["name"], "load")
            self.assertEqual(loops[1]["value"]["PipelineII"], "undef")
            self.assertEqual(len(row["sha256"]), 64)

    def test_missing_top_report_rejects_instead_of_accepting_any_xml(self):
        with tempfile.TemporaryDirectory() as temporary:
            solution = Path(temporary)
            directory = solution / "syn/report"
            directory.mkdir(parents=True)
            with self.assertRaises(ValueError):
                collect_reports(solution, "process_cache")
            (directory / "process_cache_csynth.xml").write_text(REPORT)
            self.assertEqual(len(collect_reports(solution, "process_cache")), 1)
            with self.assertRaises(ValueError):
                collect_reports(solution, "other_top")

    def test_malformed_or_missing_identity_does_not_produce_a_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.xml"
            path.write_text("<profile/>")
            with self.assertRaises(ValueError):
                read_csynth_report(path)

    def test_diagnostics_are_retained_not_silently_waived(self):
        log = "INFO: started\nWARNING: II violation\nERROR: deadlock\nCRITICAL WARNING: memory\n"
        self.assertEqual(len(log_diagnostics(log)), 3)

    def test_interface_width_budget_and_latency_are_read_from_structured_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            solution = Path(temporary)
            directory = solution / "syn/report"
            directory.mkdir(parents=True)
            with self.assertRaises(ValueError):
                collect_interfaces(solution)
            (directory / "csynth.xml").write_text('''<profile>
              <Interface InterfaceName="m_axi_gmem0" type="axi4full" dataWidth="512">
                <busParams><busParam busParamName="NUM_READ_OUTSTANDING">16</busParam></busParams>
                <constraints><constraint latency="64" argName="edges"/></constraints>
              </Interface><Interface InterfaceName="ap_clk" type="clock"/>
              </profile>''')
            interfaces = collect_interfaces(solution)
            self.assertEqual(len(interfaces), 1)
            self.assertEqual(interfaces[0]["attributes"]["dataWidth"], "512")
            self.assertEqual(interfaces[0]["bus_parameters"]["NUM_READ_OUTSTANDING"], "16")
            self.assertEqual(interfaces[0]["constraints"][0]["latency"], "64")


class ScheduleAnalysisTests(unittest.TestCase):
    def test_normalization_changes_only_source_locations_not_numerical_fields(self):
        original = {"SourceLocation": "/scratch/a.hpp:1~/scratch/b.hpp:2",
                    "PipelineII": "3", "unrelated": "/scratch/same_string",
                    "nested": [{"SourceLocation": "/scratch/c.hpp:3"}]}
        normalized = _normalized_locations(original, "/scratch")
        self.assertEqual(normalized["SourceLocation"], "<SOURCE>/a.hpp:1~<SOURCE>/b.hpp:2")
        self.assertEqual(normalized["PipelineII"], "3")
        self.assertEqual(normalized["unrelated"], "/scratch/same_string")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / "report.json").write_text('{"jobs": []}')
            with self.assertRaises(ValueError):
                compare_repetitions(path, path)

    def test_nested_trip_count_ranges_are_not_silently_erased(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "loop.xml"
            path.write_text('''<profile><UserAssignments><TopModelName>reader</TopModelName></UserAssignments>
              <PerformanceEstimates><SummaryOfLoopLatency><readEdges>
                <PipelineII>1</PipelineII><TripCount><range><min>0</min><max>536870911</max></range></TripCount>
              </readEdges></SummaryOfLoopLatency></PerformanceEstimates></profile>''')
            loop = read_loop_schedules(path)[0]
            self.assertEqual(loop["trip_count"], {"range": {"min": "0", "max": "536870911"}})
            self.assertIsNone(loop["depth"])

    def test_failed_and_unstarted_jobs_are_reported_and_contract_tampering_rejects(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "run"
            directory.mkdir()
            contract = json.loads((ROOT / (
                "configs/experiments/grasu_regraph_upstream_synthesis_apply_compat_v3.json")).read_text())
            original = directory / "source_contract.json"
            original.write_text(json.dumps(contract, separators=(",", ":")))
            (directory / "contract.json").write_text(json.dumps(contract, indent=2))
            report = {"evidence_class": contract["evidence_class"],
                      "contract_sha256": sha256_file(original),
                      "jobs": [{"id": "a4_apply", "status": "FAILED", "error": "compiler"}]}
            report_path = directory / "report.json"
            report_path.write_text(json.dumps(report))
            run = analyze_run(directory, original)
            self.assertEqual([row["status"] for row in run["rows"]], ["FAILED", "NOT_RUN"])
            output = directory / "analysis.json"
            study = analyze_study([directory], [original], output)
            self.assertEqual(study["attempts"], 2)
            self.assertIsNone(study["publication_rate_error_pct"])
            with self.assertRaises(ValueError):
                analyze_study([directory], [original], output)
            for jobs in (report["jobs"] * 2, [{"id": "undeclared", "status": "FAILED"}]):
                report["jobs"] = jobs
                report_path.write_text(json.dumps(report))
                with self.assertRaises(ValueError):
                    analyze_run(directory, original)
            original.write_text("{}")
            with self.assertRaises(ValueError):
                analyze_run(directory, original)

    def test_empty_duplicate_or_misaligned_analysis_inputs_reject(self):
        for directories, contracts in (([], []), ([Path("x")], []),
                                        ([Path("a/x"), Path("b/x")], [Path("a"), Path("b")])):
            with self.assertRaises(ValueError):
                analyze_study(directories, contracts, Path("not_created"))


if __name__ == "__main__":
    unittest.main()
