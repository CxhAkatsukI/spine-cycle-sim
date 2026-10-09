"""Read structured HLS estimates without treating unknown latency as zero."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


def _fields(element: ET.Element | None) -> dict:
    if element is None:
        return {}
    fields = {}
    repeated = set()
    for child in element:
        value = _fields(child) if len(child) else (child.text or "").strip()
        if child.attrib:
            value = {"attributes": dict(child.attrib), "value": value}
        if child.tag not in fields:
            fields[child.tag] = value
        elif child.tag in repeated:
            fields[child.tag].append(value)
        else:
            fields[child.tag] = [fields[child.tag], value]
            repeated.add(child.tag)
    return fields


def read_csynth_report(path: Path) -> dict:
    root = ET.parse(path).getroot()
    top = root.findtext("./UserAssignments/TopModelName")
    if not top:
        raise ValueError(f"HLS report has no TopModelName: {path}")
    return {
        "path": str(path), "sha256": sha256_file(path), "top": top,
        "assignments": _fields(root.find("UserAssignments")),
        "performance": _fields(root.find("PerformanceEstimates")),
        "area": _fields(root.find("AreaEstimates")),
    }


def collect_reports(solution: Path, expected_top: str) -> list[dict]:
    report_dir = solution / "syn/report"
    reports = [read_csynth_report(path) for path in sorted(report_dir.glob("*_csynth.xml"))]
    if not reports or not any(row["top"] == expected_top for row in reports):
        raise ValueError(f"missing top-level synthesis report for {expected_top}")
    return reports


def collect_interfaces(solution: Path) -> list[dict]:
    path = solution / "syn/report/csynth.xml"
    if not path.is_file():
        raise ValueError("missing consolidated HLS interface report")
    root = ET.parse(path).getroot()
    return [
        {"attributes": dict(interface.attrib),
         "bus_parameters": {item.attrib["busParamName"]: (item.text or "").strip()
                            for item in interface.findall(".//busParam")},
         "constraints": [dict(item.attrib) for item in interface.findall(".//constraint")]}
        for interface in root.iter("Interface")
        if interface.get("type") in ("axi4full", "axi4stream", "axi4lite")
    ]


def log_diagnostics(log: str) -> list[str]:
    return [line for line in log.splitlines()
            if line.startswith(("WARNING:", "ERROR:", "CRITICAL WARNING:"))]
