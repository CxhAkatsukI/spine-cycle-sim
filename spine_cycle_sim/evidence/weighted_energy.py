"""Matched 32-controller HBM energy for dynamic weighted SSSP."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .matched_energy import MatchedEnergyError, aggregate_detailed_dramsim3


_COUNT_FIELDS = (
    "reads",
    "writes",
    "read_row_hits",
    "write_row_hits",
    "activates",
    "precharges",
)
_ENERGY_FIELDS = (
    "activate_energy_pj",
    "read_energy_pj",
    "write_energy_pj",
    "refresh_energy_pj",
    "active_standby_energy_pj",
    "precharge_standby_energy_pj",
    "self_refresh_energy_pj",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path, context: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatchedEnergyError(f"cannot read {context}: {path}") from exc
    if not isinstance(document, dict):
        raise MatchedEnergyError(f"{context} must be an object")
    return document


def subtract_detailed_dram(
    cumulative: Mapping[str, Any], prefix: Mapping[str, Any]
) -> dict[str, Any]:
    """Subtract an independently reproduced quiescent DRAM prefix."""

    if cumulative.get("controller_instances") != 32 or prefix.get(
        "controller_instances"
    ) != 32:
        raise MatchedEnergyError("weighted SSSP energy requires 32 controllers")
    result: dict[str, Any] = {}
    for field in _COUNT_FIELDS:
        value = int(cumulative[field]) - int(prefix[field])
        if value < 0:
            raise MatchedEnergyError(f"cold prefix exceeds cumulative {field}")
        result[field] = value
    for field in _ENERGY_FIELDS:
        value = float(cumulative[field]) - float(prefix[field])
        tolerance = max(1.0e-3, abs(float(cumulative[field])) * 1.0e-12)
        if value < -tolerance:
            raise MatchedEnergyError(f"cold prefix exceeds cumulative {field}")
        result[field] = max(0.0, value)
    controller_cycles = int(cumulative["controller_cycles_min"]) - int(
        prefix["controller_cycles_min"]
    )
    if controller_cycles <= 0 or (
        int(cumulative["controller_cycles_max"])
        - int(prefix["controller_cycles_max"])
        != controller_cycles
    ):
        raise MatchedEnergyError("weighted SSSP DRAM phase window is not aligned")
    result["controller_cycles_min"] = controller_cycles
    result["controller_cycles_max"] = controller_cycles
    command = sum(
        result[field]
        for field in (
            "activate_energy_pj",
            "read_energy_pj",
            "write_energy_pj",
        )
    )
    total = sum(result[field] for field in _ENERGY_FIELDS)
    background = total - command
    direct_total = float(cumulative["total_energy_pj"]) - float(
        prefix["total_energy_pj"]
    )
    tolerance = max(1.0e-3, total * 1.0e-9)
    if direct_total <= 0.0 or abs(total - direct_total) > tolerance:
        raise MatchedEnergyError("weighted SSSP subtracted energy does not close")
    result.update(
        {
            "total_energy_pj": total,
            "component_sum_pj": total,
            "command_dynamic_energy_pj": command,
            "background_and_refresh_energy_pj": background,
            "component_closure_error_pj": total - direct_total,
            "controller_instances": 32,
            "read_row_hit_ratio": (
                result["read_row_hits"] / result["reads"]
                if result["reads"]
                else 0.0
            ),
            "write_row_hit_ratio": (
                result["write_row_hits"] / result["writes"]
                if result["writes"]
                else 0.0
            ),
            "claim_label": "dramsim3_full_32_controller_hbm_energy_after_exact_cold_prefix",
        }
    )
    return result


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise MatchedEnergyError(f"empty CSV: {path}")
    return rows


def _csv_by_run(path: Path) -> dict[str, dict[str, str]]:
    rows = _csv_rows(path)
    if len({row["run_id"] for row in rows}) != len(rows):
        raise MatchedEnergyError(f"duplicate run rows in {path}")
    return {row["run_id"]: row for row in rows}


def analyze_matched_weighted_sssp_energy(
    dynamic_dir: str | Path, cold_dir: str | Path
) -> dict[str, Any]:
    """Build matched HBM-only pair rows for weighted SSSP."""

    dynamic_root = Path(dynamic_dir)
    cold_root = Path(cold_dir)
    dynamic_manifest_path = dynamic_root / "matrix_manifest.json"
    cold_manifest_path = cold_root / "matrix_manifest.json"
    dynamic_manifest = _load_json(dynamic_manifest_path, "dynamic matrix manifest")
    cold_manifest = _load_json(cold_manifest_path, "cold matrix manifest")
    for name, manifest in (("dynamic", dynamic_manifest), ("cold", cold_manifest)):
        if (
            manifest.get("status") != "PASS"
            or manifest.get("instantiate_all_hbm_channels") is not True
            or manifest.get("hbm_controller_instances") != 32
        ):
            raise MatchedEnergyError(f"{name} matrix is not 32-controller eligible")
    if dynamic_manifest.get("all_correct") is not True or cold_manifest.get(
        "all_exact_dynamic_prefix_matches"
    ) is not True:
        raise MatchedEnergyError("weighted SSSP correctness/prefix gate failed")
    run_ids = list(dynamic_manifest.get("selected_run_ids", []))
    if (
        len(run_ids) != 3
        or len(set(run_ids)) != 3
        or set(run_ids) != set(cold_manifest.get("selected_run_ids", []))
    ):
        raise MatchedEnergyError("weighted SSSP requires the same three run IDs")
    if dynamic_manifest.get("input_manifest_sha256") != cold_manifest.get(
        "input_manifest_sha256"
    ):
        raise MatchedEnergyError("dynamic and cold input manifests differ")
    input_path = Path(str(dynamic_manifest["input_manifest"]))
    if _sha256(input_path) != dynamic_manifest["input_manifest_sha256"]:
        raise MatchedEnergyError("weighted SSSP input manifest hash mismatch")
    input_manifest = _load_json(input_path, "weighted SSSP input manifest")
    runs = {run["run_id"]: run for run in input_manifest["runs"]}
    dynamic_rows = _csv_rows(dynamic_root / "system_rows.csv")
    cold_rows = _csv_by_run(cold_root / "cold_baseline_rows.csv")

    pairs = []
    system_rows = []
    for run_id in run_ids:
        run = runs.get(run_id)
        if not isinstance(run, dict) or run.get("scenario") != "insert":
            raise MatchedEnergyError(f"invalid weighted SSSP run: {run_id}")
        spine_summary_path = dynamic_root / run_id / "spine" / "summary.json"
        cold_summary_path = cold_root / run_id / "spine" / "summary.json"
        grasu_manifest_path = dynamic_root / run_id / "grasu_regraph" / "manifest.json"
        spine_summary = _load_json(spine_summary_path, "Spine dynamic summary")
        cold_summary = _load_json(cold_summary_path, "Spine cold summary")
        grasu_manifest = _load_json(grasu_manifest_path, "GraSU child manifest")
        grasu_result = grasu_manifest.get("result")
        if not isinstance(grasu_result, dict):
            raise MatchedEnergyError("GraSU child result is missing")
        if any(
            result.get("success") is not True
            or int(result.get("correctness_mismatches", -1)) != 0
            for result in (spine_summary, cold_summary, grasu_result)
        ):
            raise MatchedEnergyError(f"incorrect weighted SSSP result: {run_id}")
        if (
            cold_summary.get("cycles") != spine_summary.get("cold_cycles")
            or cold_summary.get("backend_requests")
            != spine_summary.get("cold_backend_requests")
        ):
            raise MatchedEnergyError(f"cold prefix identity failed: {run_id}")

        spine_cumulative = aggregate_detailed_dramsim3(
            dynamic_root / run_id / "spine" / "dram"
        )
        spine_prefix = aggregate_detailed_dramsim3(
            cold_root / run_id / "spine" / "dram"
        )
        spine = subtract_detailed_dram(spine_cumulative, spine_prefix)
        grasu = aggregate_detailed_dramsim3(
            dynamic_root / run_id / "grasu_regraph" / "dram"
        )
        aligned_spine_requests = int(spine_summary["backend_requests"]) - int(
            cold_summary["backend_requests"]
        )
        if spine["reads"] + spine["writes"] != aligned_spine_requests:
            raise MatchedEnergyError(f"Spine phase requests do not close: {run_id}")
        if grasu["reads"] + grasu["writes"] != int(grasu_result["backend_requests"]):
            raise MatchedEnergyError(f"GraSU requests do not close: {run_id}")
        matching_dynamic = [
            value
            for value in dynamic_rows
            if value["run_id"] == run_id and value["system"] == "spine"
        ]
        if len(matching_dynamic) != 1 or int(
            matching_dynamic[0]["aligned_backend_requests"]
        ) != aligned_spine_requests:
            raise MatchedEnergyError(f"Spine aligned ledger mismatch: {run_id}")
        if run_id not in cold_rows or int(cold_rows[run_id]["backend_requests"]) != int(
            cold_summary["backend_requests"]
        ):
            raise MatchedEnergyError(f"cold CSV ledger mismatch: {run_id}")

        dataset_id = str(run["dataset_id"])
        for system, dram in (("spine", spine), ("grasu_regraph", grasu)):
            system_rows.append(
                {
                    "algorithm": "weighted_sssp",
                    "run_id": run_id,
                    "dataset_id": dataset_id,
                    "system": system,
                    "dram": dram,
                }
            )
        pairs.append(
            {
                "algorithm": "weighted_sssp",
                "run_id": run_id,
                "dataset_id": dataset_id,
                "spine_dram_energy_pj": spine["total_energy_pj"],
                "grasu_dram_energy_pj": grasu["total_energy_pj"],
                "grasu_to_spine_dram_energy_ratio": (
                    grasu["total_energy_pj"] / spine["total_energy_pj"]
                ),
                "spine_dram_command_dynamic_energy_pj": spine[
                    "command_dynamic_energy_pj"
                ],
                "grasu_dram_command_dynamic_energy_pj": grasu[
                    "command_dynamic_energy_pj"
                ],
                "grasu_to_spine_dram_command_dynamic_energy_ratio": (
                    grasu["command_dynamic_energy_pj"]
                    / spine["command_dynamic_energy_pj"]
                ),
                "spine_dram_background_refresh_energy_pj": spine[
                    "background_and_refresh_energy_pj"
                ],
                "grasu_dram_background_refresh_energy_pj": grasu[
                    "background_and_refresh_energy_pj"
                ],
                "partial_energy_ratio_valid_as_total": False,
                "dram_energy_ratio_valid": True,
                "dram_energy_scope": "all_32_hbm_controller_instances",
            }
        )
    if len({row["dataset_id"] for row in pairs}) != 3:
        raise MatchedEnergyError("weighted SSSP energy lacks three datasets")
    return {
        "schema_version": 1,
        "status": "PASS",
        "claim_class": "matched_weighted_sssp_32_controller_hbm_energy",
        "dynamic_manifest": str(dynamic_manifest_path.resolve()),
        "dynamic_manifest_sha256": _sha256(dynamic_manifest_path),
        "cold_manifest": str(cold_manifest_path.resolve()),
        "cold_manifest_sha256": _sha256(cold_manifest_path),
        "pairs": pairs,
        "system_rows": system_rows,
        "all_correct": True,
        "cold_prefix_subtraction": "exact_quiescent_per_controller_component_subtraction",
    }


def flatten_weighted_system_rows(ledger: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in ledger["system_rows"]:
        dram = row["dram"]
        rows.append(
            {
                "algorithm": row["algorithm"],
                "run_id": row["run_id"],
                "dataset_id": row["dataset_id"],
                "system": row["system"],
                "dram_reads": dram["reads"],
                "dram_writes": dram["writes"],
                "dram_total_energy_pj": dram["total_energy_pj"],
                "dram_command_dynamic_energy_pj": dram[
                    "command_dynamic_energy_pj"
                ],
                "dram_background_refresh_energy_pj": dram[
                    "background_and_refresh_energy_pj"
                ],
                "dram_controller_cycles": dram["controller_cycles_min"],
                "claim_label": dram["claim_label"],
            }
        )
    return rows
