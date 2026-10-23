"""A source-backed Apply interval is an explicit control, not a fitted speed factor."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from spine_cycle_sim.experiments.evaluation_impact.r_bank_stream import apply_schedule as study
from tests.test_regraph_prefetch_capacity import fixture as capacity_fixture


def fixture():
    before, reference, _ = capacity_fixture()
    indexed = {study.elastic_analysis.identity(row): row for row in before}
    rows = []
    for latency, reverse, arm in study.MATRIX:
        row = deepcopy(indexed[(latency, reverse, study.ARMS[1] if arm == study.ARMS[2] else arm)])
        row["arm"] = row["observations"]["result"]["arm"] = arm
        for part in row["observations"]["trajectory"]: part["arm"] = arm
        rows.append(row)
    return rows, reference, before


class ApplyScheduleTests(unittest.TestCase):
    def test_complete_matrix_preserves_old_controls_and_nonadmission(self):
        rows, reference, before = fixture()
        result = study.summarize(rows, reference, before=before)
        self.assertEqual(result["pre_edit_controls_replayed_exactly"], 8)
        self.assertEqual(result["physical_masters"], study.MASTERS)
        self.assertIn("100 -> 1", result["only_control_change"])
        for name in ("production_baseline_admitted", "hardware_timing_admitted",
                     "publication_match_admitted", "strict_resource_match_admitted"):
            self.assertFalse(result[name])

    def test_missing_changed_old_or_order_dependent_rejected(self):
        for mode in ("missing", "old", "order"):
            rows, reference, before = fixture()
            if mode == "missing": rows.pop()
            else: rows[0 if mode == "old" else 2]["observations"]["result"]["cycles"] += 1
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                study.summarize(rows, reference, before=before)

    def test_work_cannot_be_removed_to_pass(self):
        for field in ("read_bytes", "write_bytes", "state", "active"):
            rows, reference, before = fixture()
            for row in rows:
                if row["arm"] != study.ARMS[2]: continue
                if field == "state":
                    for output in row["outputs"]: output["sha256"] = "changed"
                elif field == "active": row["observations"]["trajectory"][0]["active"] += 1
                else: row["observations"]["result"][field] -= 64
            with self.subTest(field=field), self.assertRaises(ValueError):
                study.summarize(rows, reference, before=before)

    def test_schedule_requires_both_response_boundary_and_rtl_enables(self):
        with tempfile.TemporaryDirectory() as directory:
            solution = Path(directory)
            report = solution / "syn/report/Apply_Pipeline_Apply_csynth.xml"
            schedule = solution / ".autopilot/db/Apply_Pipeline_Apply.verbose.sched.rpt"
            rtl = solution / "syn/verilog/kernelApply_Apply_Pipeline_Apply.v"
            for path in (report, schedule, rtl): path.parent.mkdir(parents=True, exist_ok=True)
            report.write_text("""<profile><UserAssignments><TopModelName>Apply_Pipeline_Apply</TopModelName>
                </UserAssignments><PerformanceEstimates><SummaryOfLoopLatency><Apply>
                <PipelineII>1</PipelineII><PipelineDepth>74</PipelineDepth></Apply>
                </SummaryOfLoopLatency></PerformanceEstimates></profile>""")
            schedule.write_text('State 73 <SV = 72> :\n"%vprop = read i512\n'
                                'State 74 <SV = 73> :\n"%write_ln61 = write void @_ssdm_op_Write.axis\n')
            verilog = "\n".join("always @ (*) begin\nif (((1'b0 == ap_block_pp0_stage0_11001) & "
                f"(ap_enable_reg_pp0_iter{stage} == 1'b1))) begin\n{signal} = 1'b1;\nend\nend"
                for signal, stage in (("m_axi_gmem1_RREADY", 72), ("prop_write_burst_stm_TVALID", 73)))
            rtl.write_text(verilog)
            self.assertEqual(study.schedule_evidence(solution)["unstalled_post_response_cycles"], 1)
            rtl.write_text(verilog.replace("iter73", "iter74"))
            with self.assertRaisesRegex(ValueError, "interval"):
                study.schedule_evidence(solution)
            rtl.write_text(verilog)
            schedule.write_text(schedule.read_text().replace("State 73", "State 72"))
            with self.assertRaisesRegex(ValueError, "schedule differs"):
                study.schedule_evidence(solution)


if __name__ == "__main__": unittest.main()
