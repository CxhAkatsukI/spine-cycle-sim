"""The wrapper control changes request timing, never traffic or completion work."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import wrapper_schedule as study
from tests.test_regraph_apply_schedule import fixture as apply_fixture


def fixture():
    before, reference, _ = apply_fixture()
    indexed = {study.elastic_analysis.identity(row): row for row in before}
    rows = []
    for latency, reverse, arm in study.MATRIX:
        row = deepcopy(indexed[(latency, reverse, study.ARMS[1] if arm == study.ARMS[2] else arm)])
        row["arm"] = row["observations"]["result"]["arm"] = arm
        for part in row["observations"]["trajectory"]: part["arm"] = arm
        rows.append(row)
    return rows, reference, before


class WrapperScheduleTests(unittest.TestCase):
    def test_complete_matrix_replays_old_controls_and_does_not_admit_baseline(self):
        rows, reference, before = fixture()
        result = study.summarize(rows, reference, before=before)
        self.assertEqual(result["pre_edit_controls_replayed_exactly"], 8)
        self.assertEqual(result["physical_masters"], study.MASTERS)
        self.assertIn("71 -> 2", result["only_control_change"])
        for name in ("production_baseline_admitted", "hardware_timing_admitted",
                     "publication_match_admitted", "strict_resource_match_admitted"):
            self.assertFalse(result[name])

    def test_missing_old_drift_or_registration_dependence_is_rejected(self):
        for mode in ("missing", "old", "order"):
            rows, reference, before = fixture()
            if mode == "missing": rows.pop()
            else: rows[0 if mode == "old" else 2]["observations"]["result"]["cycles"] += 1
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                study.summarize(rows, reference, before=before)

    def test_write_read_state_active_or_convergence_work_cannot_be_removed(self):
        for field in ("read_bytes", "write_bytes", "state", "active", "convergence"):
            rows, reference, before = fixture()
            for row in rows:
                if row["arm"] != study.ARMS[2]: continue
                if field == "state":
                    for output in row["outputs"]: output["sha256"] = "changed"
                elif field == "active": row["observations"]["trajectory"][0]["active"] += 1
                elif field == "convergence": row["observations"]["trajectory"][-1]["active"] = 1
                else: row["observations"]["result"][field] -= 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                study.summarize(rows, reference, before=before)

    def test_both_physical_ports_require_address_data_and_response_schedule(self):
        with tempfile.TemporaryDirectory() as directory:
            solution = Path(directory)
            report = solution / "syn/report/write_out_csynth.xml"
            rtl = solution / "syn/verilog/kernelHBMWrapper_write_out.v"
            for path in (report, rtl): path.parent.mkdir(parents=True, exist_ok=True)
            metadata = """<profile><UserAssignments><TopModelName>write_out</TopModelName>
                </UserAssignments><PerformanceEstimates><SummaryOfLoopLatency><write_out>
                <PipelineII>1</PipelineII><PipelineDepth>71</PipelineDepth></write_out>
                </SummaryOfLoopLatency></PerformanceEstimates></profile>"""
            report.write_text(metadata)
            verilog = "\n".join("always @ (*) begin\nif (((1'b0 == ap_block_pp0_stage0_11001) & "
                f"(ap_enable_reg_pp0_iter{stage} == 1'b1))) begin\nm_axi_gmem{port}_{channel} = 1'b1;\nend\nend"
                for port in (1, 2) for channel, stage in (("AWVALID", 1), ("WVALID", 2), ("BREADY", 70)))
            rtl.write_text(verilog)
            evidence = study.schedule_evidence(solution)
            self.assertEqual(evidence["unstalled_pre_request_cycles"], 2)
            self.assertTrue(evidence["explicit_memory_responses_retained"])
            self.assertEqual(len(evidence["rtl_enables"]), 6)
            for signal in evidence["rtl_enables"]:
                rtl.write_text(verilog.replace(signal + " = 1'b1;", signal + " = 1'b0;"))
                with self.subTest(signal=signal), self.assertRaisesRegex(ValueError, "handshake"):
                    study.schedule_evidence(solution)
            rtl.write_text(verilog.replace("iter70", "iter69"))
            with self.assertRaisesRegex(ValueError, "interval"):
                study.schedule_evidence(solution)
            rtl.write_text(verilog)
            report.write_text(metadata.replace("<PipelineDepth>71", "<PipelineDepth>70"))
            with self.assertRaisesRegex(ValueError, "metadata"):
                study.schedule_evidence(solution)


if __name__ == "__main__": unittest.main()
