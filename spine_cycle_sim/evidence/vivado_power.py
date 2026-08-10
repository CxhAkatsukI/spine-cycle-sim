"""Fail-closed parser for Vivado's automatic implementation power report."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping
from typing import Sequence


class VivadoPowerError(ValueError):
    """Raised when a Vivado power log is missing or internally inconsistent."""


def sha256_path(path: Path) -> str:
    """Return a streaming SHA256 for one evidence artifact."""

    return _sha256(path)


def _tcl_path(path: Path) -> str:
    return "{" + str(path.resolve()).replace("}", "\\}") + "}"


def render_power_tcl(checkpoint: Path, summary: Path, hierarchy: Path) -> str:
    """Render the frozen vectorless power flow used when a DCP is retained."""

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
    """Run the frozen power flow when the routed DCP is available."""

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


_SUMMARY_LABELS = {
    "Total On-Chip Power (W)": "total_on_chip_w",
    "FPGA Power (W)": "fpga_w",
    "HBM Power (W)": "hbm_w",
    "Design Power Budget (W)": "design_budget_w",
    "Dynamic (W)": "dynamic_w",
    "Device Static (W)": "device_static_w",
    "Confidence Level": "confidence_level",
    "Simulation Activity File": "simulation_activity_file",
}

_PUBLICATION_COMPONENTS = {
    "hmss_0": "hbm_subsystem",
    "spine_partconv_compute_kernel_1": "compute_kernel",
    "spine_partconv_rdmaint_kernel_1": "reader_maintenance_kernel",
    "buffer_spine_partconv_compute_kernel_1_value_out": "value_stream_buffer",
    "buffer_spine_partconv_rdmaint_kernel_1_edge_out": "edge_stream_buffer",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _summary_value(text: str, label: str) -> str:
    match = re.search(
        rf"^\|\s*{re.escape(label)}\s*\|\s*([^|]+?)\s*\|$",
        text,
        flags=re.MULTILINE,
    )
    if match is None:
        raise VivadoPowerError(f"missing Vivado power field: {label}")
    return match.group(1).strip()


def _float_value(value: str, label: str) -> float:
    match = re.match(r"[-+]?\d+(?:\.\d+)?", value)
    if match is None:
        raise VivadoPowerError(f"non-numeric Vivado power field {label}: {value!r}")
    return float(match.group(0))


def parse_vivado_power_log(
    path: str | Path,
    *,
    required_components: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Parse one completed Vivado report_power invocation and check conservation."""

    log_path = Path(path).resolve()
    if not log_path.is_file():
        raise VivadoPowerError(f"missing Vivado implementation log: {log_path}")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    if "report_power completed successfully" not in text:
        raise VivadoPowerError("Vivado report_power did not complete successfully")

    summary: dict[str, object] = {}
    for label, key in _SUMMARY_LABELS.items():
        raw = _summary_value(text, label)
        summary[key] = (
            raw
            if key in {"confidence_level", "simulation_activity_file"}
            else _float_value(raw, label)
        )

    total = float(summary["total_on_chip_w"])
    if abs(total - float(summary["fpga_w"]) - float(summary["hbm_w"])) > 0.002:
        raise VivadoPowerError("FPGA + HBM power does not conserve total on-chip power")
    if abs(total - float(summary["dynamic_w"]) - float(summary["device_static_w"])) > 0.002:
        raise VivadoPowerError("dynamic + static power does not conserve total on-chip power")

    hierarchy_match = re.search(
        r"3\.1 By Hierarchy\s*-+\s*(?P<table>.*?)\n\+[-+]+\+\s*\n\s*\d+ Infos",
        text,
        flags=re.DOTALL,
    )
    if hierarchy_match is None:
        raise VivadoPowerError("missing Vivado hierarchy power table")
    hierarchy_rows: list[dict[str, object]] = []
    for line in hierarchy_match.group("table").splitlines():
        match = re.match(r"^\|(?P<name>[^|]+)\|\s*(?P<power>\d+(?:\.\d+)?)\s*\|$", line)
        if match is None:
            continue
        raw_name = match.group("name").rstrip()
        if raw_name.strip() == "Name":
            continue
        hierarchy_rows.append(
            {
                "name": raw_name.strip(),
                "indent": len(raw_name) - len(raw_name.lstrip()),
                "power_w": float(match.group("power")),
            }
        )
    if not hierarchy_rows:
        raise VivadoPowerError("empty Vivado hierarchy power table")

    component_rows = []
    by_name = {row["name"]: row for row in hierarchy_rows}
    component_map = (
        _PUBLICATION_COMPONENTS
        if required_components is None
        else dict(required_components)
    )
    for source_name, component in component_map.items():
        if source_name not in by_name:
            raise VivadoPowerError(f"missing hierarchy component: {source_name}")
        component_rows.append(
            {
                "component": component,
                "vivado_hierarchy_name": source_name,
                "power_w": by_name[source_name]["power_w"],
            }
        )

    return {
        "schema_version": 1,
        "claim_class": "vivado_automatic_vectorless_low_confidence_fpga_power",
        "source": {
            "path": str(log_path),
            "sha256": _sha256(log_path),
        },
        "summary": summary,
        "hierarchy": hierarchy_rows,
        "publication_components": component_rows,
        "limitations": [
            "Vivado used default vectorless activity; this is not workload-calibrated energy.",
            "Hierarchy values support implementation feasibility and component attribution only.",
            "Simulator activity and DRAM command accounting remain the workload-energy source.",
        ],
        "status": "PASS",
    }
