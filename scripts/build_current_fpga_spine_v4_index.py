#!/usr/bin/env python3
"""Build the pinned evidence index for the frozen Spine v4 calibration roles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_current_fpga_components import (  # noqa: E402
    discover_hardware_logs,
)
from scripts.analyze_current_fpga_spine_composed_v4 import (  # noqa: E402
    expected_pairs,
)


DEFAULT_CONTRACT = ROOT / "configs/contracts/current_fpga_spine_composed_cases_v4.json"
DEFAULT_CASES = ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v2.json"
DEFAULT_SIMULATION_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_exact_20260811"
)
DEFAULT_HARDWARE_ROOT = Path(
    "/home/chuxiao/grasu-regraph-integration/docs/evidence/sharded_k4_fullgraph_20260806"
)
DEFAULT_OUTPUT = ROOT / "docs/evidence/current_fpga_spine_composed_index_v4.json"


OLD_DIRECTORY = {
    "weighted_sssp": "weighted_sssp_compacted_hls_v1",
    "connected_components": "connected_components_compacted_hls_v1",
    "thresholded_residual_pagerank": (
        "thresholded_residual_pagerank_compacted_hls_v1"
    ),
}
V4_DIRECTORY = {
    "weighted_sssp": "weighted_sssp_current_fpga_v4",
    "connected_components": "connected_components_current_fpga_v4",
    "thresholded_residual_pagerank": (
        "thresholded_residual_pagerank_current_fpga_v4"
    ),
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_directory(root: Path, dataset: str, algorithm: str) -> Path:
    if dataset in {"au", "su", "wk"}:
        return root / "runs_current_v1" / dataset / "spine" / OLD_DIRECTORY[algorithm]
    if dataset == "r19":
        if algorithm == "connected_components":
            return root / "runs_v4_final" / dataset / "spine" / algorithm
        return root / "runs_current_v1" / dataset / "spine" / OLD_DIRECTORY[algorithm]
    if dataset == "so":
        if algorithm == "connected_components":
            return (
                root
                / "runs_v4_large"
                / dataset
                / "spine"
                / "connected_components_hls_global_promotion_v3"
            )
        legacy_name = (
            "weighted_sssp"
            if algorithm == "weighted_sssp"
            else "thresholded_residual_pagerank"
        )
        return root / "runs_v4_large" / dataset / "spine" / legacy_name
    if dataset == "pk":
        return root / "runs_v4_large" / dataset / "spine" / V4_DIRECTORY[algorithm]
    if dataset in {"lj", "lj08"}:
        return root / "runs_v4_final" / dataset / "spine" / algorithm
    if dataset in {"ask540", "ask904"}:
        return (
            root
            / "runs_v4_final"
            / dataset
            / "spine"
            / "thresholded_residual_pagerank"
        )
    raise ValueError(f"unknown frozen dataset: {dataset}")


def ask_hardware_logs(dataset: str) -> list[Path]:
    edge_tag = "540000" if dataset == "ask540" else "903774"
    root = Path("/data/tmp/chuxiao/matched_fpga_bridge_resident_final_20260806")
    return [
        root
        / f"repeat{repeat}"
        / f"askubuntu{dataset[3:]}k_respr_resident"
        / "spine"
        / "respr"
        / f"dynamic_askubuntu_reciprocal_e{edge_tag}_insert_u8.log"
        for repeat in (1, 2, 3)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--simulation-root", type=Path, default=DEFAULT_SIMULATION_ROOT)
    parser.add_argument("--hardware-root", type=Path, default=DEFAULT_HARDWARE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    contract = read_json(args.contract.resolve())
    cases = read_json(args.cases.resolve())
    rows: list[dict[str, object]] = []
    missing: list[str] = []
    for algorithm, dataset in sorted(expected_pairs(contract)):
        run_dir = run_directory(args.simulation_root.resolve(), dataset, algorithm)
        if dataset.startswith("ask"):
            logs = ask_hardware_logs(dataset)
        else:
            logs = discover_hardware_logs(
                args.hardware_root.resolve(),
                cases["algorithms"][algorithm],
                dataset,
                "spine",
            )
        result = run_dir / "result.json"
        manifest_exists = any(
            (run_dir / name).is_file()
            for name in ("run_manifest.json", "manifest.json", "summary.json")
        )
        if not result.is_file() or not manifest_exists or len(logs) != 3:
            missing.append(f"{algorithm}:{dataset}")
            if args.allow_partial:
                continue
            raise FileNotFoundError(missing[-1])
        rows.append(
            {
                "algorithm": algorithm,
                "dataset": dataset,
                "run_dir": str(run_dir),
                "hardware_logs": [str(path) for path in logs],
            }
        )
    payload = {
        "schema_version": 1,
        "status": "complete" if not missing else "partial",
        "contract_id": contract["contract_id"],
        "rows": rows,
        "missing": missing,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        f"CURRENT_FPGA_SPINE_INDEX_{payload['status'].upper()} "
        f"rows={len(rows)} missing={len(missing)} output={args.output}"
    )
    return 0 if not missing or args.allow_partial else 1


if __name__ == "__main__":
    raise SystemExit(main())
