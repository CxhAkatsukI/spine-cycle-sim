"""Audit wrapper pre-request timing without removing explicit write responses."""

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
from . import apply_schedule, elastic_analysis, prefetch_convergence
from .runtime import CACHED_LOCAL

ARMS = ("a4_io16", "prefetch_sssp_response", "prefetch_sssp_write_issue")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]
MASTERS = dict(zip(ARMS, (13, 16, 16)))


def schedule_evidence(solution):
    report = solution / "syn/report/write_out_csynth.xml"
    rtl = solution / "syn/verilog/kernelHBMWrapper_write_out.v"
    metadata = ET.parse(report).getroot()
    loop = metadata.find("PerformanceEstimates/SummaryOfLoopLatency/write_out")
    if (loop is None or loop.findtext("PipelineII") != "1" or
            loop.findtext("PipelineDepth") != "71" or
            metadata.findtext("UserAssignments/TopModelName") != "write_out"):
        raise ValueError("review required: wrapper schedule metadata differs")
    verilog = rtl.read_text()
    stages = {}
    for port in (1, 2):
        for channel, stage in (("AWVALID", 1), ("WVALID", 2), ("BREADY", 70)):
            signal = f"m_axi_gmem{port}_{channel}"
            blocks = re.findall(r"always @ \(\*\) begin\n(.*?)\nend", verilog, re.S)
            matches = [body for body in blocks if signal + " = 1'b1;" in body]
            if len(matches) != 1 or "1'b0 == ap_block_pp0_stage0_11001" not in matches[0]:
                raise ValueError("review required: wrapper RTL handshake differs")
            enables = re.findall(r"ap_enable_reg_pp0_iter(\d+) == 1'b1", matches[0])
            if enables != [str(stage)]:
                raise ValueError("review required: wrapper request/response interval differs")
            stages[signal] = stage
    return dict(files=[pin(p) for p in (report, rtl)],
        tool_version=metadata.findtext("ReportVersion/Version"),
        part=metadata.findtext("UserAssignments/Part"),
        clock_period_ns=metadata.findtext("UserAssignments/TargetClockPeriod"),
        pipeline_ii=1, total_scheduled_depth=71, unstalled_pre_request_cycles=2,
        rtl_enables=stages, explicit_memory_responses_retained=True,
        scope="existing_SSSP_synthesis_boundary_not_cycle_exact_AXI_or_board_calibration")


def freeze(output, reference, solution):
    baseline = json.loads(reference.read_text())
    # Earlier source files may evolve; preserve them in their archive and replay
    # every old observation. Frozen external inputs, binaries and reports cannot.
    external = [p for p in baseline["pins"] if not Path(p["path"]).is_relative_to(ROOT)]
    if (baseline.get("status") != "SSSP_APPLY_CONTROL_COMPLETE_SIMULATOR_PREDICTION" or
            baseline.get("pins_unchanged") is not True or baseline.get("failures") or
            [elastic_analysis.identity(row) for row in baseline["r_rows"]] != apply_schedule.MATRIX or
            not external or any(sha256_file(Path(p["path"])) != p["sha256"] for p in external)):
        raise ValueError("unchanged complete Apply reference artifacts required")
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
    result = dict(status="PRE_SSSP_WRAPPER_CONTROL_FROZEN", reference=pin(reference),
        source_pins=[pin(p) for p in sources], schedule=evidence,
        artifacts=[pin(output / name) for name in ("sources.tar.gz", "pre_edit.diff")],
        git_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        compiler=subprocess.check_output(["g++", "--version"], text=True), baseline_admitted=False)
    atomic_write_json(output / "freeze.json", result)
    return result


def summarize(rows, reference, *, before):
    result = elastic_analysis.summarize(rows, reference, before=before, arms=ARMS,
        before_matrix=apply_schedule.MATRIX, physical_masters=MASTERS,
        reduction_key="cycle_reduction_from_71_pre_request_cycles")
    result["only_control_change"] = "wrapper pre-request latency 71 -> 2; explicit writes/responses and all other resources unchanged"
    return result


def run(output, reference, before, core_reference, cpus):
    frozen = json.loads(before.read_text())
    if (frozen.get("status") != "PRE_SSSP_WRAPPER_CONTROL_FROZEN" or
            frozen["reference"] != pin(reference) or any(
                sha256_file(Path(p["path"])) != p["sha256"] for p in
                frozen["artifacts"] + frozen["schedule"]["files"])):
        raise ValueError("pre-edit reference, source archive or synthesis evidence changed")
    baseline = json.loads(reference.read_text())
    return prefetch_convergence.run(output, core_reference, cpus, matrix=MATRIX,
        analyze=partial(summarize, before=baseline["r_rows"]), extra_references=(before, reference,
            *[Path(p["path"]) for p in frozen["schedule"]["files"] + frozen["artifacts"]]),
        complete_status="SSSP_WRAPPER_CONTROL_COMPLETE_SIMULATOR_PREDICTION",
        cached_reference=core_reference, memory_profile=CACHED_LOCAL, prefetch_checks=True,
        extra_input_checks={"PREFETCH_CAPACITY_TEST": 16})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--solution", type=Path)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--core-reference", type=Path)
    parser.add_argument("--cpus", type=int, nargs="+")
    args = parser.parse_args()
    if args.freeze:
        if args.solution is None: parser.error("--freeze requires --solution")
        result = freeze(args.output.resolve(), args.reference.resolve(), args.solution.resolve())
    else:
        if args.before is None or args.core_reference is None or args.cpus is None:
            parser.error("--before, --core-reference and --cpus required")
        result = run(args.output.resolve(), args.reference.resolve(), args.before.resolve(),
                     args.core_reference.resolve(), args.cpus)
    print(json.dumps({"status": result["status"]}))
