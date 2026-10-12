"""Gate nominal schedule predictions against the realized HLS loop and AXI RTL."""

import json
from pathlib import Path
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ..validation import compare_traffic


def loop_schedule(path):
    root = ET.parse(path).getroot()
    loop = root.find("PerformanceEstimates/SummaryOfLoopLatency/read_continuous_sources_loop")
    if loop is None:
        raise ValueError("continuous-reader loop report missing")
    report = {"loop": "read_continuous_sources_loop",
              "achieved_ii": int(loop.findtext("PipelineII")),
              "depth_cycles": int(loop.findtext("PipelineDepth")),
              "target_period_ns": float(root.findtext("UserAssignments/TargetClockPeriod")),
              "estimated_period_ns": float(root.findtext(
                  "PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod"))}
    if (report["achieved_ii"] <= 0 or report["depth_cycles"] <= 0
            or not 0 < report["target_period_ns"] < 100
            or not 0 < report["estimated_period_ns"] < 100):
        raise ValueError("invalid HLS loop estimates")
    return report


def decide(hls, schedule):
    if hls["status"] != "PASS_HLS_AXI_NOT_ROUTED" or hls["hardware_timing_admitted"] is not False:
        raise ValueError("functional HLS evidence required; no FPGA admission")
    if not same_typed(compare_traffic(hls["arms"]["reference"], hls["arms"]["candidate"]),
                      hls["comparison"]):
        raise ValueError("raw RTL comparison differs")
    reference = {row["trial"]: row for row in hls["arms"]["reference"]}
    rows = [{"trial": row["trial"], "reference_cycles": reference[row["trial"]]["cycles"],
             "candidate_cycles": row["cycles"],
             "candidate_over_reference": row["cycles"] / reference[row["trial"]]["cycles"]}
            for row in hls["arms"]["candidate"]]
    reasons = []
    if schedule["achieved_ii"] != 1:
        reasons.append("nominal_II1_schedule_not_realized")
    if schedule["estimated_period_ns"] > schedule["target_period_ns"]:
        reasons.append("estimated_clock_target_not_met")
    if any(row["candidate_cycles"] > row["reference_cycles"] for row in rows):
        reasons.append("synthetic_RTL_regressions")
    return {"status": "REJECTED_CANDIDATE" if reasons else "NEEDS_ROUTE_AND_BOARD",
            "reasons": reasons, "hls_schedule": schedule, "rtl_cases": rows,
            "nominal_prediction_admitted": not reasons, "hardware_timing_admitted": False,
            "default_mode": "unchanged", "production_promotion": False}


def recheck(hls_dir):
    paths = list((hls_dir / "production/build").rglob(
        "read_continuous_row_segments_Pipeline_read_continuous_sources_loop_csynth.xml"))
    if len(paths) != 1:
        raise ValueError("exactly one continuous-reader loop report required")
    return decide(json.loads((hls_dir / "results.json").read_text()), loop_schedule(paths[0]))
