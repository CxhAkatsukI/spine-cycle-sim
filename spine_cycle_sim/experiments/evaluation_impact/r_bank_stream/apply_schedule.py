"""Audit response-anchored SSSP Apply timing, then test full convergence."""

import argparse
from functools import partial
import json
from pathlib import Path
import re
import subprocess
import tarfile
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..r_credits.freeze import ROOT, pin
from . import elastic_analysis, prefetch_capacity, prefetch_convergence

ARMS = ("a4_io16", "prefetch_ready_capacity512", "prefetch_sssp_response")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]
MASTERS = dict(zip(ARMS, (13, 16, 16)))


def schedule_evidence(solution):
    report = solution / "syn/report/Apply_Pipeline_Apply_csynth.xml"
    schedule = solution / ".autopilot/db/Apply_Pipeline_Apply.verbose.sched.rpt"
    rtl = solution / "syn/verilog/kernelApply_Apply_Pipeline_Apply.v"
    metadata = ET.parse(report).getroot()
    loop = metadata.find("PerformanceEstimates/SummaryOfLoopLatency/Apply")
    if (loop is None or loop.findtext("PipelineII") != "1" or
            loop.findtext("PipelineDepth") != "74" or
            metadata.findtext("UserAssignments/TopModelName") != "Apply_Pipeline_Apply"):
        raise ValueError("review required: SSSP Apply schedule metadata differs")
    text = schedule.read_text()
    states = {int(state): body for state, body in re.findall(
        r"^State (\d+) <SV = \d+>.*?\n(.*?)(?=^State |\Z)", text, re.M | re.S)}
    if ('"%vprop = read i512' not in states.get(73, "") or
            '"%write_ln61 = write void @_ssdm_op_Write.axis' not in states.get(74, "")):
        raise ValueError("review required: old-state response/output schedule differs")
    verilog = rtl.read_text()
    stages = {}
    for signal in ("m_axi_gmem1_RREADY", "prop_write_burst_stm_TVALID"):
        match = re.search(
            r"always @ \(\*\) begin\s+if \(\(\(1'b0 == ap_block_pp0_stage0_11001\) & "
            r"\(ap_enable_reg_pp0_iter(\d+) == 1'b1\)\)\) begin\s+" + signal + r" = 1'b1;",
            verilog)
        if not match:
            raise ValueError("review required: response/output RTL enables differ")
        stages[signal] = int(match[1])
    if stages != dict(m_axi_gmem1_RREADY=72, prop_write_burst_stm_TVALID=73):
        raise ValueError("review required: unstalled response-to-output interval differs")
    return dict(files=[pin(p) for p in (report, schedule, rtl)],
        tool_version=metadata.findtext("ReportVersion/Version"),
        part=metadata.findtext("UserAssignments/Part"),
        clock_period_ns=metadata.findtext("UserAssignments/TargetClockPeriod"),
        pipeline_ii=1, total_scheduled_depth=74, unstalled_post_response_cycles=1,
        rtl_enables=stages, scope="existing_integrated_SSSP_synthesis_not_board_calibration")


def freeze(output, reference, solution):
    baseline = json.loads(reference.read_text())
    if (baseline.get("status") != "PREFETCH_CAPACITY_COMPLETE_SIMULATOR_PREDICTION" or
            baseline.get("pins_unchanged") is not True or len(baseline["r_rows"]) != 12 or
            any(sha256_file(Path(p["path"])) != p["sha256"] for p in baseline["pins"])):
        raise ValueError("unchanged complete pre-edit capacity evidence required")
    evidence = schedule_evidence(solution)
    output.mkdir(parents=True, exist_ok=False)
    sources = sorted(p for owner in ("cpp", "spine_cycle_sim", "configs", "tests", "scripts", "sst")
                     for p in (ROOT / owner).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts) + [ROOT / "CMakeLists.txt"]
    with tarfile.open(output / "sources.tar.gz", "w:gz") as archive:
        for source in sources:
            archive.add(source, arcname=source.relative_to(ROOT), recursive=False)
    (output / "pre_edit.diff").write_bytes(subprocess.check_output(
        ["git", "diff", "--binary", "HEAD"], cwd=ROOT))
    result = dict(status="PRE_SSSP_APPLY_CONTROL_FROZEN", reference=pin(reference),
        source_pins=[pin(p) for p in sources], schedule=evidence,
        artifacts=[pin(output / name) for name in ("sources.tar.gz", "pre_edit.diff")],
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        baseline_admitted=False)
    atomic_write_json(output / "freeze.json", result)
    return result


def summarize(rows, reference, *, before):
    result = elastic_analysis.summarize(rows, reference, before=before, arms=ARMS,
        before_matrix=prefetch_capacity.MATRIX, physical_masters=MASTERS,
        reduction_key="cycle_reduction_from_100_post_response_cycles")
    result["only_control_change"] = "Apply post-response latency 100 -> 1; all other resources/timing unchanged"
    return result


def run(output, reference, before, cpus):
    frozen = json.loads(before.read_text())
    if (frozen.get("status") != "PRE_SSSP_APPLY_CONTROL_FROZEN" or
            frozen["reference"] != pin(reference) or any(
                sha256_file(Path(p["path"])) != p["sha256"] for p in
                frozen["artifacts"] + frozen["schedule"]["files"])):
        raise ValueError("pre-edit reference, source archive or synthesis evidence changed")
    baseline = json.loads(reference.read_text())
    return prefetch_convergence.run(output, reference, cpus, matrix=MATRIX,
        analyze=partial(summarize, before=baseline["r_rows"]), extra_references=(before,
            *[Path(p["path"]) for p in frozen["schedule"]["files"] + frozen["artifacts"]]),
        complete_status="SSSP_APPLY_CONTROL_COMPLETE_SIMULATOR_PREDICTION",
        cached_reference=reference, prefetch_checks=True,
        extra_input_checks={"PREFETCH_CAPACITY_TEST": 16})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--solution", type=Path)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--cpus", type=int, nargs="+")
    args = parser.parse_args()
    if args.freeze:
        if args.solution is None: parser.error("--freeze requires --solution")
        result = freeze(args.output.resolve(), args.reference.resolve(), args.solution.resolve())
    else:
        if args.before is None or args.cpus is None: parser.error("--before and --cpus required")
        result = run(args.output.resolve(), args.reference.resolve(), args.before.resolve(), args.cpus)
    print(json.dumps({"status": result["status"]}))
