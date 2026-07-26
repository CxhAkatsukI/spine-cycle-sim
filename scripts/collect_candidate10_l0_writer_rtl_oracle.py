#!/usr/bin/env python3
"""Collect and verify frozen Candidate-10 L0-writer RTL timing evidence."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_candidate10_l0_writer_rtl_oracle.sh"
TESTBENCH = ROOT / "scripts" / "rtl" / "candidate10_l0_writer_tb.sv"
XO = Path(
    "/data/feiyang/spine-dynamic-graph-builds/"
    "pipeline_dirty_frontier_publication_1e61fc0_20260725/production/"
    "hls_v5_candidate_10/spine_partconv_rdmaint_kernel.hw.xo"
)
XO_SHA256 = "629e185724467cc14eec4ae14018ff0a89a94aa518ef77499ca6cc2363b28be5"
HLS_SOURCE_ROOT = XO.parent / "audit" / "source"
HLS_SOURCE_SHA256 = {
    "common_types.hpp": "9a818b0b27101e568dc86c098e92437ffc0b9520da126a7933e15001ba9d2042",
    "spine_partitioned.hpp": "d98fb04cb59c3b00b894ba4d615d7dd1a6250f46fe1d998a951bb0a0843c7dbc",
}
RTL_PREFIX = "ip_repo/xilinx_com_hls_spine_partconv_rdmaint_kernel_1_0/hdl/verilog"
RTL_ORACLE_MEMBERS = {
    "kernel_top": f"{RTL_PREFIX}/spine_partconv_rdmaint_kernel.v",
    "graph_axi_adapter": f"{RTL_PREFIX}/spine_partconv_rdmaint_kernel_gmem_p0_m_axi.v",
    "writer": f"{RTL_PREFIX}/spine_partconv_rdmaint_kernel_partitioned_write_l0_family.v",
    "writer_loop": f"{RTL_PREFIX}/spine_partconv_rdmaint_kernel_partitioned_write_l0_family_Pipeline_PARTITIONED_WRITE_L0_EDGES.v",
}
ORACLE_RE = re.compile(r"\bL0_WRITER_RTL\s+(?P<fields>.+)$")


@dataclass(frozen=True)
class OracleCase:
    case_id: str
    inputs: int
    edges: int
    rows: int
    pattern: int
    source_stride: int = 1
    stall_period: int = 0
    stall_width: int = 0
    expect_family_local_contract_failure: bool = False


CASES = [
    *(OracleCase(f"same_source_{count}", count, count, 1, 0)
      for count in (1, 2, 3, 4, 5, 15, 16, 17, 128, 1024)),
    *(OracleCase(f"dense_sources_{count}", count, count, count, 1)
      for count in (2, 3, 4, 5, 15, 16, 17, 128)),
    *(OracleCase(f"page_sources_{count}", count, count, count, 1, 256)
      for count in (2, 3, 4, 5, 15, 16, 17)),
    OracleCase("duplicate_pairs_4", 4, 2, 2, 2),
    OracleCase("duplicate_pairs_16", 16, 8, 8, 2),
    OracleCase("four_per_source_4", 4, 4, 1, 4),
    OracleCase("four_per_source_8", 8, 8, 2, 4),
    OracleCase("four_per_source_12", 12, 12, 3, 4),
    OracleCase("four_per_source_16", 16, 16, 4, 4),
    OracleCase("four_per_source_20", 20, 20, 5, 4),
    OracleCase("family_local_contract_violation_4", 4, 2, 2, 3, 1, 0, 0, True),
    OracleCase("family_local_contract_violation_16", 16, 8, 8, 3, 1, 0, 0, True),
    OracleCase("same_source_16_backpressure_5_2", 16, 16, 1, 0, 1, 5, 2),
    OracleCase("page_sources_16_backpressure_8_4", 16, 16, 16, 1, 256, 8, 4),
]


def add_derived_metrics(rows: list[dict[str, object]]) -> None:
    """Add layer-explicit byte and schedule metrics to parsed RTL rows."""
    by_case = {str(row["case_id"]): row for row in rows}
    for row in rows:
        inputs = int(row["inputs"])
        cycles = int(row["cycles"])
        row["writer_loop_ii_cycles"] = 24 * inputs
        row["writer_control_residual_cycles"] = cycles - 24 * inputs
        row["sorter_child_read_bytes"] = int(row["sorter_requested_r_beats"]) * 16
        row["graph_child_write_bytes"] = int(row["graph_requested_w_beats"]) * 8
        row["metadata_child_read_bytes"] = int(row["meta_requested_r_beats"]) * 8
        row["metadata_child_write_bytes"] = int(row["meta_requested_w_beats"]) * 8

        case_id = str(row["case_id"])
        if int(row["stall_period"]) == 0:
            row["ideal_case_id"] = ""
            row["backpressure_delta_cycles"] = ""
            row["backpressure_slowdown"] = ""
            continue
        ideal_id = re.sub(r"_backpressure_\d+_\d+$", "", case_id)
        ideal = by_case.get(ideal_id)
        if ideal is None:
            row["ideal_case_id"] = ""
            row["backpressure_delta_cycles"] = ""
            row["backpressure_slowdown"] = ""
            continue
        ideal_cycles = int(ideal["cycles"])
        row["ideal_case_id"] = ideal_id
        row["backpressure_delta_cycles"] = cycles - ideal_cycles
        row["backpressure_slowdown"] = round(cycles / ideal_cycles, 9)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frozen_source_manifest() -> dict[str, object]:
    source_hashes = {
        name: sha256(HLS_SOURCE_ROOT / name) for name in HLS_SOURCE_SHA256
    }
    if source_hashes != HLS_SOURCE_SHA256:
        raise RuntimeError("frozen Candidate-10 HLS source hash mismatch")
    with zipfile.ZipFile(XO) as archive:
        rtl_hashes = {
            role: hashlib.sha256(archive.read(member)).hexdigest()
            for role, member in RTL_ORACLE_MEMBERS.items()
        }
    return {
        "hls_source_root": str(HLS_SOURCE_ROOT),
        "hls_source_sha256": source_hashes,
        "xo_rtl_members": RTL_ORACLE_MEMBERS,
        "xo_rtl_sha256": rtl_hashes,
    }


def parse_oracle(output: str) -> dict[str, int]:
    matches = [match for line in output.splitlines()
               if (match := ORACLE_RE.search(line))]
    if len(matches) != 1:
        raise RuntimeError(f"expected one L0_WRITER_RTL line, found {len(matches)}")
    fields: dict[str, int] = {}
    for item in matches[0].group("fields").split():
        key, value = item.split("=", 1)
        fields[key] = int(value)
    return fields


def validate_oracle(case: OracleCase, oracle: dict[str, int]) -> list[str]:
    failures: list[str] = []
    result_edges = case.inputs if case.expect_family_local_contract_failure else case.edges
    result_rows = case.inputs if case.expect_family_local_contract_failure else case.rows
    result_error = 1 if case.expect_family_local_contract_failure else 0
    expected = {
        "inputs": case.inputs,
        "edges": case.edges,
        "rows": case.rows,
        "pattern": case.pattern,
        "source_stride": case.source_stride,
        "stall_period": case.stall_period,
        "stall_width": case.stall_width,
        "result_edges": result_edges,
        "result_rows": result_rows,
        "result_overflow": result_error,
        "result_validation": result_error,
        "result_outputs": result_edges,
        "sorter_ar": case.inputs,
        "sorter_r": case.inputs,
        "sorter_requested_r_beats": case.inputs,
    }
    for key, value in expected.items():
        if oracle.get(key) != value:
            failures.append(f"{key}: expected {value}, got {oracle.get(key)}")
    if oracle.get("graph_requested_w_beats") != oracle.get("graph_w"):
        failures.append("graph requested/write beat mismatch")
    if oracle.get("meta_requested_w_beats") != oracle.get("meta_w"):
        failures.append("metadata requested/write beat mismatch")
    if oracle.get("graph_b", 0) > oracle.get("graph_aw", 0):
        failures.append("graph responses exceed requests")
    if oracle.get("meta_b", 0) > oracle.get("meta_aw", 0):
        failures.append("metadata responses exceed requests")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path)
    args = parser.parse_args()

    out_dir = args.out_dir.resolve()
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for stale_log in raw_dir.glob("*.log"):
        stale_log.unlink()
    build_dir = (
        args.build_dir.resolve()
        if args.build_dir
        else Path(tempfile.mkdtemp(
            prefix="candidate10_l0_writer_oracle.", dir="/data/tmp/chuxiao"))
    )
    if sha256(XO) != XO_SHA256:
        raise SystemExit("frozen Candidate-10 XO hash mismatch")
    frozen_sources = frozen_source_manifest()

    rows: list[dict[str, object]] = []
    for index, case in enumerate(CASES):
        snapshot = build_dir / "xsim" / "xsim.dir" / "candidate10_l0_writer_oracle"
        environment = os.environ.copy()
        environment.update(
            {
                "BUILD_DIR": str(build_dir),
                "CANDIDATE10_XO": str(XO),
                "CANDIDATE10_XO_SHA256": XO_SHA256,
                "CANDIDATE10_ORACLE_REUSE": (
                    "1" if index or snapshot.is_dir() else "0"
                ),
            }
        )
        command = [
            str(RUNNER),
            f"INPUTS={case.inputs}",
            f"EDGES={case.edges}",
            f"ROWS={case.rows}",
            f"PATTERN={case.pattern}",
            f"SOURCE_STRIDE={case.source_stride}",
            f"STALL_PERIOD={case.stall_period}",
            f"STALL_WIDTH={case.stall_width}",
            "MAX_CYCLES=2000000",
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=180,
        )
        raw_path = raw_dir / f"{case.case_id}.log"
        raw_path.write_text(completed.stdout, encoding="utf-8")
        if completed.returncode:
            raise RuntimeError(f"RTL oracle failed for {case.case_id}: {raw_path}")
        oracle = parse_oracle(completed.stdout)
        failures = validate_oracle(case, oracle)
        row: dict[str, object] = {
            **asdict(case),
            **oracle,
            "status": "PASS" if not failures else "FAIL",
            "failures": "; ".join(failures),
            "raw_log": str(raw_path.relative_to(out_dir)),
        }
        rows.append(row)
        print(f"{row['status']} {case.case_id}: cycles={oracle['cycles']}"
              + (f" ({row['failures']})" if failures else ""), flush=True)

    add_derived_metrics(rows)

    csv_path = out_dir / "l0_writer_oracle.csv"
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "schema_version": 2,
        "claim": "frozen_candidate10_l0_writer_rtl_control_and_internal_request_oracle",
        "xo": str(XO),
        "xo_sha256": XO_SHA256,
        **frozen_sources,
        "collector_sha256": sha256(Path(__file__).resolve()),
        "runner_sha256": sha256(RUNNER),
        "testbench_sha256": sha256(TESTBENCH),
        "tcl_sha256": sha256(ROOT / "scripts" / "rtl" / "run_all.tcl"),
        "build_dir": str(build_dir),
        "cases": len(rows),
        "all_pass": all(row["status"] == "PASS" for row in rows),
        "protocol": {
            "address_unit": "port_data_words, converted to bytes by the kernel-level m_axi adapter",
            "request_length": "actual beats, not external AXI AxLEN minus one encoding",
            "write_response": "one internal B response per accepted AW request",
            "family_local": "the Candidate10 writer trusts upstream family buckets and detects count mismatches at final validation",
        },
        "derived_metrics": {
            "writer_loop_ii_cycles": "24 * inputs; the synthesized edge-loop throughput term",
            "writer_control_residual_cycles": "observed cycles - writer_loop_ii_cycles; includes fill, drain, final flush, and deterministic child-protocol waits",
            "child_request_bytes": "requested beats multiplied by the corresponding child port width; not an assertion about final HBM traffic",
            "backpressure_delta_cycles": "periodically stalled run minus the matching ideal run",
        },
        "limitations": [
            "This oracle isolates the HLS child writer with deterministic response timing.",
            "It observes child-to-adapter requests, not final U55C HBM AXI transactions.",
            "Periodic stalls are deterministic protocol sensitivity tests, not an HBM model.",
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if manifest["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
