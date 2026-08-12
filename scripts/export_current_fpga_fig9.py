#!/usr/bin/env python3
"""Export correctness- and ledger-gated current Figure 9 pairs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analyze_current_fpga_components import (  # noqa: E402
    evidence_identity,
    load_admitted_result,
    memory_ledger_row,
    run_directory,
)


DEFAULT_CASES = ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v7.json"
DEFAULT_CONTRACT = ROOT / "configs/contracts/current_fpga_fig9_memory_v20.json"
DEFAULT_SPINE_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v12_20260812"
)
DEFAULT_GRASU_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v20_fig9_20260812"
)
DEFAULT_OUT = ROOT / "docs/evaluation_refresh_20260810/fig9_current_v20"
ARCHITECTURES = ("spine", "grasu_regraph")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def dram_energy_pj(result: Mapping[str, object], manifest: Mapping[str, object]) -> float:
    direct = manifest.get("dram_total_energy_pj", result.get("dram_total_energy_pj"))
    if isinstance(direct, (int, float)) and not isinstance(direct, bool):
        return float(direct)
    dram = manifest.get("dram")
    if isinstance(dram, Mapping):
        nested = dram.get("total_energy_pj")
        if isinstance(nested, (int, float)) and not isinstance(nested, bool):
            return float(nested)
    raise ValueError("admitted result does not report DRAMSim3 energy")


def conservation_audit(
    result: Mapping[str, object],
    manifest: Mapping[str, object],
    ledger: Mapping[str, object],
) -> dict[str, object]:
    arbitration = result.get("backend_arbitration")
    arbitration_checks = {
        "reported": isinstance(arbitration, Mapping),
        "ledger_closed": isinstance(arbitration, Mapping)
        and arbitration.get("ledger_closed") is True,
        "intent_grant_consumed_match": isinstance(arbitration, Mapping)
        and int(arbitration.get("unique_intents", -1))
        == int(arbitration.get("grants", -2))
        == int(arbitration.get("consumed_grants", -3))
        == int(result.get("backend_requests", -4)),
        "pending_empty": isinstance(arbitration, Mapping)
        and int(arbitration.get("pending_intents", -1)) == 0
        and int(arbitration.get("pending_grants", -1)) == 0,
    }
    dram = manifest.get("dram")
    manifest_checks = manifest.get("checks")
    if isinstance(dram, Mapping):
        dram_requests = int(dram.get("reads", -1)) + int(dram.get("writes", -1))
    else:
        dram_requests = int(manifest.get("dram_reads", -1)) + int(
            manifest.get("dram_writes", -1)
        )
    runner_gate = (
        manifest_checks.get("dram_request_ledger") is True
        if isinstance(manifest_checks, Mapping)
        else dram_requests == int(result.get("backend_requests", -2))
    )
    checks = {
        "memory_ledger_pass": ledger.get("status") == "PASS",
        "arbitration_reported": arbitration_checks["reported"],
        "arbitration_ledger_closed": arbitration_checks["ledger_closed"],
        "intent_grant_consumed_match": arbitration_checks[
            "intent_grant_consumed_match"
        ],
        "arbitration_pending_empty": arbitration_checks["pending_empty"],
        "dramsim_request_count_match": dram_requests
        == int(result.get("backend_requests", -2)),
        "runner_dram_request_gate": runner_gate,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "backend_requests": int(result.get("backend_requests", -1)),
        "dramsim_requests": dram_requests,
    }


def pair_row(
    *,
    dataset: str,
    algorithm: str,
    spine_ledger: Mapping[str, object],
    grasu_ledger: Mapping[str, object],
    spine_energy_pj: float,
    grasu_energy_pj: float,
) -> dict[str, object]:
    if spine_ledger.get("status") != "PASS" or grasu_ledger.get("status") != "PASS":
        raise ValueError("Figure 9 cannot admit a failed memory ledger")
    spine_bytes = int(spine_ledger["accepted_backend_bytes"])
    grasu_bytes = int(grasu_ledger["accepted_backend_bytes"])
    if min(spine_bytes, grasu_bytes) <= 0 or min(spine_energy_pj, grasu_energy_pj) <= 0:
        raise ValueError("Figure 9 bytes and energy must be positive")
    return {
        "dataset": dataset,
        "dataset_id": dataset,
        "algorithm": algorithm,
        "competitor": "grasu_regraph_k4_shared",
        "spine_memory_bytes": spine_bytes,
        "competitor_memory_bytes": grasu_bytes,
        "memory_ratio_gr_over_spine": grasu_bytes / spine_bytes,
        "spine_dram_energy_pj": spine_energy_pj,
        "competitor_dram_energy_pj": grasu_energy_pj,
        "spine_energy_advantage": grasu_energy_pj / spine_energy_pj,
        "energy_scope": "bound_channel_dramsim3_activity_and_background",
        "correctness_gate": "PASS",
        "memory_ledger_gate": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--spine-root", type=Path, default=DEFAULT_SPINE_ROOT)
    parser.add_argument("--grasu-root", type=Path, default=DEFAULT_GRASU_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    cases_path = args.cases.resolve()
    contract_path = args.contract.resolve()
    cases = read_json(cases_path)
    contract = read_json(contract_path)
    if contract.get("status") != "frozen_before_current_grasu_execution":
        raise ValueError("Figure 9 contract is not frozen")
    if sha256_file(cases_path) != contract["case_contract"]["sha256"]:
        raise ValueError("Figure 9 case contract hash mismatch")
    roots = {
        "spine": args.spine_root.resolve(),
        "grasu_regraph": args.grasu_root.resolve(),
    }
    plugins: dict[str, tuple[Path, str]] = {}
    for architecture in ARCHITECTURES:
        architecture_contract = contract["architectures"][architecture]
        plugin = ROOT / architecture_contract["plugin"]["path"]
        plugin_sha256 = sha256_file(plugin)
        if plugin_sha256 != architecture_contract["plugin"]["sha256"]:
            raise ValueError(f"Figure 9 {architecture} plugin differs from contract")
        plugins[architecture] = (plugin, plugin_sha256)
        for profile in architecture_contract["profiles"].values():
            if sha256_file(ROOT / profile["path"]) != profile["sha256"]:
                raise ValueError(f"Figure 9 profile differs from contract: {profile['path']}")

    rows: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    missing: list[str] = []
    for algorithm in contract["algorithms"]:
        specification = cases["algorithms"][algorithm]
        for dataset in contract["datasets"]:
            systems: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, object], dict[str, object]]] = {}
            for architecture in ARCHITECTURES:
                run_dir = run_directory(
                    roots[architecture], specification, dataset, architecture
                )
                try:
                    result, result_path, manifest_path = load_admitted_result(run_dir)
                except FileNotFoundError:
                    missing.append(f"{dataset}:{algorithm}:{architecture}")
                    continue
                manifest = read_json(manifest_path)
                profile = contract["architectures"][architecture]["profiles"][algorithm]
                _plugin, plugin_sha256 = plugins[architecture]
                if manifest.get("sst_plugin_sha256") != plugin_sha256:
                    raise ValueError(f"Figure 9 plugin mismatch: {run_dir}")
                if evidence_identity(
                    result, manifest, ("profile_id", "architecture_profile_id")
                ) != profile["profile_id"]:
                    raise ValueError(f"Figure 9 profile mismatch: {run_dir}")
                profile_parameters = read_json(ROOT / profile["path"])["parameters"]
                ledger = memory_ledger_row(
                    architecture,
                    algorithm,
                    dataset,
                    str(cases["roles"][dataset]),
                    result,
                    result_path,
                    profile_parameters,
                )
                conservation = conservation_audit(result, manifest, ledger)
                if conservation["status"] != "PASS":
                    raise ValueError(
                        f"Figure 9 conservation audit failed: {run_dir}: "
                        f"{conservation['checks']}"
                    )
                systems[architecture] = (result, manifest, ledger, conservation)
                evidence.append(
                    {
                        "dataset": dataset,
                        "algorithm": algorithm,
                        "architecture": architecture,
                        "result": str(result_path.resolve()),
                        "result_sha256": sha256_file(result_path),
                        "manifest": str(manifest_path.resolve()),
                        "manifest_sha256": sha256_file(manifest_path),
                        "ledger_status": ledger["status"],
                        "conservation_status": conservation["status"],
                        "conservation_checks": conservation["checks"],
                    }
                )
            if set(systems) != set(ARCHITECTURES):
                continue
            spine_result, spine_manifest, spine_ledger, _spine_conservation = systems["spine"]
            grasu_result, grasu_manifest, grasu_ledger, _grasu_conservation = systems["grasu_regraph"]
            rows.append(
                pair_row(
                    dataset=dataset,
                    algorithm=algorithm,
                    spine_ledger=spine_ledger,
                    grasu_ledger=grasu_ledger,
                    spine_energy_pj=dram_energy_pj(spine_result, spine_manifest),
                    grasu_energy_pj=dram_energy_pj(grasu_result, grasu_manifest),
                )
            )

    expected = int(contract["gates"]["rows_expected"])
    if (missing or len(rows) != expected) and not args.allow_partial:
        raise FileNotFoundError(
            f"Figure 9 current matrix incomplete: rows={len(rows)}/{expected}, "
            f"missing={missing}"
        )
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if rows:
        write_csv(output / "pair_rows.csv", rows)
    status = "PASS_CURRENT_MODEL_DATA" if len(rows) == expected and not missing else "INCOMPLETE"
    write_json(
        output / "manifest.json",
        {
            "schema_version": 1,
            "status": status,
            "metric": "accepted_backend_bytes_and_bound_channel_dramsim3_energy",
            "cases": str(cases_path),
            "cases_sha256": sha256_file(cases_path),
            "contract": str(contract_path),
            "contract_sha256": sha256_file(contract_path),
            "simulation_roots": {
                architecture: str(path) for architecture, path in roots.items()
            },
            "plugins": {
                architecture: {
                    "path": str(plugin.resolve()),
                    "sha256": plugin_sha256,
                }
                for architecture, (plugin, plugin_sha256) in plugins.items()
            },
            "rows": len(rows),
            "expected_rows": expected,
            "missing": missing,
            "evidence": evidence,
        },
    )
    print(f"CURRENT_FPGA_FIG9_{status} rows={len(rows)}/{expected} out={output}")
    return 0 if status == "PASS_CURRENT_MODEL_DATA" or args.allow_partial else 1


if __name__ == "__main__":
    raise SystemExit(main())
