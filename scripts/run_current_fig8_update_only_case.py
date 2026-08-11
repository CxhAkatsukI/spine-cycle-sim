#!/usr/bin/env python3
"""Run one current-model setup-inclusive Fig. 8 update-only case."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.persistent_update_only import (  # noqa: E402
    HostRuntimeModel,
    analyze_persistent_update_pair,
)
from spine_cycle_sim.calibration.frozen import (  # noqa: E402
    load_frozen_scale_models,
)


DEFAULT_HOST_TOOL = (
    Path("/data/tmp/chuxiao/spine-cycle-sim-sharded-k4-v3-build")
    / "cpp"
    / "persistent_update_host_benchmark"
)
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_LIB_DIR = ROOT / "cpp/sst/build/sst-current-fpga-v11"
DEFAULT_SPINE_PROFILE = (
    ROOT / "configs/architectures/spine_owner_fifo_sssp_hls_v1.json"
)
DEFAULT_GRASU_PROFILE = (
    ROOT
    / "configs/architectures/"
    "grasu_regraph_sharded_k4_weighted_hls_v8.json"
)
DEFAULT_CAPABILITY_CATALOG = (
    ROOT / "configs/contracts/grasu_regraph_sharded_k4_hls_capabilities_v8.json"
)
DEFAULT_CASE_CONTRACT = (
    ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v6.json"
)
DEFAULT_CALIBRATION_CONTRACT = (
    ROOT / "configs/contracts/evaluation_refresh_fpga_calibration_v7.json"
)
DEFAULT_FROZEN_MODELS = (
    ROOT / "docs/evaluation_refresh_20260810/calibration_v11_frozen"
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def directed_insert_updates(materialization: dict[str, Any]) -> dict[int, Path]:
    updates: dict[int, Path] = {}
    for artifact in materialization.get("updates", []):
        if (
            artifact.get("projection") == "directed"
            and artifact.get("scenario") == "insert"
        ):
            updates[int(artifact["user_mutations"])] = Path(str(artifact["path"]))
    return updates


def run_command(
    command: list[str],
    cwd: Path,
    log_path: Path,
    *,
    allow_success_result: Path | None = None,
    expected_mode: str | None = None,
) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0 and allow_success_result is not None:
        if allow_success_result.is_file():
            result = load_json(allow_success_result)
            if result.get("success") is True and (
                expected_mode is None or result.get("mode") == expected_mode
            ):
                return
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed with rc={completed.returncode}; see {log_path}"
        )


def run_host_benchmark(
    *,
    host_tool: Path,
    graph: Path,
    updates: Path,
    partition_vertices: int,
    host_repeats: int,
) -> dict[str, Any]:
    command = [
        str(host_tool.resolve()),
        str(graph.resolve()),
        str(updates.resolve()),
        "1",
        str(partition_vertices),
        str(host_repeats),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"host benchmark failed with rc={completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def update_traffic(raw: dict[str, Any]) -> dict[str, Any]:
    traffic = raw.get("update_backend_traffic", raw.get("backend_traffic"))
    if not isinstance(traffic, dict):
        return {"combined": {"requests": 0, "bytes": 0}}
    return traffic


def pure_result(
    raw: dict[str, Any],
    *,
    system: str,
    updates: int,
    calibration_scale: float,
    calibration_component: str,
) -> dict[str, Any]:
    if system == "spine":
        cycles = int(raw.get("maintenance_cycles", raw.get("update_cycles", 0)))
        mode = "spine_maintenance_from_current_direct_run"
    else:
        cycles = int(raw.get("update_cycles", 0))
        mode = "grasu_update_from_current_direct_update_only_run"
    correctness = int(raw.get("correctness_mismatches", 0))
    correctness += int(raw.get("architecture_correctness_mismatches", 0))
    correctness += int(raw.get("mathematical_correctness_mismatches", 0))
    calibrated_cycles = max(1, round(cycles * calibration_scale))
    return {
        "success": bool(raw.get("success", False)),
        "mode": mode,
        "measurement_window": "pure_update_only",
        "graph_compute_executed": False,
        "resident_state_persistent": True,
        "core_mhz": float(raw["core_mhz"]),
        "logical_updates": updates,
        "batch_count": 1,
        "device_cycles": calibrated_cycles,
        "raw_device_cycles": cycles,
        "calibrated_device_cycles": calibrated_cycles,
        "device_cycle_calibration_scale": calibration_scale,
        "device_cycle_calibration_component": calibration_component,
        "correctness_mismatches": correctness,
        "backend_traffic": update_traffic(raw),
        "source_measurement_window": raw.get("measurement_window", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materialization-manifest", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dataset-key", required=True)
    parser.add_argument("--updates", type=int, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--host-tool", type=Path, default=DEFAULT_HOST_TOOL)
    parser.add_argument("--host-repeats", type=int, default=3)
    parser.add_argument("--partition-vertices", type=int, default=65536)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=DEFAULT_LIB_DIR)
    parser.add_argument("--spine-profile", type=Path, default=DEFAULT_SPINE_PROFILE)
    parser.add_argument("--grasu-profile", type=Path, default=DEFAULT_GRASU_PROFILE)
    parser.add_argument(
        "--capability-catalog", type=Path, default=DEFAULT_CAPABILITY_CATALOG
    )
    parser.add_argument("--case-contract", type=Path, default=DEFAULT_CASE_CONTRACT)
    parser.add_argument(
        "--calibration-contract", type=Path, default=DEFAULT_CALIBRATION_CONTRACT
    )
    parser.add_argument(
        "--frozen-models-dir", type=Path, default=DEFAULT_FROZEN_MODELS
    )
    parser.add_argument("--max-cycles", type=int, default=10_000_000_000)
    parser.add_argument("--h2d-gbps", type=float, default=12.0)
    parser.add_argument("--launch-sync-us", type=float, default=10.0)
    args = parser.parse_args()
    if args.updates <= 0:
        raise ValueError("updates must be positive")

    case_contract_path = args.case_contract.resolve()
    calibration_contract_path = args.calibration_contract.resolve()
    case_contract = load_json(case_contract_path)
    calibration_contract = load_json(calibration_contract_path)
    if (
        case_contract.get("calibration_contract_id")
        != calibration_contract.get("contract_id")
    ):
        raise ValueError("case and calibration contracts disagree")
    plugin = args.lib_dir.resolve() / "libspine_cycle.so"
    plugin_sha256 = sha256_file(plugin)
    if plugin_sha256 != calibration_contract["simulator_plugin"]["sha256"]:
        raise ValueError("Fig. 8 plugin does not match the frozen contract")
    component_models, frozen_model_evidence = load_frozen_scale_models(
        args.frozen_models_dir,
        kind="component",
        contract_id=str(calibration_contract["contract_id"]),
        contract_sha256=sha256_file(calibration_contract_path),
        cases_sha256=sha256_file(case_contract_path),
        plugin_sha256=plugin_sha256,
    )
    spine_profile_payload = load_json(args.spine_profile.resolve())
    grasu_profile_payload = load_json(args.grasu_profile.resolve())
    spine_model = component_models[
        (
            "spine",
            "weighted_sssp",
            str(spine_profile_payload["profile_id"]),
            "maintenance",
        )
    ]
    grasu_model = component_models[
        (
            "grasu_regraph",
            "weighted_sssp",
            str(grasu_profile_payload["profile_id"]),
            "update_event",
        )
    ]

    materialization = load_json(args.materialization_manifest.resolve())
    graph = Path(str(materialization["graphs"]["directed"]["path"]))
    source_cohorts = materialization["graphs"]["directed"].get("source_cohorts", {})
    source = int(source_cohorts.get("update_only", source_cohorts.get("default", 0)))
    update_paths = directed_insert_updates(materialization)
    if args.updates not in update_paths:
        raise ValueError(f"missing directed insert update slice for {args.updates}")
    update = update_paths[args.updates]
    out = args.out_dir.resolve()

    host = run_host_benchmark(
        host_tool=args.host_tool,
        graph=graph,
        updates=update,
        partition_vertices=args.partition_vertices,
        host_repeats=args.host_repeats,
    )
    spine_dir = out / "spine_raw"
    grasu_dir = out / "grasu_raw"
    shutil.rmtree(spine_dir, ignore_errors=True)
    shutil.rmtree(grasu_dir, ignore_errors=True)
    spine_command = [
        sys.executable,
        str(ROOT / "scripts/run_sst_spine_vertical.py"),
        "--out-dir",
        str(spine_dir),
        "--sst",
        str(args.sst.resolve()),
        "--lib-dir",
        str(args.lib_dir.resolve()),
        "--no-build",
        "--profile",
        str(args.spine_profile.resolve()),
        "--scenario",
        "candidate10_maintenance",
        "--workload",
        str(update.resolve()),
        "--max-cycles",
        str(args.max_cycles),
    ]
    grasu_command = [
        sys.executable,
        str(ROOT / "scripts/run_sst_grasu_regraph_hls_weighted.py"),
        "--out-dir",
        str(grasu_dir),
        "--sst",
        str(args.sst.resolve()),
        "--lib-dir",
        str(args.lib_dir.resolve()),
        "--no-build",
        "--profile",
        str(args.grasu_profile.resolve()),
        "--workload",
        str(graph.resolve()),
        "--update-workload",
        str(update.resolve()),
        "--source",
        str(source),
        "--max-cycles",
        str(args.max_cycles),
        "--capability-catalog",
        str(args.capability_catalog.resolve()),
        "--update-only",
    ]
    run_command(
        spine_command,
        ROOT,
        out / "spine_raw.log",
        allow_success_result=spine_dir / "result.json",
        expected_mode="spine_maintenance",
    )
    run_command(grasu_command, ROOT, out / "grasu_raw.log")
    spine_raw = load_json(spine_dir / "result.json")
    grasu_raw = load_json(grasu_dir / "result.json")
    spine = pure_result(
        spine_raw,
        system="spine",
        updates=args.updates,
        calibration_scale=spine_model.scale,
        calibration_component="maintenance",
    )
    grasu = pure_result(
        grasu_raw,
        system="grasu",
        updates=args.updates,
        calibration_scale=grasu_model.scale,
        calibration_component="update_event",
    )
    comparison = analyze_persistent_update_pair(
        dataset_id=args.dataset_id,
        scenario="insert",
        host=host,
        spine_result=spine,
        grasu_result=grasu,
        runtime=HostRuntimeModel(args.h2d_gbps, args.launch_sync_us),
    )
    write_json(out / "host.json", host)
    write_json(out / "spine.json", spine)
    write_json(out / "grasu.json", grasu)
    write_json(out / "comparison.json", comparison)
    write_json(
        out / "manifest.json",
        {
            "schema_version": 1,
            "status": "PASS",
            "dataset_id": args.dataset_id,
            "dataset_key": args.dataset_key,
            "updates": args.updates,
            "source": source,
            "materialization_manifest": str(args.materialization_manifest.resolve()),
            "graph": str(graph.resolve()),
            "update_workload": str(update.resolve()),
            "sst_plugin": str(plugin),
            "sst_plugin_sha256": plugin_sha256,
            "case_contract": str(case_contract_path),
            "case_contract_sha256": sha256_file(case_contract_path),
            "calibration_contract": str(calibration_contract_path),
            "calibration_contract_sha256": sha256_file(
                calibration_contract_path
            ),
            "frozen_component_models": frozen_model_evidence,
            "spine_profile_id": spine_profile_payload["profile_id"],
            "spine_profile_sha256": sha256_file(args.spine_profile.resolve()),
            "grasu_profile_id": grasu_profile_payload["profile_id"],
            "grasu_profile_sha256": sha256_file(args.grasu_profile.resolve()),
            "capability_catalog": str(args.capability_catalog.resolve()),
            "capability_catalog_sha256": sha256_file(
                args.capability_catalog.resolve()
            ),
            "timing_boundary": (
                "measured_host_preprocessing_plus_explicit_transfer_launch_model_"
                "plus_calibrated_device_cycles"
            ),
            "h2d_gbps": args.h2d_gbps,
            "launch_sync_us": args.launch_sync_us,
            "spine_command": spine_command,
            "grasu_command": grasu_command,
        },
    )
    speedup = comparison["spine_speedup"]["modeled_host_inclusive"]
    print(
        f"PASS FIG8_CURRENT_CASE {args.dataset_id} u{args.updates} "
        f"speedup={speedup:.3f} out={out}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
