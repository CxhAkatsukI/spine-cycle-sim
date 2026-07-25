"""Parse and validate routed Vitis/Vivado FPGA evidence.

The parsers consume either plain text or gzip-compressed reports. They keep
requested-clock timing separate from packaged xclbin clocks so an auto-scaled
build cannot be mislabeled as closing its original timing constraint.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import re
from typing import Any


RESOURCE_KEYS = ("lut", "lut_as_mem", "reg", "bram", "uram", "dsp")
TIMING_KEYS = (
    "wns_ns",
    "tns_ns",
    "setup_failing_endpoints",
    "setup_total_endpoints",
    "whs_ns",
    "ths_ns",
    "hold_failing_endpoints",
    "hold_total_endpoints",
    "wpws_ns",
    "tpws_ns",
    "pulse_width_failing_endpoints",
    "pulse_width_total_endpoints",
)
_FLOAT_RE = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_RESOURCE_RE = re.compile(
    rf"^\s*(?P<count>\d+)\s+\[\s*(?P<bound><?)(?P<pct>{_FLOAT_RE})%\]\s*$"
)


class FpgaEvidenceError(ValueError):
    """Raised when a report or evidence manifest is incomplete or inconsistent."""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_report(path: str | Path) -> tuple[str, dict[str, Any]]:
    """Read a plain/gzip report and return text plus archive/content identity."""

    report_path = Path(path)
    archive = report_path.read_bytes()
    content = gzip.decompress(archive) if report_path.suffix == ".gz" else archive
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FpgaEvidenceError(f"report is not UTF-8 text: {report_path}") from exc
    return text, {
        "path": str(report_path),
        "archive_sha256": _sha256(archive),
        "content_sha256": _sha256(content),
        "archive_bytes": len(archive),
        "content_bytes": len(content),
        "compression": "gzip" if report_path.suffix == ".gz" else "none",
    }


def _header_metadata(text: str) -> dict[str, str]:
    fields = {
        "tool_version": "Tool Version",
        "date": "Date",
        "host": "Host",
        "command": "Command",
        "design": "Design",
        "device": "Device",
        "design_state": "Design State",
    }
    metadata: dict[str, str] = {}
    for output_name, report_name in fields.items():
        match = re.search(
            rf"^\|\s*{re.escape(report_name)}\s*:\s*(.*?)\s*$",
            text,
            re.MULTILINE,
        )
        if match:
            metadata[output_name] = match.group(1)
    return metadata


def _parse_resource_cell(cell: str) -> dict[str, Any]:
    match = _RESOURCE_RE.match(cell)
    if not match:
        raise FpgaEvidenceError(f"invalid utilization cell: {cell!r}")
    return {
        "count": int(match.group("count")),
        "user_budget_pct": float(match.group("pct")),
        "percent_is_upper_bound": match.group("bound") == "<",
    }


def parse_accelerator_utilization(text: str) -> dict[str, Any]:
    """Parse report_accelerator_utilization's system utilization table."""

    if "Accelerator Utilization Design Information" not in text:
        raise FpgaEvidenceError("not an accelerator utilization report")

    rows: list[dict[str, Any]] = []
    table_seen = False
    for line in text.splitlines():
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = line.split("|")[1:-1]
        if len(cells) != 7:
            continue
        if cells[0].strip() == "Name":
            table_seen = True
            continue
        if not table_seen:
            continue
        try:
            resources = {
                key: _parse_resource_cell(cell)
                for key, cell in zip(RESOURCE_KEYS, cells[1:], strict=True)
            }
        except FpgaEvidenceError:
            continue
        raw_name = cells[0]
        rows.append(
            {
                "name": raw_name.strip(),
                "indent": len(raw_name) - len(raw_name.lstrip()),
                "resources": resources,
            }
        )

    if not rows:
        raise FpgaEvidenceError("utilization report has no resource rows")
    by_name = {row["name"]: row for row in rows}
    required = ("Platform", "User Budget", "Used Resources", "Unused Resources")
    missing = [name for name in required if name not in by_name]
    if missing:
        raise FpgaEvidenceError(
            f"utilization report is missing {', '.join(missing)}"
        )

    system_names = set(required)
    component_indent = min(
        row["indent"] for row in rows if row["name"] not in system_names
    )
    components = [
        row
        for row in rows
        if row["name"] not in system_names and row["indent"] == component_indent
    ]
    instances = [
        row
        for row in rows
        if row["name"] not in system_names and row["indent"] > component_indent
    ]
    return {
        "metadata": _header_metadata(text),
        "used_resources": by_name["Used Resources"]["resources"],
        "user_budget": by_name["User Budget"]["resources"],
        "platform": by_name["Platform"]["resources"],
        "components": components,
        "instances": instances,
        "rows": rows,
    }


