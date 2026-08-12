#!/usr/bin/env python3
"""Assemble the admitted current-FPGA Figure 8--10 review packet."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.render_evaluation_refresh import (  # noqa: E402
    collect_fig9_rows_from_campaign,
    read_csv,
    render_fig8,
    render_fig9,
    write_csv,
)


FIG8_CROSS = "persistent_update_setup_cross_dataset.csv"
FIG8_BATCH = "persistent_update_setup_batch_sensitivity.csv"
FIG8_MANIFEST = "persistent_update_setup_manifest.json"
FIG9_ROWS = "pair_rows.csv"
FIG10_FILES = (
    "admitted_breakdown_rows.csv",
    "mechanism_admission.csv",
    "cost_model_admission.json",
    "fig10_admitted_breakdown.pdf",
    "fig10_admitted_breakdown.png",
    "fig10_realized_work_correlations.pdf",
    "fig10_realized_work_correlations.png",
)


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_status(path: Path, expected: str) -> dict[str, object]:
    manifest = read_json(path)
    status = manifest.get("status")
    if status != expected:
        raise ValueError(f"{path}: expected status {expected}, got {status}")
    return manifest


def copy_with_hash(source: Path, destination: Path) -> dict[str, str]:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return {
        "source": str(source.resolve()),
        "source_sha256": sha256(source),
        "output": str(destination.resolve()),
        "output_sha256": sha256(destination),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fig8-dir", type=Path, required=True)
    parser.add_argument("--fig9-dir", type=Path, required=True)
    parser.add_argument("--fig10-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    fig8 = args.fig8_dir.resolve()
    fig9 = args.fig9_dir.resolve()
    fig10 = args.fig10_dir.resolve()
    output = args.out_dir.resolve()
    data_dir = output / "data"
    figure_dir = output / "figures"
    data_dir.mkdir(parents=True, exist_ok=True)
    figure_dir.mkdir(parents=True, exist_ok=True)

    fig8_manifest_path = fig8 / FIG8_MANIFEST
    fig9_manifest_path = fig9 / "manifest.json"
    fig10_manifest_path = fig10 / "manifest.json"
    require_status(fig8_manifest_path, "PASS_CURRENT_MODEL_DATA")
    require_status(fig9_manifest_path, "PASS_CURRENT_MODEL_DATA")
    fig10_manifest = require_status(
        fig10_manifest_path, "PARTIAL_COMPONENT_CALIBRATION"
    )

    fig8_cross_path = fig8 / FIG8_CROSS
    fig8_batch_path = fig8 / FIG8_BATCH
    cross_rows = read_csv(fig8_cross_path)
    batch_rows = read_csv(fig8_batch_path)
    if len(cross_rows) != 5 or len(batch_rows) != 3:
        raise ValueError("Figure 8 requires five cross-dataset and three batch rows")
    write_csv(data_dir / "fig8_update_cross_dataset.csv", cross_rows)
    write_csv(data_dir / "fig8_update_batch_sensitivity.csv", batch_rows)
    render_fig8(cross_rows, batch_rows, figure_dir / "fig8_update_throughput")

    fig9_rows, fig9_source, fig9_status = collect_fig9_rows_from_campaign(fig9)
    if fig9_status != "PASS_CURRENT_MODEL_DATA" or len(fig9_rows) != 9:
        raise ValueError(
            f"Figure 9 requires nine admitted rows, got {len(fig9_rows)} ({fig9_status})"
        )
    write_csv(data_dir / "fig9_memory_energy_rows.csv", fig9_rows)
    render_fig9(fig9_rows, figure_dir / "fig9_memory_energy")

    copied: dict[str, dict[str, str]] = {}
    for filename in FIG10_FILES:
        destination = data_dir / filename if filename.endswith((".csv", ".json")) else figure_dir / filename
        copied[filename] = copy_with_hash(fig10 / filename, destination)

    inputs = (fig8_manifest_path, fig9_manifest_path, fig10_manifest_path)
    manifest = {
        "schema_version": 1,
        "status": "PASS_WITH_DECLARED_PARTIAL_FIG10",
        "fig8_status": "PASS_CURRENT_MODEL_DATA",
        "fig9_status": "PASS_CURRENT_MODEL_DATA",
        "fig10_status": fig10_manifest["status"],
        "fig10_holdout_status": fig10_manifest.get("whole_machine_holdout_status"),
        "claim_boundary": (
            "Figures 8 and 9 are admitted current-model data. Figure 10 admits "
            "only the component-calibrated breakdown and explicitly reported "
            "mechanism correlations; its global whole-machine cost model is diagnostic."
        ),
        "inputs": [
            {"path": str(path), "sha256": sha256(path)} for path in inputs
        ],
        "fig9_pair_rows": {"path": str(fig9_source), "sha256": sha256(fig9_source)},
        "fig10_copies": copied,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        "CURRENT_FPGA_FIG8_10_PACKET_PASS "
        f"fig8=8 fig9={len(fig9_rows)} fig10={fig10_manifest.get('admitted_breakdown_rows')} "
        f"out={output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
