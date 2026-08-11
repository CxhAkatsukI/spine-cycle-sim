#!/usr/bin/env python3
"""Build the evidence index for the frozen Spine overlap-v6 contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_current_fpga_components import discover_hardware_logs  # noqa: E402


DEFAULT_CONTRACT = ROOT / "configs/contracts/current_fpga_spine_overlap_cases_v6.json"
DEFAULT_CASES = ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v2.json"
DEFAULT_SIMULATION_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_exact_20260811"
)
DEFAULT_HARDWARE_ROOT = Path(
    "/home/chuxiao/grasu-regraph-integration/docs/evidence/sharded_k4_fullgraph_20260806"
)
DEFAULT_V5_HARDWARE_ROOT = Path(
    "/data/tmp/chuxiao/spine_sssp_overlap_v5_holdout_hw_20260811"
)
DEFAULT_V6_HARDWARE_ROOT = Path(
    "/data/tmp/chuxiao/spine_sssp_overlap_v6_holdout_hw_20260811"
)
DEFAULT_OUTPUT = ROOT / "docs/evidence/current_fpga_spine_overlap_index_v6.json"


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def simulator_run_dir(root: Path, dataset: str) -> Path:
    if dataset.endswith("_u512"):
        prefix = "holdout_v6_observability"
    elif dataset.endswith("_u64"):
        prefix = "holdout_v5_observability"
    else:
        prefix = "runs_v5_observability"
    return root / prefix / dataset / "spine" / "weighted_sssp"


def repeated_logs(root: Path, dataset: str) -> list[Path]:
    return sorted(root.glob(f"repeat*/{dataset}/**/*.log"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--simulation-root", type=Path, default=DEFAULT_SIMULATION_ROOT)
    parser.add_argument("--hardware-root", type=Path, default=DEFAULT_HARDWARE_ROOT)
    parser.add_argument("--v5-hardware-root", type=Path, default=DEFAULT_V5_HARDWARE_ROOT)
    parser.add_argument("--v6-hardware-root", type=Path, default=DEFAULT_V6_HARDWARE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    contract = read_json(args.contract.resolve())
    cases = read_json(args.cases.resolve())
    calibration = set(contract["roles"]["calibration"])
    holdout = set(contract["roles"]["holdout"])
    rows: list[dict[str, object]] = []
    missing: list[str] = []
    for dataset in sorted(calibration | holdout):
        run_dir = simulator_run_dir(args.simulation_root.resolve(), dataset)
        if dataset.endswith("_u512"):
            logs = repeated_logs(args.v6_hardware_root.resolve(), dataset)
        elif dataset.endswith("_u64"):
            logs = repeated_logs(args.v5_hardware_root.resolve(), dataset)
        else:
            logs = discover_hardware_logs(
                args.hardware_root.resolve(),
                cases["algorithms"]["weighted_sssp"],
                dataset,
                "spine",
            )
        result_exists = (run_dir / "result.json").is_file()
        manifest_exists = any(
            (run_dir / name).is_file()
            for name in ("run_manifest.json", "manifest.json", "summary.json")
        )
        if not result_exists or not manifest_exists or len(logs) != 3:
            missing.append(dataset)
            if args.allow_partial:
                continue
            raise FileNotFoundError(dataset)
        rows.append(
            {
                "algorithm": "weighted_sssp",
                "dataset": dataset,
                "role": "holdout" if dataset in holdout else "calibration",
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
        f"CURRENT_FPGA_SPINE_OVERLAP_V6_INDEX_{payload['status'].upper()} "
        f"rows={len(rows)} missing={len(missing)} output={args.output}"
    )
    return 0 if not missing or args.allow_partial else 1


if __name__ == "__main__":
    raise SystemExit(main())
