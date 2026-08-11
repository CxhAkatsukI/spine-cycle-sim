#!/usr/bin/env python3
"""Assemble current-FPGA Spine RQ3 evidence from one immutable v11 plugin."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_current_fpga_components import (  # noqa: E402
    evidence_identity,
    load_admitted_result,
    run_directory,
)
from spine_cycle_sim.experiments.publication_analysis import (  # noqa: E402
    load_case_results,
)
from spine_cycle_sim.experiments.rq3 import (  # noqa: E402
    analyze_rq3_results,
    write_rq3_analysis,
)


DEFAULT_CASES = ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v6.json"
DEFAULT_CONTRACT = (
    ROOT / "configs/contracts/evaluation_refresh_fpga_calibration_v7.json"
)
DEFAULT_CARRY_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_rq3_20260812/carry"
)
DEFAULT_DELETE_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_rq3_20260812/"
    "delete_fallback"
)
DEFAULT_RESIDUAL_CORRECTION_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_rq3_20260812/"
    "residual_correction"
)
DEFAULT_RESIDUAL_CORRECTION_SWEEP_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_rq3_20260812/"
    "residual_correction_sweep"
)
DEFAULT_OUT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_rq3_20260812/package"
)
WORKLOAD_TAG = {
    "weighted_sssp": "weighted_sssp",
    "connected_components": "connected_components",
    "thresholded_residual_pagerank": "residual_pagerank",
}


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def case_payload(
    *,
    execution_id: str,
    dataset: str,
    algorithm: str,
    scenario: str,
    role: str,
    user_mutations: int,
    physical_records: int,
    raw_result_path: Path,
    result: dict[str, Any],
    plugin_sha256: str,
) -> dict[str, Any]:
    if result.get("success") is not True:
        raise ValueError(f"failed raw RQ3 result: {raw_result_path}")
    for field in (
        "correctness_mismatches",
        "architecture_correctness_mismatches",
        "mathematical_correctness_mismatches",
    ):
        if int(result.get(field, 0)) != 0:
            raise ValueError(f"nonzero {field}: {raw_result_path}")
    return {
        "status": "pass",
        "case": {
            "execution_id": execution_id,
            "dataset_id": dataset,
            "system": "spine",
            "algorithm": algorithm,
            "scenario": scenario,
            "batch_size": user_mutations,
            "update": {
                "user_mutations": user_mutations,
                "physical_records": physical_records,
            },
        },
        "row": {
            "cycles": int(result["cycles"]),
            "dataset_kind": (
                "synthetic" if role == "synthetic_calibration" else "real"
            ),
            "architecture_correctness_mismatches": 0,
            "mathematical_correctness_mismatches": 0,
        },
        "scalar_metrics": {
            "maintenance_cycles": int(result.get("maintenance_cycles", 0)),
            "update_cycles": int(result.get("update_cycles", 0)),
            "measurement_window": "dynamic_e2e_to_convergence",
        },
        "raw_result_path": str(raw_result_path.resolve()),
        "raw_result_sha256": sha256_file(raw_result_path),
        "plugin_sha256": plugin_sha256,
        "rq3_role": role,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--simulation-root", type=Path)
    parser.add_argument("--carry-root", type=Path, default=DEFAULT_CARRY_ROOT)
    parser.add_argument("--delete-root", type=Path, default=DEFAULT_DELETE_ROOT)
    parser.add_argument(
        "--residual-correction-root",
        type=Path,
        default=DEFAULT_RESIDUAL_CORRECTION_ROOT,
    )
    parser.add_argument(
        "--residual-correction-sweep-root",
        type=Path,
        default=DEFAULT_RESIDUAL_CORRECTION_SWEEP_ROOT,
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    cases_path = args.cases.resolve()
    contract_path = args.contract.resolve()
    cases = read_json(cases_path)
    contract = read_json(contract_path)
    if cases.get("calibration_contract_id") != contract.get("contract_id"):
        raise ValueError("RQ3 case and calibration contracts disagree")
    plugin = ROOT / contract["simulator_plugin"]["path"]
    plugin_sha256 = sha256_file(plugin)
    if plugin_sha256 != contract["simulator_plugin"]["sha256"]:
        raise ValueError("RQ3 plugin differs from the frozen contract")
    simulation_root = (
        args.simulation_root or Path(cases["default_simulation_root"])
    ).resolve()
    profile_entries = {
        row["algorithm"]: row
        for row in contract["architecture_profiles"]
        if row["architecture"] == "spine"
    }
    output = args.out_dir.resolve()
    wrappers: list[dict[str, Any]] = []
    missing: list[str] = []

    for algorithm, specification in cases["algorithms"].items():
        expected_profile = profile_entries[algorithm]
        for dataset, contract_role in cases["roles"].items():
            run_dir = run_directory(simulation_root, specification, dataset, "spine")
            try:
                result, result_path, manifest_path = load_admitted_result(run_dir)
            except FileNotFoundError:
                missing.append(f"{dataset}:{algorithm}")
                continue
            manifest = read_json(manifest_path)
            if manifest.get("sst_plugin_sha256") != plugin_sha256:
                raise ValueError(f"RQ3 plugin mismatch: {dataset}:{algorithm}")
            if evidence_identity(
                result, manifest, ("profile_id", "architecture_profile_id")
            ) != expected_profile["profile_id"]:
                raise ValueError(f"RQ3 profile mismatch: {dataset}:{algorithm}")
            metadata = read_json(
                simulation_root
                / "workloads"
                / f"{dataset}_{WORKLOAD_TAG[algorithm]}_insert_u8.json"
            )
            role = (
                "trace_calibration"
                if contract_role == "calibration"
                else "trace_holdout"
            )
            wrappers.append(
                case_payload(
                    execution_id=f"current_fpga_v11_{dataset}_{algorithm}_u8",
                    dataset=dataset,
                    algorithm=algorithm,
                    scenario="insert",
                    role=role,
                    user_mutations=8,
                    physical_records=int(metadata["update_edges"]),
                    raw_result_path=result_path,
                    result=result,
                    plugin_sha256=plugin_sha256,
                )
            )

    carry_summary_path = args.carry_root.resolve() / "summary.json"
    carry_summary = read_json(carry_summary_path)
    expected_sssp = profile_entries["weighted_sssp"]
    if (
        carry_summary.get("plugin_sha256") != plugin_sha256
        or carry_summary.get("profile_sha256") != expected_sssp["sha256"]
        or carry_summary.get("all_correct") is not True
    ):
        raise ValueError("current-FPGA carry sweep identity or correctness failed")
    for target in (1, 2, 3, 4, 5):
        path = args.carry_root.resolve() / "runs" / f"l{target}" / "case_result.json"
        payload = read_json(path)
        if payload.get("plugin_sha256") != plugin_sha256:
            raise ValueError(f"carry L{target} plugin mismatch")
        wrappers.append(payload)

    delete_root = args.delete_root.resolve()
    delete_result_path = delete_root / "result.json"
    delete_summary_path = delete_root / "summary.json"
    delete_result = read_json(delete_result_path)
    delete_summary = read_json(delete_summary_path)
    if (
        delete_summary.get("status") != "PASS"
        or delete_summary.get("sst_plugin_sha256") != plugin_sha256
        or delete_summary.get("architecture_profile_id")
        != expected_sssp["profile_id"]
        or delete_summary.get("architecture_profile_sha256")
        != expected_sssp["sha256"]
    ):
        raise ValueError("current-FPGA deletion fallback identity failed")
    wrappers.append(
        case_payload(
            execution_id="current_fpga_v11_delete_fallback_sssp",
            dataset="synthetic_delete_fallback",
            algorithm="weighted_sssp",
            scenario="delete",
            role="synthetic_calibration",
            user_mutations=1,
            physical_records=1,
            raw_result_path=delete_result_path,
            result=delete_result,
            plugin_sha256=plugin_sha256,
        )
    )

    expected_respr = profile_entries["thresholded_residual_pagerank"]
    correction_sweep_results: list[Path] = []
    for user_mutations in (1, 64):
        sweep_result_path = (
            args.residual_correction_sweep_root.resolve()
            / f"deltahls_soc_flickr_insert_u{user_mutations}"
            / "eps_1e-06"
            / "spine"
            / "summary.json"
        )
        sweep_result = read_json(sweep_result_path)
        if (
            sweep_result.get("sst_plugin_sha256") != plugin_sha256
            or sweep_result.get("architecture_profile_id")
            != expected_respr["profile_id"]
            or sweep_result.get("architecture_profile_sha256")
            != expected_respr["sha256"]
            or int(sweep_result.get("iterations", 0)) <= 0
            or int(sweep_result.get("residual_correction_cycles", 0)) <= 0
            or sweep_result.get("memory_ledger_match") is not True
        ):
            raise ValueError(
                f"current-FPGA residual correction u{user_mutations} failed"
            )
        wrappers.append(
            case_payload(
                execution_id=(
                    f"current_fpga_v11_flickr_respr_correction_u{user_mutations}"
                ),
                dataset=f"flickr_pr_correction_u{user_mutations}",
                algorithm="thresholded_residual_pagerank",
                scenario="pagerank_correction",
                role="synthetic_calibration",
                user_mutations=user_mutations,
                physical_records=int(sweep_result.get("update_edges", 0)),
                raw_result_path=sweep_result_path,
                result=sweep_result,
                plugin_sha256=plugin_sha256,
            )
        )
        correction_sweep_results.append(sweep_result_path)

    correction_result_path = (
        args.residual_correction_root.resolve()
        / "deltahls_soc_flickr_insert_u8"
        / "eps_1e-06"
        / "spine"
        / "summary.json"
    )
    correction_result = read_json(correction_result_path)
    if (
        correction_result.get("sst_plugin_sha256") != plugin_sha256
        or correction_result.get("architecture_profile_id")
        != expected_respr["profile_id"]
        or correction_result.get("architecture_profile_sha256")
        != expected_respr["sha256"]
        or int(correction_result.get("iterations", 0)) <= 0
        or int(correction_result.get("residual_correction_cycles", 0)) <= 0
        or correction_result.get("memory_ledger_match") is not True
    ):
        raise ValueError("current-FPGA residual correction identity failed")
    wrappers.append(
        case_payload(
            execution_id="current_fpga_v11_flickr_respr_correction_u8",
            dataset="flickr_pr_correction",
            algorithm="thresholded_residual_pagerank",
            scenario="pagerank_correction",
            role="trace_holdout",
            user_mutations=8,
            physical_records=int(correction_result.get("update_edges", 0)),
            raw_result_path=correction_result_path,
            result=correction_result,
            plugin_sha256=plugin_sha256,
        )
    )

    if missing and not args.allow_partial:
        raise FileNotFoundError("missing current-FPGA RQ3 rows: " + ", ".join(missing))
    for payload in wrappers:
        execution_id = str(payload["case"]["execution_id"])
        write_json(output / "runs" / execution_id / "case_result.json", payload)

    analysis = analyze_rq3_results(
        load_case_results([output]),
        preferred_plugin_sha256=[plugin_sha256],
        calibration_dataset_ids=[
            dataset for dataset, role in cases["roles"].items() if role == "calibration"
        ],
    )
    write_rq3_analysis(output / "analysis", analysis)
    write_json(
        output / "manifest.json",
        {
            "schema_version": 1,
            "status": "INCOMPLETE" if missing else "PASS",
            "contract": str(contract_path),
            "contract_sha256": sha256_file(contract_path),
            "cases": str(cases_path),
            "cases_sha256": sha256_file(cases_path),
            "plugin": str(plugin.resolve()),
            "plugin_sha256": plugin_sha256,
            "simulation_root": str(simulation_root),
            "carry_summary": str(carry_summary_path),
            "carry_summary_sha256": sha256_file(carry_summary_path),
            "delete_result": str(delete_result_path),
            "delete_result_sha256": sha256_file(delete_result_path),
            "residual_correction_result": str(correction_result_path),
            "residual_correction_result_sha256": sha256_file(
                correction_result_path
            ),
            "residual_correction_sweep_results": [
                {
                    "path": str(path),
                    "sha256": sha256_file(path),
                    "role": "synthetic_calibration",
                }
                for path in correction_sweep_results
            ],
            "case_results": len(wrappers),
            "missing": missing,
            "excluded_claims": [
                {
                    "case_class": "zero_net_no_repair",
                    "reason": (
                        "current routed HLS does not coalesce a full-key signed "
                        "batch before dirty publication; strict no-repair evidence "
                        "is target-only"
                    ),
                }
            ],
        },
    )
    print(
        f"CURRENT_FPGA_RQ3_{'INCOMPLETE' if missing else 'PASS'} "
        f"rows={len(wrappers)} missing={len(missing)} out={output}",
        flush=True,
    )
    return 0 if not missing or args.allow_partial else 1


if __name__ == "__main__":
    raise SystemExit(main())
