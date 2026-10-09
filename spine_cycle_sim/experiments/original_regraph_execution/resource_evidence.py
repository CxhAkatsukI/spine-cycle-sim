"""Inspect instantiated original HLS AXI parameters, not generic RTL defaults."""

from __future__ import annotations

import json
from pathlib import Path
import re

from spine_cycle_sim.experiments.campaign_runtime import sha256_file


def instantiated_parameters(text: str) -> dict[str, list[int]]:
    definitions = {name: int(value) for name, value in re.findall(r"\bparameter\s+(\w+)\s*=\s*(\d+)\s*;", text)}
    parameters = {}
    for name in ("NUM_READ_OUTSTANDING", "NUM_WRITE_OUTSTANDING", "MAX_READ_BURST_LENGTH",
                 "MAX_WRITE_BURST_LENGTH", "C_M_AXI_DATA_WIDTH"):
        values = re.findall(r"\." + name + r"\(\s*(\w+)\s*\)", text)
        if any(not value.isdecimal() and value not in definitions for value in values):
            raise ValueError("unresolved instantiated original AXI parameter")
        parameters[name] = [int(value) if value.isdecimal() else definitions[value] for value in values]
    return parameters


def admit_axi_evidence(root: Path, contract: dict) -> list[dict]:
    analysis = json.loads((root / "docs/experiments/comparisons/grasu_regraph_stage_validation/schedule_analysis.json").read_text())
    runs = {item["run"]: item for item in analysis["runs"]}
    evidence = []
    for item in contract["axi_evidence"]:
        run = root / "results/upstream_stage_controls" / item["run"]
        if sha256_file(run / "report.json") != runs[item["run"]]["report_sha256"]:
            raise ValueError("original HLS scheduling report differs from accepted evidence")
        path = run / item["path"]
        text = path.read_text()
        parameters = instantiated_parameters(text)
        if (parameters["NUM_READ_OUTSTANDING"] != item["read"] or parameters["NUM_WRITE_OUTSTANDING"] != item["write"] or
                parameters["MAX_READ_BURST_LENGTH"] != [16] * len(item["read"]) or
                parameters["MAX_WRITE_BURST_LENGTH"] != [16] * len(item["read"]) or
                parameters["C_M_AXI_DATA_WIDTH"] != [512] * len(item["read"])):
            raise ValueError("original instantiated AXI geometry differs from whole-A4 assumptions")
        evidence.append({"path": str(path), "sha256": sha256_file(path), "parameters": parameters,
                         "hls_report_sha256": runs[item["run"]]["report_sha256"],
                         "scope": "instantiated_interface_capacity_not_measured_memory_latency"})
    return evidence
