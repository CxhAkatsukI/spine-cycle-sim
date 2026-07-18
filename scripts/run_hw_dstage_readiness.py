#!/usr/bin/env python3
"""Run built-in HW D-stage timing matrices."""

from __future__ import annotations

import argparse
import csv
import json
import shlex
import statistics
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.calibration.maintenance import (  # noqa: E402
    DEFAULT_XRT_SETUP,
    KEY_VALUE_RE,
)

DEFAULT_XCLBIN = (
    "/data/feiyang/spine-dynamic-graph-builds/"
    "stream_sparse_carry_cursors_local_20260716_160954/"
    "compact_validation_20260717/hw_134_routed_accepted/xclbin/"
    "spine_partitioned_split_e2e.hw.xclbin"
)
DEFAULT_HOST_EXE = (
    "/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/"
    "host_partitioned_csr_e2e_smoke"
)

BASE_FIELDS = [
    "case",
    "sweep",
    "repeat",
    "returncode",
    "status",
    "stdout_log",
    "stderr_log",
    "command_log",
    "command",
]

SUMMARY_FIELDS = [
    "case",
    "sweep",
    "repeats",
    "successful_repeats",
    "median_conv_ms",
    "min_conv_ms",
    "max_conv_ms",
    "conv_ms_jitter_pct",
    "median_reader_ms",
    "median_conv_span_ms",
    "median_maint_ms",
    "median_kernel_e2e_ms",
]


@dataclass(frozen=True)
class DStageCase:
    case: str
    sweep: str
    args: tuple[str, ...]
    purpose: str


def default_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            case="tiny_default",
            sweep="tiny",
            args=(),
            purpose="Minimal graph; exposes fixed CONV overhead and small-counter path.",
        ),
        DStageCase(
            case="star_e512",
            sweep="single_source_fanout",
            args=("--star", "512"),
            purpose="One active source with moderate fanout across partitions.",
        ),
        DStageCase(
            case="fanout_e4096_s64",
            sweep="multi_source_fanout",
            args=("--fanout", "4096", "64"),
            purpose="Many active sources with a larger edge stream.",
        ),
        DStageCase(
            case="repeat_fanout_e512_b3_s64",
            sweep="multi_batch_level_state",
            args=("--repeat-fanout", "512", "3", "64"),
            purpose="Multiple update batches before CONV; checks level-state exposure.",
        ),
        DStageCase(
            case="fallback_forced",
            sweep="full_path_tile",
            args=("--fallback-forced",),
            purpose="Forces the non-tiny tile path and broader tile scheduling counters.",
        ),
    ]


def phase3a1_calibration_matrix() -> list[DStageCase]:
    return [
        DStageCase("calib_tiny_default", "tiny", (), "Small fixed-overhead case."),
        DStageCase(
            "calib_sparse_wide",
            "tiny_wide_tiles",
            ("--sparse-wide",),
            "Few edges touching distant tiles.",
        ),
        DStageCase(
            "calib_star_e128",
            "single_source_fanout",
            ("--star", "128"),
            "Single active source, small fanout.",
        ),
        DStageCase(
            "calib_star_e512",
            "single_source_fanout",
            ("--star", "512"),
            "Single active source, medium fanout.",
        ),
        DStageCase(
            "calib_star_e2048",
            "single_source_fanout",
            ("--star", "2048"),
            "Single active source, larger fanout.",
        ),
        DStageCase(
            "calib_fanout_e1024_s16",
            "multi_source_fanout",
            ("--fanout", "1024", "16"),
            "Moderate edge stream with limited active sources.",
        ),
        DStageCase(
            "calib_fanout_e4096_s64",
            "multi_source_fanout",
            ("--fanout", "4096", "64"),
            "Larger edge stream with many active records.",
        ),
        DStageCase(
            "calib_fanout_e8192_s128",
            "multi_source_fanout",
            ("--fanout", "8192", "128"),
            "Large fast-tile path case.",
        ),
        DStageCase(
            "calib_repeat_fanout_e256_b2_s32",
            "multi_batch_level_state",
            ("--repeat-fanout", "256", "2", "32"),
            "Two batches creating L1 state before CONV.",
        ),
        DStageCase(
            "calib_repeat_fanout_e512_b3_s64",
            "multi_batch_level_state",
            ("--repeat-fanout", "512", "3", "64"),
            "Three batches with mixed L0/L1 state.",
        ),
        DStageCase(
            "calib_repeat_star_e1024_b2",
            "repeat_single_source",
            ("--repeat-star", "1024", "2"),
            "Repeated single-source fanout batches.",
        ),
        DStageCase(
            "calib_fallback_forced",
            "full_path_tile",
            ("--fallback-forced",),
            "Full tile path dominated by vertex-state sweep.",
        ),
    ]


