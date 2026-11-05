"""Execute the frozen matrix with finite memory and correctness admission."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from spine_cycle_sim.experiments.shared_workloads import load_slice
from .matrix import ROOT, prepare


def admit(case: dict, plugin_sha: str) -> dict:
    directory = Path(case["out_dir"])
    raw_path = directory / "result.json"
    raw = json.loads(raw_path.read_text())
    summary_path = next(p for p in (directory / "run_manifest.json", directory / "summary.json") if p.exists())
    summary = json.loads(summary_path.read_text())
    if raw.get("success") is not True or summary.get("status") != "PASS":
        raise ValueError("runner or raw correctness admission failed")
    if summary.get("sst_plugin_sha256") != plugin_sha:
        raise ValueError("loaded plugin differs from frozen plugin")
    required = ["correctness_mismatches"]
    if "rq3_trace_carry" not in case["previous_execution_id"]:
        required += ["architecture_correctness_mismatches", "mathematical_correctness_mismatches"]
    if any(raw.get(key) != 0 for key in required):
        raise ValueError(f"missing or nonzero correctness counters: {required}")
    if raw.get("maintenance_stage_ledger_closed") is not True:
        raise ValueError("open maintenance ledger")
    total = raw["update_cycles"] if raw.get("cold_cycles", 0) else raw["cycles"]
    vertices = raw.get("vertices")
    if vertices is None:
        vertices = load_slice(Path(case["inputs"]["--workload"]["path"])).vertices
    return {"status": "pass", "case": {"execution_id": case["execution_id"],
        "dataset_id": case["dataset_id"], "system": "spine", "algorithm": case["algorithm"],
        "scenario": "delete" if "delete_fallback" in case["execution_id"] else "insert",
        "batch_size": case["batch_size"], "update": {"user_mutations": case["batch_size"],
            "physical_records": case["physical_records"]}},
        "row": {"cycles": int(total), "dataset_kind": case["dataset_kind"],
                **{key: raw[key] for key in required},
                "validation_contract": "carry_fixture" if len(required) == 1 else "generic_algorithm_oracles",
                "measurement_window": "dynamic_e2e_to_convergence"},
        "scalar_metrics": {"vertices": vertices,
            "zero_net": case["previous_execution_id"] == "zero_net_sssp",
            "update_cycles": raw.get("update_cycles", 0)},
        "raw_result_path": str(raw_path), "raw_result_sha256": sha256_file(raw_path),
        "plugin_sha256": plugin_sha, "rq3_role": case["role"]}


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--lib-dir", type=Path, required=True)
    parser.add_argument("--only", help="substring selection for correctness smoke")
    parser.add_argument("--memory-gib", type=int, choices=(4, 8, 16, 32), default=32,
                        help="finite child address-space budget, frozen in the campaign identity")
    args = parser.parse_args()
    output, library = args.out_dir.resolve(), args.lib_dir.resolve()
    path = output / "matrix.json"
    matrix = json.loads(path.read_text()) if path.exists() else prepare(output, library)
    plugin_sha = sha256_file(library / "libspine_cycle.so")
    identity = {"plugin_sha256": plugin_sha,
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0],
        "source_hashes": {str(p.relative_to(ROOT)): sha256_file(p)
            for directory in ("cpp", "sst") for p in (ROOT / directory).rglob("*")
            if p.is_file() and p.suffix in (".cpp", ".hpp", ".py") and "build" not in p.parts},
        "memory": {"per_process_address_limit_gib": args.memory_gib, "reserve_gib": 24, "jobs": 1},
        "matrix_sha256": sha256_file(path)}
    identity_path = output / "identity.json"
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise ValueError("identity changed; use a fresh output directory")
    atomic_write_json(identity_path, identity)
    status_path = output / "status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    for case in matrix["cases"]:
        if args.only and args.only not in case["execution_id"]:
            continue
        directory = Path(case["out_dir"])
        wrapper_path = directory / "case_result.json"
        if wrapper_path.exists():
            if json.loads(wrapper_path.read_text()) != admit(case, plugin_sha):
                raise ValueError("saved admission changed")
            status[case["execution_id"]] = "PASS_REUSED_THIS_CAMPAIGN"
            continue
        if (directory / "result.json").exists():
            atomic_write_json(wrapper_path, admit(case, plugin_sha))
            status[case["execution_id"]] = "PASS_REVALIDATED_UNCHANGED_RAW"
            atomic_write_json(status_path, status)
            print(status[case["execution_id"]], case["execution_id"], flush=True)
            continue
        print("RUN", case["execution_id"], flush=True)
        resources = run_bounded(case["command"], ROOT, directory / "driver",
                                timeout=1200, memory_gib=args.memory_gib, reserve_gib=24)
        try:
            if resources["exit_code"] != 0:
                raise ValueError(f"runner exit {resources['exit_code']}")
            atomic_write_json(wrapper_path, admit(case, plugin_sha))
            status[case["execution_id"]] = "PASS"
        except (ValueError, KeyError, FileNotFoundError, StopIteration) as error:
            status[case["execution_id"]] = f"FAIL: {error}"
        atomic_write_json(status_path, status)
        print(status[case["execution_id"]], round(resources["wall_seconds"], 2), "s", flush=True)
    atomic_write_json(status_path, status)
    if any(not state.startswith("PASS") for state in status.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
