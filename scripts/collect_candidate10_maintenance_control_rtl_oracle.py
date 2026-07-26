#!/usr/bin/env python3
"""Measure the frozen Candidate10 zero-edge maintenance RTL control schedule."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run_candidate10_maintenance_control_rtl_oracle.sh"
TESTBENCH = ROOT / "scripts/rtl/candidate10_maintenance_control_tb.sv"
XO = Path(
    "/data/feiyang/spine-dynamic-graph-builds/"
    "pipeline_dirty_frontier_publication_1e61fc0_20260725/production/"
    "hls_v5_candidate_10/spine_partconv_rdmaint_kernel.hw.xo"
)
XO_SHA256 = "629e185724467cc14eec4ae14018ff0a89a94aa518ef77499ca6cc2363b28be5"
RTL_PREFIX = (
    "ip_repo/xilinx_com_hls_spine_partconv_rdmaint_kernel_1_0/hdl/verilog/"
)
TOP_MODULE = "spine_partconv_rdmaint_kernel_partitioned_run_maintenance"
CSYNTH_REPORT = Path(
    "/data/feiyang/spine-dynamic-graph-builds/"
    "pipeline_dirty_frontier_publication_1e61fc0_20260725/production/"
    "hls_v5_candidate_10/reports/spine_partconv_rdmaint_kernel.hw/"
    "hls_reports/spine_partconv_rdmaint_kernel_csynth.rpt"
)
HW_EVIDENCE = ROOT / "docs/evidence/spine_candidate10_hw_20260725/correctness_cases.csv"
SIM_EVIDENCE = (
    ROOT / "results/candidate10_maintenance_control_floor_20260726/"
    "runs/cal_zero/summary.json"
)
SUMMARY_RE = re.compile(r"\bMAINT_CONTROL_RTL\s+(?P<fields>.+)$")
INSTANCE_RE = re.compile(
    r"\b(spine_partconv_rdmaint_kernel_[A-Za-z0-9_$]+)\s+"
    r"(?:#\s*\(|[A-Za-z_][A-Za-z0-9_$]*\s*\()"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_fields(text: str) -> dict[str, int | str]:
    fields: dict[str, int | str] = {}
    for item in text.split():
        key, value = item.split("=", 1)
        try:
            fields[key] = int(value, 0)
        except ValueError:
            fields[key] = value
    return fields


def parse_summary(output: str) -> dict[str, int | str]:
    if "MAINT_CONTROL_RTL_TIMEOUT" in output:
        raise RuntimeError("maintenance-control RTL oracle timed out")
    matches = [
        match
        for line in output.splitlines()
        if (match := SUMMARY_RE.search(line))
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one MAINT_CONTROL_RTL line, found {len(matches)}"
        )
    return parse_fields(matches[0].group("fields"))


def extract_dependency_closure(build_dir: Path) -> tuple[list[str], dict[str, str]]:
    rtl_dir = build_dir / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(XO) as archive:
        members = {
            Path(name).stem: name
            for name in archive.namelist()
            if name.startswith(RTL_PREFIX) and name.endswith(".v")
        }
        missing: set[str] = set()
        selected: dict[str, str] = {}
        pending = [TOP_MODULE]
        while pending:
            module = pending.pop()
            if module in selected:
                continue
            member = members.get(module)
            if member is None:
                missing.add(module)
                continue
            text = archive.read(member).decode("utf-8")
            selected[module] = text
            dependencies = {
                dependency
                for dependency in INSTANCE_RE.findall(text)
                if dependency in members
            }
            for dependency in dependencies:
                if dependency not in selected:
                    pending.append(dependency)
        if missing:
            raise RuntimeError(f"RTL dependency members missing: {sorted(missing)}")
        for stale in rtl_dir.glob("*.v"):
            stale.unlink()
        hashes: dict[str, str] = {}
        for module, text in sorted(selected.items()):
            path = rtl_dir / f"{module}.v"
            path.write_text(text, encoding="utf-8")
            hashes[module] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return sorted(selected), hashes


def csynth_min_cycles() -> int:
    text = CSYNTH_REPORT.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"grp_partitioned_run_maintenance_fu_\d+\s*\|"
        r"partitioned_run_maintenance\s*\|\s*(\d+)",
        text,
    )
    if not match:
        raise RuntimeError("maintenance minimum latency missing from csynth report")
    return int(match.group(1))


def hardware_zero_cycles() -> tuple[float, float]:
    with HW_EVIDENCE.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows = [row for row in rows if row["evidence_case"] == "zero_edge"]
    if len(rows) != 1:
        raise RuntimeError(f"expected one zero_edge hardware row, found {len(rows)}")
    milliseconds = float(rows[0]["maint_ms"])
    return milliseconds, milliseconds * 150_000.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()

    if sha256(XO) != XO_SHA256:
        raise SystemExit("frozen Candidate10 XO hash mismatch")
    build_dir = (
        args.build_dir.resolve()
        if args.build_dir
        else Path(
            tempfile.mkdtemp(
                prefix="candidate10_maintenance_control.",
                dir="/data/tmp/chuxiao",
            )
        )
    )
    modules, module_hashes = extract_dependency_closure(build_dir)
    environment = {
        **os.environ,
        "BUILD_DIR": str(build_dir),
        "CANDIDATE10_ORACLE_REUSE": "1" if args.reuse else "0",
    }
    completed = subprocess.run(
        [str(RUNNER), "MAX_CYCLES=200000"],
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=900,
    )
    raw_path = (
        args.out.resolve().parent
        / f"{args.out.stem}_raw"
        / "zero.log"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(f"maintenance-control RTL oracle failed: {raw_path}")
    rtl = parse_summary(completed.stdout)
    if rtl.get("case") != "zero":
        raise RuntimeError(f"unexpected RTL case: {rtl.get('case')}")
    if any(int(rtl[key]) for key in ("sorter_aw", "sorter_w", "sorter_ar")):
        raise RuntimeError("zero-edge RTL unexpectedly accessed sorted-edge memory")
    if rtl["meta_requested_r"] != rtl["meta_r"]:
        raise RuntimeError("metadata read beat ledger did not close")
    if rtl["meta_requested_w"] != rtl["meta_w"]:
        raise RuntimeError("metadata write beat ledger did not close")
    if rtl["meta_aw"] != rtl["meta_b"]:
        raise RuntimeError("metadata write request/response ledger did not close")
    if rtl["result_requested_w"] != rtl["result_w"]:
        raise RuntimeError("result write beat ledger did not close")
    if rtl["result_aw"] != rtl["result_b"]:
        raise RuntimeError("result write request/response ledger did not close")

    sim = json.loads(SIM_EVIDENCE.read_text(encoding="utf-8"))
    hardware_ms, hardware_cycles = hardware_zero_cycles()
    rtl_cycles = int(rtl["cycles"])
    sim_cycles = int(sim["maintenance_cycles"])
    sim_floor = int(
        sim["maintenance_candidate_zero_edge_control_min_cycles"]
    )
    sim_padding = int(
        sim["maintenance_candidate_zero_edge_control_padding_cycles"]
    )
    sim_overrun = int(
        sim["maintenance_candidate_zero_edge_control_memory_overrun_cycles"]
    )
    if sim_cycles != rtl_cycles or sim_floor != rtl_cycles:
        raise RuntimeError("simulator zero-edge floor diverged from RTL")
    if sim_padding <= 0 or sim_overrun != 0:
        raise RuntimeError("simulator zero-edge floor ledger is inconsistent")
    report = {
        "schema_version": 1,
        "claim": "candidate10_zero_edge_maintenance_control_timing_decomposition",
        "status": "PASS",
        "evidence_tier": "rtl_oracle_plus_measured_hardware",
        "frozen_artifact": {
            "xo": str(XO),
            "xo_sha256": XO_SHA256,
            "top_module": TOP_MODULE,
            "dependency_modules": len(modules),
            "module_names": modules,
            "module_sha256": module_hashes,
            "csynth_report": str(CSYNTH_REPORT),
            "csynth_report_sha256": sha256(CSYNTH_REPORT),
            "csynth_static_min_cycles": csynth_min_cycles(),
        },
        "zero_edge": {
            "rtl_ideal_child_responder": rtl,
            "sst_execution_driven_cycles": sim_cycles,
            "sst_control_floor_cycles": sim_floor,
            "sst_control_floor_padding_cycles": sim_padding,
            "sst_control_floor_memory_overrun_cycles": sim_overrun,
            "hardware_event_ms": hardware_ms,
            "hardware_event_cycles_at_150mhz": hardware_cycles,
            "sst_minus_rtl_cycles": sim_cycles - rtl_cycles,
            "hardware_minus_sst_cycles": hardware_cycles - sim_cycles,
            "hardware_minus_rtl_cycles": hardware_cycles - rtl_cycles,
        },
        "interpretation": {
            "rtl_scope": (
                "partitioned_run_maintenance ap_start-to-ap_done with one-cycle "
                "zero-data HLS child-protocol memory responders"
            ),
            "sst_scope": (
                "execution-driven maintenance through Candidate10 m_axi adapters "
                "and SST/DRAMSim3"
            ),
            "hardware_scope": "XRT CL_PROFILING_COMMAND_START-to-END on routed U55C",
            "not_identified_as_wrapper": (
                "hardware_minus_sst includes shell/interconnect/HBM timing and any "
                "remaining control mismatch; it is not a fitted wrapper constant"
            ),
        },
        "provenance": {
            "runner": str(RUNNER),
            "runner_sha256": sha256(RUNNER),
            "testbench": str(TESTBENCH),
            "testbench_sha256": sha256(TESTBENCH),
            "collector_sha256": sha256(Path(__file__).resolve()),
            "hardware_evidence": str(HW_EVIDENCE),
            "hardware_evidence_sha256": sha256(HW_EVIDENCE),
            "sim_evidence": str(SIM_EVIDENCE),
            "sim_evidence_sha256": sha256(SIM_EVIDENCE),
            "raw_log": str(raw_path),
            "build_dir": str(build_dir),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "PASS candidate10_maintenance_control: "
        f"rtl={rtl_cycles} sim={sim_cycles} hw={hardware_cycles:.1f} cycles "
        f"modules={len(modules)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