def _timing_values(tokens: list[str], context: str) -> dict[str, int | float]:
    if len(tokens) != len(TIMING_KEYS):
        raise FpgaEvidenceError(f"{context} has {len(tokens)} timing fields")
    try:
        values: list[int | float] = [
            float(token) if index in (0, 1, 4, 5, 8, 9) else int(token)
            for index, token in enumerate(tokens)
        ]
    except ValueError as exc:
        raise FpgaEvidenceError(f"invalid numeric field in {context}") from exc
    return dict(zip(TIMING_KEYS, values, strict=True))


def _section(text: str, start: str, end: str | None = None) -> str:
    start_at = text.find(start)
    if start_at < 0:
        raise FpgaEvidenceError(f"report section not found: {start}")
    if end is None:
        return text[start_at:]
    end_at = text.find(end, start_at + len(start))
    return text[start_at:] if end_at < 0 else text[start_at:end_at]


def parse_timing_summary(text: str, kernel_clock_name: str) -> dict[str, Any]:
    """Parse global and kernel-clock setup/hold timing from a routed report."""

    design_section = _section(text, "| Design Timing Summary", "| Clock Summary")
    summary: dict[str, int | float] | None = None
    for line in design_section.splitlines():
        tokens = line.split()
        if len(tokens) != len(TIMING_KEYS):
            continue
        try:
            summary = _timing_values(tokens, "design timing summary")
            break
        except FpgaEvidenceError:
            continue
    if summary is None:
        raise FpgaEvidenceError("design timing summary values not found")

    met_phrase = "All user specified timing constraints are met."
    failed_phrase = "Timing constraints are not met."
    if met_phrase in design_section:
        constraints_met = True
    elif failed_phrase in design_section:
        constraints_met = False
    else:
        raise FpgaEvidenceError("timing constraint disposition not found")

    clock_section = _section(text, "| Clock Summary", "| Intra Clock Table")
    clock_re = re.compile(
        rf"^\s*{re.escape(kernel_clock_name)}\s+\{{[^}}]+\}}\s+"
        rf"(?P<period>{_FLOAT_RE})\s+(?P<frequency>{_FLOAT_RE})\s*$",
        re.MULTILINE,
    )
    clock_match = clock_re.search(clock_section)
    if not clock_match:
        raise FpgaEvidenceError(f"clock summary lacks {kernel_clock_name}")

    intra_section = _section(text, "| Intra Clock Table", "| Inter Clock Table")
    clock_timing: dict[str, int | float] | None = None
    for line in intra_section.splitlines():
        tokens = line.split()
        if not tokens or tokens[0] != kernel_clock_name:
            continue
        clock_timing = _timing_values(tokens[1:], f"intra-clock {kernel_clock_name}")
        break
    if clock_timing is None:
        raise FpgaEvidenceError(f"intra-clock timing lacks {kernel_clock_name}")

    return {
        "metadata": _header_metadata(text),
        "constraints_met_at_requested_clock": constraints_met,
        "design_summary": summary,
        "kernel_clock": {
            "name": kernel_clock_name,
            "period_ns": float(clock_match.group("period")),
            "requested_mhz": float(clock_match.group("frequency")),
            "timing": clock_timing,
        },
    }


