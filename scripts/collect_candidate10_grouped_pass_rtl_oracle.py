#!/usr/bin/env python3
"""Collect and verify frozen Candidate-10 grouped-pass RTL cycle evidence."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_candidate10_grouped_pass_rtl_oracle.sh"
XO = Path(
    "/data/feiyang/spine-dynamic-graph-builds/"
    "pipeline_dirty_frontier_publication_1e61fc0_20260725/production/"
    "hls_v5_candidate_10/spine_partconv_rdmaint_kernel.hw.xo"
)
XO_SHA256 = "629e185724467cc14eec4ae14018ff0a89a94aa518ef77499ca6cc2363b28be5"
ORACLE_RE = re.compile(r"\bRTL_ORACLE\s+(?P<fields>.+)$")


@dataclass(frozen=True)
class OracleCase:
    case_id: str
    unique: int
    stride: int
    bitmap: int = 0
    empty: int = 0
    probe: int = 0


CASES = [
    *(OracleCase(f"directory_contiguous_{count}", count, 1) for count in (1, 4, 16, 17, 32, 48, 64, 128, 4096)),
    OracleCase("directory_spread_16", 16, 4),
    OracleCase("directory_spread_64", 64, 4),
    OracleCase("bitmap_probe_spread_16", 16, 128, 1, 0, 1),
    OracleCase("bitmap_probe_spread_64", 64, 128, 1, 0, 1),
    *(OracleCase(f"bitmap_empty_contiguous_{count}", count, 1, 1, 1, 0) for count in (1, 4, 16, 17, 32, 64, 128, 4096)),
    OracleCase("bitmap_empty_spread_16", 16, 128, 1, 1, 0),
    OracleCase("bitmap_empty_spread_64", 64, 128, 1, 1, 0),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def grouped_windows(case: OracleCase) -> list[tuple[int, int]]:
    divisor = 128 if case.bitmap else 4
    windows: list[tuple[int, int]] = []
    sources = 0
    groups = 0
    last_group: int | None = None
    for index in range(case.unique):
        group = (index * case.stride) // divisor
        if group != last_group and groups == 16:
            windows.append((sources, groups))
            sources = 0
            groups = 0
            last_group = None
        if group != last_group:
            groups += 1
            last_group = group
        sources += 1
    windows.append((sources, groups))
    return windows


def formula_cycles(case: OracleCase) -> int:
    total = 0
    empty_fast_path = bool(case.bitmap and case.empty and not case.probe)
    for index, (sources, groups) in enumerate(grouped_windows(case)):
        chunks = math.ceil(sources / 16)
        if empty_fast_path:
            cycles = 156 + 5 * sources + 9 * groups
        else:
            cycles = 229 + 5 * sources + 20 * groups + 2 * sources
        cycles += 72 * (chunks - 1)
        if groups == 16:
            cycles -= 4
        if index != 0:
            cycles -= 3
        total += cycles
    return total


def parse_oracle(output: str) -> dict[str, int]:
    matches = [match for line in output.splitlines() if (match := ORACLE_RE.search(line))]
    if len(matches) != 1:
        raise RuntimeError(f"expected one RTL_ORACLE line, found {len(matches)}")
    fields: dict[str, int] = {}
    for item in matches[0].group("fields").split():
        key, value = item.split("=", 1)
        fields[key] = int(value)
    return fields


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--build-dir", type=Path)
    args = parser.parse_args()

    out_dir = args.out_dir.resolve()
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    build_dir = (
        args.build_dir.resolve()
        if args.build_dir
        else Path(tempfile.mkdtemp(prefix="candidate10_grouped_oracle.", dir="/data/tmp/chuxiao"))
    )
    if sha256(XO) != XO_SHA256:
        raise SystemExit("frozen Candidate-10 XO hash mismatch")

    rows = []
    for index, case in enumerate(CASES):
        snapshot = build_dir / "xsim" / "xsim.dir" / "candidate10_grouped_pass_oracle"
        environment = os.environ.copy()
        environment.update(
            {
                "BUILD_DIR": str(build_dir),
                "CANDIDATE10_XO": str(XO),
                "CANDIDATE10_XO_SHA256": XO_SHA256,
                "CANDIDATE10_ORACLE_REUSE": "1" if index or snapshot.is_dir() else "0",
            }
        )
        command = [
            str(RUNNER),
            f"UNIQUE={case.unique}",
            f"STRIDE={case.stride}",
            f"BITMAP={case.bitmap}",
            f"EMPTY={case.empty}",
            f"PROBE={case.probe}",
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        raw_path = raw_dir / f"{case.case_id}.log"
        raw_path.write_text(completed.stdout, encoding="utf-8")
        if completed.returncode:
            raise RuntimeError(f"RTL oracle failed for {case.case_id}: {raw_path}")
        oracle = parse_oracle(completed.stdout)
        expected = formula_cycles(case)
        windows = grouped_windows(case)
        rows.append(
            {
                **asdict(case),
                "windows": len(windows),
                "groups": sum(groups for _, groups in windows),
                "rtl_cycles": oracle["cycles"],
                "formula_cycles": expected,
                "delta_cycles": oracle["cycles"] - expected,
                "status": "PASS" if oracle["cycles"] == expected else "FAIL",
                "raw_log": str(raw_path.relative_to(out_dir)),
            }
        )
        print(f"{rows[-1]['status']} {case.case_id}: rtl={oracle['cycles']} formula={expected}")

    csv_path = out_dir / "grouped_pass_oracle.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "schema_version": 1,
        "claim": "frozen_candidate10_grouped_pass_rtl_control_oracle",
        "xo": str(XO),
        "xo_sha256": XO_SHA256,
        "collector_sha256": sha256(Path(__file__).resolve()),
        "runner_sha256": sha256(RUNNER),
        "testbench_sha256": sha256(
            ROOT / "scripts" / "rtl" / "candidate10_grouped_pass_tb.sv"
        ),
        "tcl_sha256": sha256(ROOT / "scripts" / "rtl" / "run_all.tcl"),
        "build_dir": str(build_dir),
        "cases": len(rows),
        "all_pass": all(row["status"] == "PASS" for row in rows),
        "formula": {
            "normal": "229 + 5*S + 20*G + 2*E + 72*(ceil(S/16)-1) - full_window*4 - continuation*3",
            "empty_bitmap": "156 + 5*S + 9*G + 72*(ceil(S/16)-1) - full_window*4 - continuation*3",
        },
        "limitations": [
            "The testbench supplies ideal unlimited-outstanding AXI responses.",
            "The result is an HLS RTL control lower bound; SST-HBM models additional memory delay and contention.",
        ],
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0 if manifest["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
