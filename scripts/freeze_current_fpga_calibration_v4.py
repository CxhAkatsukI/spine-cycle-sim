#!/usr/bin/env python3
"""Freeze AU/SU timing models before any WK/R19 holdout is executed."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_current_fpga_calibration import (  # noqa: E402
    ARCHITECTURES,
    collect_total_records,
    read_json,
)
from scripts.analyze_current_fpga_components import (  # noqa: E402
    component_samples,
    discover_hardware_logs,
    evidence_identity,
    load_admitted_result,
    run_directory,
    unique_prefixed_record,
)
from spine_cycle_sim.calibration.current_fpga import (  # noqa: E402
    CurrentFPGAComponentRecord,
    fit_component_scale_calibration_only,
    fit_total_scale_calibration_only,
)


DEFAULT_CASES = ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v5.json"
DEFAULT_CONTRACT = (
    ROOT / "configs/contracts/evaluation_refresh_fpga_calibration_v6.json"
)
DEFAULT_OUT = ROOT / "docs/evaluation_refresh_20260810/calibration_v10_frozen"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def group_total_models(records: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[Any]] = {}
    for record in records:
        if record.role != "calibration":
            raise ValueError("calibration freeze received a holdout total row")
        grouped.setdefault(
            (record.architecture, record.algorithm, record.profile_id), []
        ).append(record)
    models = []
    for key in sorted(grouped):
        model = fit_total_scale_calibration_only(grouped[key])
        models.append(
            {
                **asdict(model),
                "profile_id": key[2],
                "fit_role": "calibration_only",
                "holdout_used_for_fit": False,
                "model_form": (
                    "hardware_cycles = scale * execution_driven_simulator_cycles"
                ),
            }
        )
    return models


def collect_component_records(
    cases: dict[str, Any],
    contract: dict[str, Any],
    simulation_root: Path,
    hardware_root: Path,
) -> tuple[list[CurrentFPGAComponentRecord], list[dict[str, Any]]]:
    profile_entries = {
        (row["architecture"], row["algorithm"]): row
        for row in contract["architecture_profiles"]
    }
    expected_plugin_sha256 = str(contract["simulator_plugin"]["sha256"])
    clock_mhz = float(cases["clock_mhz"])
    records: list[CurrentFPGAComponentRecord] = []
    evidence: list[dict[str, Any]] = []
    calibration_datasets = tuple(
        dataset for dataset, role in cases["roles"].items() if role == "calibration"
    )
    for algorithm, algorithm_spec in cases["algorithms"].items():
        for dataset in calibration_datasets:
            for architecture in ARCHITECTURES:
                run_dir = run_directory(
                    simulation_root, algorithm_spec, dataset, architecture
                )
                result, result_path, manifest_path = load_admitted_result(run_dir)
                manifest = read_json(manifest_path)
                profile = profile_entries[(architecture, algorithm)]
                observed_profile_id = evidence_identity(
                    result, manifest, ("profile_id", "architecture_profile_id")
                )
                observed_profile_sha = evidence_identity(
                    result,
                    manifest,
                    ("profile_sha256", "architecture_profile_sha256"),
                )
                if observed_profile_id != profile["profile_id"]:
                    raise ValueError(
                        f"profile mismatch: {architecture}:{algorithm}:{dataset}"
                    )
                if observed_profile_sha != profile["sha256"]:
                    raise ValueError(
                        f"profile hash mismatch: {architecture}:{algorithm}:{dataset}"
                    )
                if manifest.get("sst_plugin_sha256") != expected_plugin_sha256:
                    raise ValueError(
                        f"plugin mismatch: {architecture}:{algorithm}:{dataset}"
                    )
                logs = discover_hardware_logs(
                    hardware_root, algorithm_spec, dataset, architecture
                )
                if len(logs) < 3:
                    raise FileNotFoundError(
                        f"three hardware logs: {architecture}:{algorithm}:{dataset}"
                    )
                prefix = (
                    "SPINE_HW_TIMING"
                    if architecture == "spine"
                    else algorithm_spec["hardware_timing_prefix"]
                )
                hardware_records = [
                    unique_prefixed_record(path, prefix) for path in logs
                ]
                for component, simulator, hardware, observation in component_samples(
                    architecture, algorithm, result, hardware_records, clock_mhz
                ):
                    records.append(
                        CurrentFPGAComponentRecord(
                            architecture=architecture,
                            algorithm=algorithm,
                            profile_id=profile["profile_id"],
                            dataset=dataset,
                            role="calibration",
                            component=component,
                            simulator_cycles=simulator,
                            hardware_cycles=hardware,
                            hardware_observation=observation,
                        )
                    )
                evidence.append(
                    {
                        "architecture": architecture,
                        "algorithm": algorithm,
                        "dataset": dataset,
                        "role": "calibration",
                        "profile_id": profile["profile_id"],
                        "profile_sha256": profile["sha256"],
                        "sst_plugin_sha256": expected_plugin_sha256,
                        "simulator_result": str(result_path.resolve()),
                        "simulator_result_sha256": sha256_file(result_path),
                        "simulator_manifest": str(manifest_path.resolve()),
                        "simulator_manifest_sha256": sha256_file(manifest_path),
                        "hardware_logs": [str(path) for path in logs],
                        "hardware_log_sha256": [sha256_file(path) for path in logs],
                    }
                )
    return records, evidence


def group_component_models(
    records: list[CurrentFPGAComponentRecord],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[CurrentFPGAComponentRecord]] = {}
    for record in records:
        if record.role != "calibration":
            raise ValueError("calibration freeze received a holdout component row")
        grouped.setdefault(
            (
                record.architecture,
                record.algorithm,
                record.profile_id,
                record.component,
            ),
            [],
        ).append(record)
    models = []
    for key in sorted(grouped):
        model = fit_component_scale_calibration_only(grouped[key])
        models.append(
            {
                **asdict(model),
                "profile_id": key[2],
                "fit_role": "calibration_only",
                "holdout_used_for_fit": False,
                "hardware_observation": grouped[key][0].hardware_observation,
            }
        )
    return models


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--simulation-root", type=Path)
    parser.add_argument("--hardware-root", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    cases_path = args.cases.resolve()
    contract_path = args.contract.resolve()
    cases = read_json(cases_path)
    contract = read_json(contract_path)
    if cases.get("status") != "frozen" or contract.get("status") != "frozen":
        raise ValueError("case and calibration contracts must be frozen")
    if cases.get("calibration_contract_id") != contract.get("contract_id"):
        raise ValueError("case and calibration contracts disagree")
    plugin = ROOT / contract["simulator_plugin"]["path"]
    if not plugin.is_file() or sha256_file(plugin) != contract["simulator_plugin"][
        "sha256"
    ]:
        raise ValueError("frozen simulator plugin identity mismatch")
    for profile in contract["architecture_profiles"]:
        profile_path = ROOT / profile["path"]
        if not profile_path.is_file() or sha256_file(profile_path) != profile["sha256"]:
            raise ValueError(
                "frozen architecture profile identity mismatch: "
                f"{profile['architecture']}:{profile['algorithm']}"
            )
    simulation_root = (
        args.simulation_root or Path(cases["default_simulation_root"])
    ).resolve()
    hardware_root = (
        args.hardware_root or Path(cases["default_hardware_root"])
    ).resolve()

    holdout_results = sorted(
        path
        for dataset, role in cases["roles"].items()
        if role == "holdout"
        for path in (simulation_root / "runs_current_v1" / dataset).rglob(
            "result.json"
        )
    )
    if holdout_results:
        raise ValueError(
            "calibration freeze requires a clean pre-holdout root; found "
            + ", ".join(str(path) for path in holdout_results)
        )

    total_records, total_evidence, missing = collect_total_records(
        cases,
        contract,
        simulation_root,
        hardware_root,
        allow_partial=True,
    )
    expected_missing = sorted(
        f"{architecture}:{algorithm}:{dataset}"
        for dataset, role in cases["roles"].items()
        if role == "holdout"
        for algorithm in cases["algorithms"]
        for architecture in ARCHITECTURES
    )
    if sorted(missing) != expected_missing:
        raise ValueError(
            "calibration freeze is missing non-holdout rows or observed holdout rows"
        )
    total_models = group_total_models(total_records)
    component_records, component_evidence = collect_component_records(
        cases, contract, simulation_root, hardware_root
    )
    component_models = group_component_models(component_records)
    expected_total_models = len(ARCHITECTURES) * len(cases["algorithms"])
    if len(total_models) != expected_total_models:
        raise ValueError(
            f"expected {expected_total_models} total models, got {len(total_models)}"
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    total_models_path = args.out_dir / "frozen_total_models.json"
    component_models_path = args.out_dir / "frozen_component_models.json"
    write_json(
        total_models_path,
        {
            "schema_version": 1,
            "status": "FROZEN_BEFORE_HOLDOUT",
            "contract_id": contract["contract_id"],
            "contract_sha256": sha256_file(contract_path),
            "cases_sha256": sha256_file(cases_path),
            "plugin_sha256": sha256_file(plugin),
            "models": total_models,
        },
    )
    write_json(
        component_models_path,
        {
            "schema_version": 1,
            "status": "FROZEN_BEFORE_HOLDOUT",
            "contract_id": contract["contract_id"],
            "contract_sha256": sha256_file(contract_path),
            "cases_sha256": sha256_file(cases_path),
            "plugin_sha256": sha256_file(plugin),
            "models": component_models,
        },
    )
    write_json(
        args.out_dir / "calibration_freeze_manifest.json",
        {
            "schema_version": 1,
            "status": "FROZEN_BEFORE_HOLDOUT",
            "contract_id": contract["contract_id"],
            "contract_sha256": sha256_file(contract_path),
            "cases_sha256": sha256_file(cases_path),
            "plugin": str(plugin.resolve()),
            "plugin_sha256": sha256_file(plugin),
            "frozen_total_models": str(total_models_path.resolve()),
            "frozen_total_models_sha256": sha256_file(total_models_path),
            "frozen_component_models": str(component_models_path.resolve()),
            "frozen_component_models_sha256": sha256_file(component_models_path),
            "calibration_datasets": sorted(
                dataset
                for dataset, role in cases["roles"].items()
                if role == "calibration"
            ),
            "holdout_datasets": sorted(
                dataset
                for dataset, role in cases["roles"].items()
                if role == "holdout"
            ),
            "holdout_result_files_present_at_freeze": [],
            "total_model_count": len(total_models),
            "component_model_count": len(component_models),
            "total_evidence": total_evidence,
            "component_evidence": component_evidence,
        },
    )
    print(
        "CURRENT_FPGA_CALIBRATION_FROZEN "
        f"total_models={len(total_models)} component_models={len(component_models)} "
        f"out={args.out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
