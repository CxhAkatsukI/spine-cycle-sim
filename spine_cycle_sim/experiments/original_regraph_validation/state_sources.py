"""Admit pinned original Apply/writer captures without borrowing timing claims."""

from __future__ import annotations

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.upstream_controls.validation import validate_probe
from .analysis import same_typed


def admit_apply(directory: Path, root: Path, contract: dict) -> list[dict]:
    report_path = directory / "report.json"
    report = json.loads(report_path.read_text())
    canonical = root / "configs/experiments/regraph_upstream_apply_v1.json"
    source_contract = json.loads(canonical.read_text())
    pins = root / "docs/experiments/comparisons/grasu_regraph_stage_validation/source_pins.json"
    if (report.get("all_functional_probes_passed") is not True or
            report.get("evidence_class") != "upstream_source_functional_only" or
            report.get("device_cycles") is not None or
            report.get("contract_sha256") != sha256_file(canonical) or
            report.get("pins_sha256") != sha256_file(pins) or
            not same_typed(json.loads((directory / "contract.json").read_text()), source_contract)):
        raise ValueError("Apply capture requires the fixed passing original-source control")
    current_code = sorted((root / "spine_cycle_sim/experiments/upstream_controls").glob("*.py"))
    current_code.append(root / "scripts/run_upstream_stage_controls.py")
    expected_code = [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)}
                     for path in current_code]
    if not same_typed(report.get("analysis_code"), expected_code):
        raise ValueError("Apply source-control code identity changed")
    rows = report.get("probes", [])
    if [row.get("id") for row in rows] != [row["id"] for row in contract["source_controls"]]:
        raise ValueError("Apply capture matrix missing, reordered or duplicated")
    admitted = []
    for row, source, expected in zip(rows, source_contract["probes"], contract["source_controls"], strict=True):
        if (row.get("status") != "FUNCTIONAL_PASS_NOT_TIMING" or
                not same_typed(row.get("observed"), source["expected"]) or
                not same_typed(row.get("expected"), source["expected"]) or
                row["run"]["exit_code"] != 0 or row["run"]["timed_out"]):
            raise ValueError("Apply source-functional boundary changed")
        validate_probe(Path(row["run"]["stdout"]).read_text(), source["expected"])
        if not row.get("dependencies"):
            raise ValueError("Apply source dependencies missing")
        for dependency in row["dependencies"]:
            if sha256_file(Path(dependency["path"])) != dependency["sha256"]:
                raise ValueError("Apply source dependency changed")
        capture = row["applied_capture"]
        path = Path(capture["path"]).resolve()
        if (not path.is_relative_to(directory.resolve()) or
                capture["format"] != "u32le_case_then_vertex" or
                capture["boundary"] != "original_Apply_then_HBM_writer_all_replicas_checked" or
                capture["bytes"] != expected["checked_words"] * 4 or
                path.stat().st_size != capture["bytes"] or sha256_file(path) != capture["sha256"]):
            raise ValueError("Apply capture representation, extent, boundary or hash mismatch")
        admitted.append({**expected, **capture, "source_report_sha256": sha256_file(report_path)})
    return admitted
