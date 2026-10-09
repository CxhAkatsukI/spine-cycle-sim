"""Index every synthesis attempt; extract schedules without inventing rates."""

from __future__ import annotations

import json
from pathlib import Path
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from . import hls_preparation, hls_reports
from .hls_preparation import validate_synthesis_contract
from .hls_reports import _fields, collect_interfaces


def read_loop_schedules(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    loops = root.find("PerformanceEstimates/SummaryOfLoopLatency")
    if loops is None:
        return []
    rows = []
    for loop in loops:
        row = {"module": root.findtext("UserAssignments/TopModelName"),
               "loop": loop.get("name", loop.tag)}
        for name, tag in (("II", "PipelineII"), ("depth", "PipelineDepth"),
                          ("trip_count", "TripCount"), ("latency", "Latency")):
            element = loop.find(tag)
            row[name] = (None if element is None else
                         _fields(element)
                         if len(element) else (element.text or "").strip())
        rows.append(row)
    return rows


def analyze_run(directory: Path, source_contract: Path) -> dict:
    report = json.loads((directory / "report.json").read_text())
    contract = json.loads((directory / "contract.json").read_text())
    validate_synthesis_contract(contract)
    if (report.get("evidence_class") != contract["evidence_class"]
            or sha256_file(source_contract) != report.get("contract_sha256")
            or json.loads(source_contract.read_text()) != contract):
        raise ValueError("run identity differs from its declared contract")
    observed = report.get("jobs", [])
    by_id = {row["id"]: row for row in observed}
    declared = {row["id"] for row in contract["jobs"]}
    if len(by_id) != len(observed) or set(by_id) - declared:
        raise ValueError("duplicate or undeclared synthesis results")
    rows = []
    for job in contract["jobs"]:
        observed_row = by_id.get(job["id"], {"status": "NOT_RUN"})
        row = {"id": job["id"], "configuration": job,
               "status": observed_row["status"], "error": observed_row.get("error"),
               "diagnostics": observed_row.get("diagnostics", []),
               "resources": observed_row.get("run"),
               "compatibility": observed_row.get("preparation", {}).get("compatibility", []),
               "top": observed_row.get("preparation", {}).get("top"),
               "loops": [], "interfaces": [], "area": {}}
        if row["status"] == "SYNTHESIZED_NOT_BOARD_VALIDATED":
            solution = directory / job["id"] / "project/solution"
            for item in observed_row["reports"]:
                path = solution / "syn/report" / Path(item["path"]).name
                if sha256_file(path) != item["sha256"]:
                    raise ValueError(f"synthesis report changed: {path}")
                row["loops"].extend(read_loop_schedules(path))
                if item["top"] == row["top"]:
                    row["area"] = item["area"]
            row["interfaces"] = collect_interfaces(solution)
        rows.append(row)
    return {"run": directory.name, "report_sha256": sha256_file(directory / "report.json"),
            "source_contract_sha256": sha256_file(source_contract),
            "frozen_contract_snapshot_sha256": sha256_file(directory / "contract.json"),
            "contract": contract, "rows": rows}


def analyze_study(directories: list[Path], contracts: list[Path], output: Path) -> dict:
    if (not directories or len(directories) != len(contracts)
            or len({path.name for path in directories}) != len(directories)):
        raise ValueError("use a nonempty list of distinct run identities")
    if output.exists():
        raise ValueError("refuse to overwrite a previous analysis")
    runs = [analyze_run(path, contract) for path, contract in zip(directories, contracts)]
    report = {"schema_version": 1, "evidence_class": "upstream_hls_schedule_not_board_timing",
              "analysis_code": [{"path": path.name, "sha256": sha256_file(path)} for path in
                                (Path(__file__), Path(hls_preparation.__file__),
                                 Path(hls_reports.__file__))], "runs": runs,
              "attempts": sum(len(run["rows"]) for run in runs),
              "publication_rate_error_pct": None, "FPGA_measured_cycles": None,
              "not_claimed": ["publication_speed_match", "complete_G_R_cycle_model",
                              "finite_buffer_liveness", "A4_B_integration_overhead"]}
    atomic_write_json(output, report)
    return report


def _normalized_locations(value, source_root: str):
    if isinstance(value, dict):
        return {key: item.replace(source_root, "<SOURCE>")
                if key == "SourceLocation" and isinstance(item, str)
                else _normalized_locations(item, source_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalized_locations(item, source_root) for item in value]
    return value


def compare_repetitions(before: Path, after: Path) -> dict:
    reports = [json.loads((path / "report.json").read_text()) for path in (before, after)]
    rows = [{row["id"]: row for row in report["jobs"]} for report in reports]
    if not rows[0] or set(rows[0]) != set(rows[1]):
        raise ValueError("repeat comparison requires the complete same job matrix")
    comparisons = []
    for name in rows[0]:
        pair = [row[name] for row in rows]
        projections = []
        for path, row in zip((before, after), pair):
            if row["status"] != "SYNTHESIZED_NOT_BOARD_VALIDATED":
                raise ValueError("failed synthesis cannot establish repeat equivalence")
            modules = {item["top"]: {field: item[field] for field in
                                      ("assignments", "performance", "area")}
                       for item in row["reports"]}
            projections.append(_normalized_locations(modules, str(path / name / "source")))
        comparisons.append({
            "id": name, "module_count": len(projections[0]),
            "configuration_exact_equal": pair[0]["configuration"] == pair[1]["configuration"],
            "schedule_area_exact_equal_after_source_location_normalization":
                projections[0] == projections[1],
            "interfaces_exact_equal": pair[0]["interfaces"] == pair[1]["interfaces"],
        })
    return {"before": before.name, "after": after.name, "rows": comparisons,
            "normalization": "only absolute scratch prefixes in SourceLocation fields"}