def parse_xclbin_info(text: str, system_clock_name: str) -> dict[str, Any]:
    """Parse packaged and achieved clocks from xclbinutil --info output."""

    platform_match = re.search(r"^\s*Platform VBNV:\s*(\S+)\s*$", text, re.MULTILINE)
    if not platform_match:
        raise FpgaEvidenceError("xclbin info lacks Platform VBNV")

    scalable_section = _section(text, "Scalable Clocks", "System Clocks")
    scalable_re = re.compile(
        rf"^\s*Name:\s*(?P<name>\S+)\s*$.*?"
        rf"^\s*Type:\s*(?P<type>\S+)\s*$.*?"
        rf"^\s*Frequency:\s*(?P<frequency>{_FLOAT_RE})\s*MHz\s*$",
        re.MULTILINE | re.DOTALL,
    )
    scalable = {
        match.group("name"): {
            "type": match.group("type"),
            "frequency_mhz": float(match.group("frequency")),
        }
        for match in scalable_re.finditer(scalable_section)
    }
    if "DATA_CLK" not in scalable:
        raise FpgaEvidenceError("xclbin info lacks packaged DATA_CLK")

    system_section = _section(text, "System Clocks", "Generated By")
    system_re = re.compile(
        rf"^\s*Name:\s*(?P<name>\S+)\s*$.*?"
        rf"^\s*Type:\s*(?P<type>\S+)\s*$.*?"
        rf"^\s*Default Freq:\s*(?P<default>{_FLOAT_RE})\s*MHz\s*$.*?"
        rf"^\s*Requested Freq:\s*(?P<requested>{_FLOAT_RE})\s*MHz\s*$.*?"
        rf"^\s*Achieved Freq:\s*(?P<achieved>{_FLOAT_RE})\s*MHz\s*$",
        re.MULTILINE | re.DOTALL,
    )
    system = {
        match.group("name"): {
            "type": match.group("type"),
            "default_mhz": float(match.group("default")),
            "requested_mhz": float(match.group("requested")),
            "achieved_mhz": float(match.group("achieved")),
        }
        for match in system_re.finditer(system_section)
    }
    if system_clock_name not in system:
        raise FpgaEvidenceError(f"xclbin info lacks system clock {system_clock_name}")
    return {
        "platform_vbnv": platform_match.group(1),
        "packaged_clocks": scalable,
        "system_clocks": system,
        "data_clock": {
            **system[system_clock_name],
            "name": system_clock_name,
            "packaged_mhz": scalable["DATA_CLK"]["frequency_mhz"],
        },
    }


