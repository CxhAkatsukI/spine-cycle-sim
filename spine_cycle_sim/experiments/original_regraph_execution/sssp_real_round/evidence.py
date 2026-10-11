"""Pin the local synthesis evidence without claiming board calibration."""

from pathlib import Path
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


def apply_schedule(solution: Path) -> dict:
    files = [solution / ".autopilot/db/Apply_Pipeline_Apply.verbose.sched.rpt",
             solution / "syn/report/Apply_Pipeline_Apply_csynth.xml",
             solution / "impl/ip/hdl/verilog/kernelApply_Apply_Pipeline_Apply.v",
             solution.parent.parent / "kernelApply.tcl"]
    report = ET.parse(files[1]).getroot()
    loop = report.find("PerformanceEstimates/SummaryOfLoopLatency/Apply")
    if (loop is None or loop.findtext("PipelineII") != "1" or loop.findtext("PipelineDepth") != "74"
            or report.findtext("UserAssignments/TopModelName") != "Apply_Pipeline_Apply"):
        raise ValueError("local SSSP Apply schedule metadata changed; review RTL before admission")
    return {"files": [{"path": str(path), "sha256": sha256_file(path)} for path in files],
            "tool_version": report.findtext("ReportVersion/Version"),
            "part": report.findtext("UserAssignments/Part"),
            "target_clock_period_ns": report.findtext("UserAssignments/TargetClockPeriod"),
            "pipeline_ii": 1, "pipeline_depth_including_AXI_read": 74,
            "reviewed_unstalled_response_to_output_cycles": 1,
            "schedule_locations": ["state 73 / SV72: old-state AXI read",
                                   "state 74 / SV73: SSSP compare and output writes"],
            "scope": "local_one_little_one_big_300MHz_synthesis_not_A4_150MHz_board_calibration"}
