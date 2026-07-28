"""Reproducible vectorless Vivado power-report collection."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Sequence


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _tcl_path(path: Path) -> str:
    return "{" + str(path.resolve()).replace("}", "\\}") + "}"


def render_power_tcl(checkpoint: Path, summary: Path, hierarchy: Path) -> str:
    return "\n".join(
        (
            f"open_checkpoint {_tcl_path(checkpoint)}",
            "set_switching_activity -default_toggle_rate 12.5 "
            "-default_static_probability 0.5",
            f"report_power -file {_tcl_path(summary)}",
            f"report_power -hierarchical -file {_tcl_path(hierarchy)}",
            "close_design",
            "exit",
            "",
        )
    )


def collect_vivado_power(
    *,
    checkpoint: Path,
    out_dir: Path,
    vivado: Path,
    label: str,
    extra_arguments: Sequence[str] = (),
) -> dict[str, object]:
    checkpoint = checkpoint.resolve()
    out_dir = out_dir.resolve()
    vivado = vivado.resolve()
    if not checkpoint.is_file() or not vivado.is_file() or not label:
        raise ValueError("power collection requires a DCP, Vivado, and label")
    out_dir.mkdir(parents=True, exist_ok=True)
    tcl = out_dir / "report_power.tcl"
    summary = out_dir / "power_summary.rpt"
    hierarchy = out_dir / "power_hierarchy.rpt"
    log = out_dir / "vivado_power.log"
    tcl.write_text(
        render_power_tcl(checkpoint, summary, hierarchy), encoding="utf-8"
    )
    command = [
        str(vivado),
        "-mode",
        "batch",
        "-nolog",
        "-nojournal",
        "-source",
        str(tcl),
        *extra_arguments,
    ]
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0 or not summary.is_file() or not hierarchy.is_file():
        raise RuntimeError(f"Vivado power collection failed; see {log}")
    report = {
        "schema_version": 1,
        "status": "PASS",
        "label": label,
        "claim_class": "vivado_vectorless_fpga_power_feasibility_not_workload_energy",
        "checkpoint": {
            "path": str(checkpoint),
            "sha256": sha256_path(checkpoint),
        },
        "vivado": str(vivado),
        "command": command,
        "assumptions": {
            "default_toggle_rate_percent": 12.5,
            "default_static_probability": 0.5,
            "saif_or_vcd_activity": False,
        },
        "outputs": {
            path.name: sha256_path(path) for path in (tcl, summary, hierarchy, log)
        },
        "limitations": [
            "No workload SAIF/VCD activity is applied.",
            "The report supports FPGA implementation and hierarchy feasibility only.",
            "It must not be reported as workload dynamic energy or board power.",
        ],
    }
    (out_dir / "power_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