def phase3a1_holdout_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "holdout_star_e256",
            "single_source_fanout",
            ("--star", "256"),
            "Unseen single-source fanout.",
        ),
        DStageCase(
            "holdout_star_e1024",
            "single_source_fanout",
            ("--star", "1024"),
            "Unseen medium single-source fanout.",
        ),
        DStageCase(
            "holdout_star_onepart_e512",
            "one_partition_fanout",
            ("--star-onepart", "512"),
            "Unseen one-partition destination fanout.",
        ),
        DStageCase(
            "holdout_fanout_e2048_s32",
            "multi_source_fanout",
            ("--fanout", "2048", "32"),
            "Unseen fast-tile multi-source case.",
        ),
        DStageCase(
            "holdout_fanout_e6144_s96",
            "multi_source_fanout",
            ("--fanout", "6144", "96"),
            "Unseen larger fast-tile case.",
        ),
        DStageCase(
            "holdout_repeat_fanout_e256_b4_s32",
            "multi_batch_level_state",
            ("--repeat-fanout", "256", "4", "32"),
            "Unseen four-batch level-state case.",
        ),
        DStageCase(
            "holdout_repeat_fanout_e1024_b2_s128",
            "multi_batch_level_state",
            ("--repeat-fanout", "1024", "2", "128"),
            "Unseen repeated fanout with more active sources.",
        ),
        DStageCase(
            "holdout_repeat_star_dense_e512_b2",
            "repeat_single_source",
            ("--repeat-star-dense", "512", "2"),
            "Unseen dense repeated star with destination local_start at zero.",
        ),
    ]


def phase3a1_final_holdout_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "final_star_e384",
            "single_source_fanout",
            ("--star", "384"),
            "Final unseen single-source fanout.",
        ),
        DStageCase(
            "final_star_e1536",
            "single_source_fanout",
            ("--star", "1536"),
            "Final unseen larger single-source fanout.",
        ),
        DStageCase(
            "final_star_onepart_e1024",
            "one_partition_fanout",
            ("--star-onepart", "1024"),
            "Final unseen one-partition destination fanout.",
        ),
        DStageCase(
            "final_fanout_e3072_s48",
            "multi_source_fanout",
            ("--fanout", "3072", "48"),
            "Final unseen multi-source fanout.",
        ),
        DStageCase(
            "final_fanout_e7168_s112",
            "multi_source_fanout",
            ("--fanout", "7168", "112"),
            "Final unseen larger multi-source fanout.",
        ),
        DStageCase(
            "final_repeat_fanout_e384_b3_s48",
            "multi_batch_level_state",
            ("--repeat-fanout", "384", "3", "48"),
            "Final unseen three-batch level-state case.",
        ),
        DStageCase(
            "final_repeat_fanout_e768_b2_s96",
            "multi_batch_level_state",
            ("--repeat-fanout", "768", "2", "96"),
            "Final unseen two-batch level-state case.",
        ),
        DStageCase(
            "final_repeat_star_dense_e768_b2",
            "repeat_single_source",
            ("--repeat-star-dense", "768", "2"),
            "Final unseen dense repeated star case.",
        ),
    ]


def matrix_by_name(name: str) -> list[DStageCase]:
    if name == "phase3a0_readiness":
        return default_matrix()
    if name == "phase3a1_calibration":
        return phase3a1_calibration_matrix()
    if name == "phase3a1_holdout":
        return phase3a1_holdout_matrix()
    if name == "phase3a1_final_holdout":
        return phase3a1_final_holdout_matrix()
    raise ValueError(f"unknown D-stage matrix: {name}")


