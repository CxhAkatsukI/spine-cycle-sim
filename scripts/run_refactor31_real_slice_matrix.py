#!/usr/bin/env python3
"""Run the frozen refactor31 real-slice FPGA/simulator transfer matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = (
    ROOT
    / "configs/experiments/spine_refactor31_fpga_calibration_matrix_v2.json"
)
DEFAULT_SLICES = Path(
    "/data/feiyang/codex_builds/spine_paper_alignment/refactor31_real_slices_v2/manifest.json"
)
DEFAULT_PROFILE = (
    ROOT / "configs/architectures/spine_refactor31_routed_native_v1.json"
)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def case_id(row: dict[str, Any]) -> str:
    return f"{row['dataset']}_e{row['target_edges']}"


def run_command(command: list[str], log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write("COMMAND " + " ".join(command) + "\n")
        stream.flush()
        completed = subprocess.run(
            command,
            cwd=ROOT,
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"command failed with rc={completed.returncode}: {log}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--slice-manifest", type=Path, default=DEFAULT_SLICES)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--phase", choices=("fpga", "sim", "both"), default="both")
    parser.add_argument("--cases", nargs="*")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--max-cycles", type=int, default=500_000_000)
    parser.add_argument("--max-rounds", type=int, default=4096)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    if args.repeats <= 0 or args.max_cycles <= 0 or args.max_rounds <= 0:
        raise SystemExit("repeats and cycle/round limits must be positive")

    matrix = json.loads(args.matrix.resolve().read_text(encoding="utf-8"))
    slices = json.loads(args.slice_manifest.resolve().read_text(encoding="utf-8"))
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    selected = None if not args.cases else set(args.cases)
    calibration_ids = {
        dataset["id"] for dataset in matrix["calibration"]["datasets"]
    }
    rows = [row for row in slices["rows"] if row["status"] == "generated"]
    rows.sort(key=lambda row: (row["dataset"], row["target_edges"]))
    rows = [row for row in rows if selected is None or case_id(row) in selected]
    if not rows:
        raise SystemExit("no generated slice rows selected")

    progress: dict[str, Any] = {
        "schema_version": 1,
        "matrix_id": matrix["matrix_id"],
        "phase": args.phase,
        "status": "running",
        "total_cases": len(rows),
        "completed_fpga": [],
        "completed_sim": [],
        "failed": [],
        "current": None,
    }
    progress_path = output / "progress.json"
    if not args.no_resume and progress_path.is_file():
        previous = json.loads(progress_path.read_text(encoding="utf-8"))
        for key in ("completed_fpga", "completed_sim"):
            progress[key] = list(previous.get(key, []))
    write_json(progress_path, progress)

    for row in rows:
        name = case_id(row)
        role = "calibration" if row["dataset"] in calibration_ids else "holdout"
        progress["current"] = {"case": name, "role": role, "phase": None}
        write_json(progress_path, progress)
        try:
            if args.phase in {"fpga", "both"} and name not in progress["completed_fpga"]:
                progress["current"]["phase"] = "fpga"
                write_json(progress_path, progress)
                fpga_dir = output / "fpga" / name
                run_command(
                    [
                        str(ROOT / "scripts/run_refactor31_real_slice_fpga.sh"),
                        row["path"],
                        str(fpga_dir),
                        str(row["source"]),
                        str(args.repeats),
                    ],
                    output / "logs" / f"{name}_fpga.log",
                )
                progress["completed_fpga"].append(name)
                write_json(progress_path, progress)

            if args.phase in {"sim", "both"} and name not in progress["completed_sim"]:
                progress["current"]["phase"] = "sim"
                write_json(progress_path, progress)
                run_command(
                    [
                        sys.executable,
                        str(ROOT / "scripts/run_sst_spine_vertical.py"),
                        "--out-dir",
                        str(output / "sim" / name),
                        "--workload",
                        row["path"],
                        "--profile",
                        str(args.profile.resolve()),
                        "--scenario",
                        "weighted_sssp",
                        "--source",
                        str(row["source"]),
                        "--max-cycles",
                        str(args.max_cycles),
                        "--max-rounds",
                        str(args.max_rounds),
                        "--validation-mode",
                        "generic",
                        "--resident-static-sssp",
                        "--no-build",
                    ],
                    output / "logs" / f"{name}_sim.log",
                )
                progress["completed_sim"].append(name)
                write_json(progress_path, progress)
        except Exception as error:
            progress["failed"].append(
                {"case": name, "phase": progress["current"]["phase"], "error": str(error)}
            )
            progress["status"] = "failed"
            progress["current"] = None
            write_json(progress_path, progress)
            raise

    progress["status"] = "complete"
    progress["current"] = None
    progress["completed_at_unix"] = time.time()
    write_json(progress_path, progress)
    print(
        f"REFACTOR31_REAL_SLICE_CAMPAIGN_PASS cases={len(rows)} "
        f"fpga={len(progress['completed_fpga'])} sim={len(progress['completed_sim'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
