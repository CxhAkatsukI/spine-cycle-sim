#!/usr/bin/env python3
"""Close and render the immutable current-FPGA v12 evaluation package."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SIMULATION_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812"
)
DEFAULT_FIG8_EVIDENCE = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_fig8_20260812"
)
DEFAULT_RQ3_PACKAGE = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_rq3_20260812/package"
)
DEFAULT_OUT = ROOT / "docs/evaluation_refresh_20260810"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run(command: list[str]) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def require_status(path: Path, expected: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    payload = read_json(path)
    if payload.get("status") != expected:
        raise ValueError(
            f"evidence gate failed for {path}: "
            f"{payload.get('status')!r} != {expected!r}"
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--simulation-root", type=Path, default=DEFAULT_SIMULATION_ROOT
    )
    parser.add_argument("--fig8-evidence-root", type=Path, default=DEFAULT_FIG8_EVIDENCE)
    parser.add_argument("--rq3-package", type=Path, default=DEFAULT_RQ3_PACKAGE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    out = args.out_dir.resolve()
    simulation_root = args.simulation_root.resolve()
    fig8_evidence = args.fig8_evidence_root.resolve()
    rq3_package = args.rq3_package.resolve()
    frozen_models = out / "calibration_v12_frozen"
    calibration = out / "calibration_v12_analysis"
    fig8_data = out / "fig8_current_v12"
    fig9_data = out / "fig9_current_v12"

    freeze = require_status(
        frozen_models / "calibration_freeze_manifest.json",
        "FROZEN_BEFORE_HOLDOUT",
    )
    if freeze.get("holdout_result_files_present_at_freeze") != []:
        raise ValueError("calibration was not frozen before holdout")

    run(
        [
            args.python,
            str(ROOT / "scripts/analyze_current_fpga_calibration.py"),
            "--simulation-root",
            str(simulation_root),
            "--frozen-models-dir",
            str(frozen_models),
            "--out-dir",
            str(calibration),
        ]
    )
    run(
        [
            args.python,
            str(ROOT / "scripts/analyze_current_fpga_components.py"),
            "--simulation-root",
            str(simulation_root),
            "--frozen-models-dir",
            str(frozen_models),
            "--out-dir",
            str(calibration),
        ]
    )
    calibration_manifests = [
        calibration / "total_cycle_calibration.json",
        calibration / "component_cycle_calibration.json",
        calibration / "memory_ledger_validation.json",
        calibration / "structural_work_validation.json",
    ]
    for path in calibration_manifests:
        payload = require_status(path, "PASS")
        if payload.get("threshold_checks", {}).get("all_pass") is not True:
            raise ValueError(f"threshold gate failed: {path}")

    run(
        [
            args.python,
            str(ROOT / "scripts/export_persistent_update_setup_fig8.py"),
            "--evidence-root",
            str(fig8_evidence),
            "--out-dir",
            str(fig8_data),
            "--batch-count",
            "64",
            "--batch-count",
            "512",
            "--batch-count",
            "4096",
            "--status",
            "PASS_CURRENT_MODEL_DATA",
        ]
    )
    require_status(fig8_data / "persistent_update_setup_manifest.json", "PASS_CURRENT_MODEL_DATA")

    run(
        [
            args.python,
            str(ROOT / "scripts/export_current_fpga_fig9.py"),
            "--simulation-root",
            str(simulation_root),
            "--out-dir",
            str(fig9_data),
        ]
    )
    require_status(fig9_data / "manifest.json", "PASS_CURRENT_MODEL_DATA")

    run(
        [
            args.python,
            str(ROOT / "scripts/build_current_fpga_rq3_v12.py"),
            "--simulation-root",
            str(simulation_root),
            "--out-dir",
            str(rq3_package),
        ]
    )
    require_status(rq3_package / "manifest.json", "PASS")

    run(
        [
            args.python,
            str(ROOT / "scripts/render_evaluation_refresh.py"),
            "--campaign-analysis-dir",
            str(fig9_data),
            "--fig8-data-dir",
            str(fig8_data),
            "--fig10-data-dir",
            str(rq3_package / "analysis"),
            "--out-dir",
            str(out),
        ]
    )
    run(
        [
            args.python,
            str(ROOT / "scripts/audit_evaluation_refresh_alignment.py"),
            "--out-dir",
            str(out),
            "--campaign-analysis-dir",
            str(fig9_data),
            "--calibration-dir",
            str(calibration),
            "--require-ready",
        ]
    )
    alignment = require_status(out / "provenance/alignment_audit.json", "READY")

    evidence_files = [
        frozen_models / "calibration_freeze_manifest.json",
        *calibration_manifests,
        fig8_data / "persistent_update_setup_manifest.json",
        fig9_data / "manifest.json",
        rq3_package / "manifest.json",
        out / "provenance/alignment_audit.json",
    ]
    final_manifest = {
        "schema_version": 1,
        "status": "READY",
        "scope": "current_fpga_v12_fig8_fig9_fig10",
        "simulation_root": str(simulation_root),
        "alignment_status": alignment["status"],
        "evidence": [
            {
                "path": str(path.resolve()),
                "sha256": sha256_file(path),
            }
            for path in evidence_files
        ],
        "figures": [
            str((out / "figures" / name).resolve())
            for name in (
                "fig8_update_throughput_candidate.pdf",
                "fig9_memory_energy_candidate.pdf",
                "fig10_rq3_breakdown_candidate.pdf",
            )
        ],
    }
    final_path = out / "provenance/current_fpga_v12_finalization.json"
    final_path.write_text(
        json.dumps(final_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"CURRENT_FPGA_V12_FINALIZATION_READY manifest={final_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