def parse_scalar(value: str) -> int | float | str:
    if value in {"PASS", "FAIL"}:
        return value
    try:
        return int(value, 0)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def parse_stdout(stdout: str) -> dict[str, Any]:
    final_line = ""
    for line in stdout.splitlines():
        if line.startswith("PARTITIONED_CSR_E2E_SMOKE "):
            final_line = line
    if not final_line:
        return {"status": "MISSING"}
    parts = final_line.split()
    row: dict[str, Any] = {"status": parts[1] if len(parts) > 1 else "UNKNOWN"}
    for key, value in KEY_VALUE_RE.findall(final_line):
        row[key] = parse_scalar(value)
    return row


def build_command(
    case: DStageCase,
    host_exe: Path,
    xclbin: Path,
    timeout_s: int,
    xrt_setup: Path | None,
    split_kernels: bool,
) -> str:
    invocation = [
        str(host_exe),
        str(xclbin),
        *case.args,
        "--timeout",
        str(timeout_s),
    ]
    parts: list[str] = []
    if xrt_setup:
        parts.append(f"source {shlex.quote(str(xrt_setup))}")
    parts.append("unset XCL_EMULATION_MODE")
    if split_kernels:
        parts.append("export SPINE_PARTITIONED_SPLIT=1")
    parts.append(" ".join(shlex.quote(value) for value in invocation))
    return " && ".join(parts)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], preferred: list[str]) -> None:
    keys = set(preferred)
    for row in rows:
        keys.update(row.keys())
    fieldnames = preferred + sorted(keys.difference(preferred))
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def median_or_blank(values: list[float]) -> float | str:
    if not values:
        return ""
    return statistics.median(values)


def jitter_pct(values: list[float]) -> float | str:
    if len(values) < 2:
        return ""
    med = statistics.median(values)
    if med == 0:
        return ""
    return (max(values) - min(values)) / med * 100.0


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["case"]), []).append(row)

    summary: list[dict[str, Any]] = []
    for case, group in grouped.items():
        ok = [row for row in group if row.get("status") == "PASS" and row.get("returncode") == 0]
        out: dict[str, Any] = {
            "case": case,
            "sweep": group[0]["sweep"],
            "repeats": len(group),
            "successful_repeats": len(ok),
        }
        for key in ["conv_ms", "reader_ms", "conv_span_ms", "maint_ms", "kernel_e2e_ms"]:
            values = [
                float(row[key])
                for row in ok
                if key in row and isinstance(row[key], (int, float))
            ]
            out[f"median_{key}"] = median_or_blank(values)
            if key == "conv_ms" and values:
                out["min_conv_ms"] = min(values)
                out["max_conv_ms"] = max(values)
                out["conv_ms_jitter_pct"] = jitter_pct(values)
        for key in [
            "vertices",
            "batches",
            "input_edges",
            "persisted",
            "active_sources",
            "active_records",
            "next_active",
            "traversed_edges",
            "touched_tiles",
            "fast_path_tiles",
            "full_path_tiles",
            "gathered_vertex_words",
            "swept_vertex_words",
            "scattered_vertex_words",
        ]:
            values = [row.get(key) for row in ok if key in row]
            if values:
                out[f"median_{key}"] = statistics.median(float(value) for value in values)
        summary.append(out)
    return summary