def _resolve(root: Path, path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def _validated_report(
    root: Path, report: dict[str, Any], kind: str
) -> tuple[str, dict[str, Any]]:
    required = {"path", "archive_sha256", "content_sha256"}
    if not isinstance(report, dict) or set(report) != required:
        raise FpgaEvidenceError(f"{kind} report fields must be {sorted(required)}")
    text, identity = read_report(_resolve(root, report["path"]))
    for field in ("archive_sha256", "content_sha256"):
        if identity[field] != report[field]:
            raise FpgaEvidenceError(
                f"{kind} {field} mismatch: expected {report[field]}, "
                f"got {identity[field]}"
            )
    identity["path"] = report["path"]
    return text, identity


def _timing_disposition(timing: dict[str, Any], xclbin: dict[str, Any]) -> str:
    data_clock = xclbin["data_clock"]
    requested = data_clock["requested_mhz"]
    achieved = data_clock["achieved_mhz"]
    packaged = data_clock["packaged_mhz"]
    if abs(timing["kernel_clock"]["requested_mhz"] - requested) > 0.01:
        raise FpgaEvidenceError("timing and xclbin requested clocks disagree")
    if timing["constraints_met_at_requested_clock"]:
        if packaged > achieved + 0.01:
            raise FpgaEvidenceError("packaged clock exceeds achieved clock")
        return "requested_clock_closed"
    if packaged < requested and packaged <= achieved + 0.01:
        return "packaged_after_auto_scaling"
    return "timing_not_closed_at_packaged_clock"


def analyze_fpga_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Validate a frozen report manifest and produce a machine-readable ledger."""

    path = Path(manifest_path)
    manifest_bytes = path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise FpgaEvidenceError(f"invalid FPGA evidence manifest: {path}") from exc
    if manifest.get("schema_version") != 1:
        raise FpgaEvidenceError("only FPGA evidence schema_version=1 is supported")
    if manifest.get("claim_class") != "fpga_routed_measured_native_non_normalized":
        raise FpgaEvidenceError("unsafe or unsupported FPGA claim class")
    repository_root = manifest.get("repository_root")
    if not isinstance(repository_root, str) or not repository_root:
        raise FpgaEvidenceError("FPGA evidence manifest lacks repository_root")
    builds = manifest.get("builds")
    if not isinstance(builds, list) or not builds:
        raise FpgaEvidenceError("FPGA evidence manifest has no builds")

    root = (path.resolve().parent / repository_root).resolve()
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for build in builds:
        build_id = build.get("build_id")
        if not isinstance(build_id, str) or not build_id or build_id in seen:
            raise FpgaEvidenceError(f"invalid or duplicate build_id: {build_id!r}")
        seen.add(build_id)
        reports = build.get("reports")
        if not isinstance(reports, dict) or set(reports) != {
            "utilization",
            "timing",
            "xclbin_info",
        }:
            raise FpgaEvidenceError(f"{build_id}: incomplete report set")

        utilization_text, utilization_id = _validated_report(
            root, reports["utilization"], f"{build_id}.utilization"
        )
        timing_text, timing_id = _validated_report(
            root, reports["timing"], f"{build_id}.timing"
        )
        xclbin_text, xclbin_id = _validated_report(
            root, reports["xclbin_info"], f"{build_id}.xclbin_info"
        )
        utilization = parse_accelerator_utilization(utilization_text)
        timing = parse_timing_summary(timing_text, build["kernel_clock_name"])
        xclbin = parse_xclbin_info(xclbin_text, build["system_clock_name"])

        metadata_pairs = (
            (
                utilization["metadata"],
                "utilization",
                build["expected_utilization_design_state"],
            ),
            (
                timing["metadata"],
                "timing",
                build["expected_timing_design_state"],
            ),
        )
        for metadata, kind, expected_state in metadata_pairs:
            if metadata.get("design_state") != expected_state:
                raise FpgaEvidenceError(
                    f"{build_id}: {kind} design state mismatch; "
                    f"expected {expected_state}, got {metadata.get('design_state')}"
                )
            if build["tool_version"] not in metadata.get("tool_version", ""):
                raise FpgaEvidenceError(f"{build_id}: {kind} tool version mismatch")
        if xclbin["platform_vbnv"] != build["platform_vbnv"]:
            raise FpgaEvidenceError(f"{build_id}: platform mismatch")

        disposition = _timing_disposition(timing, xclbin)
        if disposition != build["expected_timing_disposition"]:
            raise FpgaEvidenceError(
                f"{build_id}: expected {build['expected_timing_disposition']}, "
                f"observed {disposition}"
            )
        results.append(
            {
                "build_id": build_id,
                "system": build["system"],
                "role": build["role"],
                "claim_label": build["claim_label"],
                "source": build["source"],
                "limitations": build["limitations"],
                "timing_disposition": disposition,
                "utilization": utilization,
                "timing": timing,
                "xclbin": xclbin,
                "report_identity": {
                    "utilization": utilization_id,
                    "timing": timing_id,
                    "xclbin_info": xclbin_id,
                },
            }
        )

    comparison_ids = manifest.get("comparison_build_ids")
    if not isinstance(comparison_ids, list) or len(comparison_ids) != 2:
        raise FpgaEvidenceError("comparison_build_ids must name exactly two builds")
    by_id = {build["build_id"]: build for build in results}
    if any(build_id not in by_id for build_id in comparison_ids):
        raise FpgaEvidenceError("comparison references an unknown build")
    first, second = (by_id[build_id] for build_id in comparison_ids)
    resource_comparison = {}
    for resource in RESOURCE_KEYS:
        first_count = first["utilization"]["used_resources"][resource]["count"]
        second_count = second["utilization"]["used_resources"][resource]["count"]
        resource_comparison[resource] = {
            first["system"]: first_count,
            second["system"]: second_count,
            "first_minus_second": first_count - second_count,
            "first_over_second": (
                first_count / second_count if second_count != 0 else None
            ),
        }

    try:
        manifest_display = str(path.resolve().relative_to(root))
    except ValueError:
        manifest_display = str(path.resolve())
    return {
        "schema_version": 1,
        "claim_class": manifest["claim_class"],
        "manifest": manifest_display,
        "manifest_sha256": _sha256(manifest_bytes),
        "comparison_build_ids": comparison_ids,
        "resource_comparison": resource_comparison,
        "builds": results,
        "limitations": manifest["limitations"],
        "status": "PASS",
    }