def run_case(
    case: DStageCase,
    repeat: int,
    host_exe: Path,
    xclbin: Path,
    timeout_s: int,
    xrt_setup: Path | None,
    split_kernels: bool,
    out_dir: Path,
) -> dict[str, Any]:
    raw_dir = out_dir / "raw" / case.case
    raw_dir.mkdir(parents=True, exist_ok=True)
    command = build_command(
        case,
        host_exe=host_exe,
        xclbin=xclbin,
        timeout_s=timeout_s,
        xrt_setup=xrt_setup,
        split_kernels=split_kernels,
    )
    completed = subprocess.run(
        ["bash", "-lc", command],
        cwd=str(host_exe.resolve().parent),
        text=True,
        capture_output=True,
        timeout=timeout_s + 120,
        check=False,
    )
    stdout_path = raw_dir / f"run_{repeat}.stdout"
    stderr_path = raw_dir / f"run_{repeat}.stderr"
    command_path = raw_dir / f"run_{repeat}.command.sh"
    stdout_path.write_text(completed.stdout)
    stderr_path.write_text(completed.stderr)
    command_path.write_text(command + "\n")

    row = {
        "case": case.case,
        "sweep": case.sweep,
        "repeat": repeat,
        "returncode": completed.returncode,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "command_log": str(command_path),
        "command": command,
    }
    parsed = parse_stdout(completed.stdout)
    if "case" in parsed:
        parsed["host_case"] = parsed.pop("case")
    row.update(parsed)
    if completed.returncode != 0 and row.get("status") == "MISSING":
        row["status"] = "FAIL"
    return row


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host-exe", type=Path, default=Path(DEFAULT_HOST_EXE))
    parser.add_argument("--xclbin", type=Path, default=Path(DEFAULT_XCLBIN))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--xrt-setup", type=Path, default=Path(DEFAULT_XRT_SETUP))
    parser.add_argument("--no-xrt-setup", action="store_true")
    parser.add_argument("--no-split-kernels", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--matrix",
        choices=[
            "phase3a0_readiness",
            "phase3a1_calibration",
            "phase3a1_holdout",
            "phase3a1_final_holdout",
        ],
        default="phase3a0_readiness",
        help="Select the built-in D-stage experiment matrix.",
    )
    parser.add_argument("--only-case", action="append", help="Limit to one or more case ids.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repeats <= 0:
        raise SystemExit("--repeats must be positive")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    cases = matrix_by_name(args.matrix)
    if args.only_case:
        allowed = set(args.only_case)
        cases = [case for case in cases if case.case in allowed]
    if not cases:
        raise SystemExit("selected matrix is empty")

    xrt_setup = None if args.no_xrt_setup else args.xrt_setup
    split_kernels = not args.no_split_kernels
    write_json(
        args.out_dir / "matrix.json",
        {
            "host_exe": str(args.host_exe),
            "xclbin": str(args.xclbin),
            "repeats": args.repeats,
            "timeout_s": args.timeout,
            "xrt_setup": str(xrt_setup) if xrt_setup else "",
            "split_kernels": split_kernels,
            "matrix": args.matrix,
            "cases": [asdict(case) for case in cases],
        },
    )

    commands = [
        build_command(
            case,
            host_exe=args.host_exe,
            xclbin=args.xclbin,
            timeout_s=args.timeout,
            xrt_setup=xrt_setup,
            split_kernels=split_kernels,
        )
        for case in cases
    ]
    (args.out_dir / "commands.sh").write_text("\n".join(commands) + "\n")
    if args.dry_run:
        print(f"cases={len(cases)} repeats={args.repeats} total_runs={len(cases) * args.repeats}")
        return 0

    rows: list[dict[str, Any]] = []
    for case in cases:
        for repeat in range(1, args.repeats + 1):
            print(f"[{case.case}] repeat {repeat}/{args.repeats}", flush=True)
            row = run_case(
                case,
                repeat=repeat,
                host_exe=args.host_exe,
                xclbin=args.xclbin,
                timeout_s=args.timeout,
                xrt_setup=xrt_setup,
                split_kernels=split_kernels,
                out_dir=args.out_dir,
            )
            rows.append(row)
            print(
                "  status={status} returncode={returncode} conv_ms={conv_ms} "
                "reader_ms={reader_ms} traversed_edges={traversed_edges}".format(
                    status=row.get("status"),
                    returncode=row.get("returncode"),
                    conv_ms=row.get("conv_ms", ""),
                    reader_ms=row.get("reader_ms", ""),
                    traversed_edges=row.get("traversed_edges", ""),
                ),
                flush=True,
            )

    write_csv(args.out_dir / "runs.csv", rows, BASE_FIELDS)
    write_csv(args.out_dir / "summary.csv", aggregate(rows), SUMMARY_FIELDS)
    print(f"wrote runs: {args.out_dir / 'runs.csv'}")
    print(f"wrote summary: {args.out_dir / 'summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
