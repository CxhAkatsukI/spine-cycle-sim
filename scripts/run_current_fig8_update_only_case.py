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
DEFAULT_HOST_TOOL = (
    Path("/data/tmp/chuxiao/spine-cycle-sim-sharded-k4-v3-build")
    / "cpp"
    / "persistent_update_host_benchmark"
)
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
DEFAULT_SPINE_LIB_DIR = ROOT / "cpp/sst/build/sst-current-fpga-v12"
DEFAULT_GRASU_LIB_DIR = ROOT / "cpp/sst/build/sst-current-fpga-v19"
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
    ROOT / "configs/contracts/evaluation_refresh_fpga_cases_v7.json"
)
DEFAULT_SPINE_CALIBRATION_CONTRACT = (
    ROOT / "configs/contracts/current_fpga_spine_mechanism_components_v15.json"
)
DEFAULT_GRASU_CALIBRATION_CONTRACT = (
    ROOT / "configs/contracts/current_fpga_grasu_persistent_update_v19.json"
)
DEFAULT_GRASU_FROZEN_MODEL = (
    ROOT
    / "docs/evaluation_refresh_20260810/"
    "calibration_v19_grasu_persistent_update_frozen/frozen_model.json"
)
DEFAULT_SPINE_FROZEN_MODEL = (
    ROOT
    / "docs/evaluation_refresh_20260810/calibration_v15_frozen"
    / "frozen_spine_mechanism_component_models.json"
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
    calibration_fixed_cycles: float = 0.0,
    calibration_additive_cycles: float = 0.0,
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
    calibrated_cycles = max(
        1,
        round(
            calibration_fixed_cycles
            + cycles * calibration_scale
            + calibration_additive_cycles
        ),
    )
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
        "device_cycle_calibration_fixed_cycles": calibration_fixed_cycles,
        "device_cycle_calibration_additive_cycles": calibration_additive_cycles,
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
    parser.add_argument(
        "--spine-lib-dir", type=Path, default=DEFAULT_SPINE_LIB_DIR
    )
    parser.add_argument(
        "--grasu-lib-dir", type=Path, default=DEFAULT_GRASU_LIB_DIR
    )
    parser.add_argument("--spine-profile", type=Path, default=DEFAULT_SPINE_PROFILE)
    parser.add_argument("--grasu-profile", type=Path, default=DEFAULT_GRASU_PROFILE)
    parser.add_argument(
        "--capability-catalog", type=Path, default=DEFAULT_CAPABILITY_CATALOG
    )
    parser.add_argument("--case-contract", type=Path, default=DEFAULT_CASE_CONTRACT)
    parser.add_argument(
        "--spine-calibration-contract",
        type=Path,
        default=DEFAULT_SPINE_CALIBRATION_CONTRACT,
    )
    parser.add_argument(
        "--grasu-calibration-contract",
        type=Path,
        default=DEFAULT_GRASU_CALIBRATION_CONTRACT,
    )
    parser.add_argument(
        "--grasu-frozen-model", type=Path, default=DEFAULT_GRASU_FROZEN_MODEL
    )
    parser.add_argument(
        "--spine-frozen-model", type=Path, default=DEFAULT_SPINE_FROZEN_MODEL
    )
    parser.add_argument("--max-cycles", type=int, default=10_000_000_000)
    parser.add_argument("--h2d-gbps", type=float, default=12.0)
    parser.add_argument("--launch-sync-us", type=float, default=10.0)
    args = parser.parse_args()
    if args.updates <= 0:
        raise ValueError("updates must be positive")

    case_contract_path = args.case_contract.resolve()
    spine_contract_path = args.spine_calibration_contract.resolve()
    grasu_contract_path = args.grasu_calibration_contract.resolve()
    case_contract = load_json(case_contract_path)
    spine_contract = load_json(spine_contract_path)
    grasu_contract = load_json(grasu_contract_path)
    spine_plugin = args.spine_lib_dir.resolve() / "libspine_cycle.so"
    grasu_plugin = args.grasu_lib_dir.resolve() / "libspine_cycle.so"
    spine_plugin_sha256 = sha256_file(spine_plugin)
    grasu_plugin_sha256 = sha256_file(grasu_plugin)
    if spine_plugin_sha256 != spine_contract["simulator_plugin"]["sha256"]:
        raise ValueError("Fig. 8 Spine plugin does not match the v15 contract")
    if grasu_plugin_sha256 != grasu_contract["plugin"]["sha256"]:
        raise ValueError("Fig. 8 G+R plugin does not match the v19 contract")
    if sha256_file(case_contract_path) != grasu_contract["case_contract"]["sha256"]:
        raise ValueError("Fig. 8 case contract does not match G+R v19")
    spine_frozen_path = args.spine_frozen_model.resolve()
    spine_frozen = load_json(spine_frozen_path)
    if spine_frozen.get("status") != "FROZEN_BEFORE_HOLDOUT":
        raise ValueError("Fig. 8 Spine mechanism model is not frozen")
    if spine_frozen.get("holdout_used_for_fit") is not False:
        raise ValueError("Fig. 8 Spine mechanism model used holdout data")
    if spine_frozen.get("contract_id") != (
        "current_fpga_spine_mechanism_components_v15_20260812"
    ):
        raise ValueError("Fig. 8 Spine mechanism model contract is not v15")
    spine_models = spine_frozen.get("models")
    if not isinstance(spine_models, dict):
        raise ValueError("Fig. 8 Spine mechanism model payload is missing")
    spine_profile_payload = load_json(args.spine_profile.resolve())
    grasu_profile_payload = load_json(args.grasu_profile.resolve())
    spine_model = spine_models.get("weighted_sssp")
    if not isinstance(spine_model, dict):
        raise ValueError("Fig. 8 frozen Spine SSSP model is missing")
    if spine_model.get("profile_id") != spine_profile_payload["profile_id"]:
        raise ValueError("Fig. 8 frozen Spine profile does not match the run")
    grasu_frozen_path = args.grasu_frozen_model.resolve()
    grasu_frozen = load_json(grasu_frozen_path)
    if grasu_frozen.get("status") != "FROZEN_BEFORE_TRANSFER_OBSERVATION":
        raise ValueError("Fig. 8 G+R persistent update model is not frozen")
    if grasu_frozen.get("contract_id") != grasu_contract.get("contract_id"):
        raise ValueError("Fig. 8 G+R frozen model contract mismatch")
    grasu_model = next(
        (
            row
            for row in grasu_frozen.get("models", [])
            if row.get("algorithm") == "weighted_sssp"
            and row.get("profile_id") == grasu_profile_payload["profile_id"]
        ),
        None,
    )
    if not isinstance(grasu_model, dict):
        raise ValueError("Fig. 8 frozen G+R SSSP persistent update model is missing")

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
        str(args.spine_lib_dir.resolve()),
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
        str(args.grasu_lib_dir.resolve()),
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
    grasu_observability = grasu_raw.get("update_observability")
    if not isinstance(grasu_observability, dict):
        raise ValueError("Fig. 8 G+R update observability is missing")
    nonempty_destination_shards = int(
        grasu_observability["destination_partitions_touched"]
    )
    control_cycles_per_shard = float(
        grasu_model["control_cycles_per_nonempty_shard"]
    )
    spine = pure_result(
        spine_raw,
        system="spine",
        updates=args.updates,
        calibration_scale=float(spine_model["maintenance_simulator_scale"]),
        calibration_fixed_cycles=float(spine_model["maintenance_fixed_cycles"]),
        calibration_component="maintenance",
    )
    grasu = pure_result(
        grasu_raw,
        system="grasu",
        updates=args.updates,
        calibration_scale=1.0,
        calibration_additive_cycles=(
            control_cycles_per_shard * nonempty_destination_shards
        ),
        calibration_component=(
            "persistent_warm_update_raw_plus_nonempty_destination_shard_envelope"
        ),
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
            "spine_sst_plugin": str(spine_plugin),
            "spine_sst_plugin_sha256": spine_plugin_sha256,
            "grasu_sst_plugin": str(grasu_plugin),
            "grasu_sst_plugin_sha256": grasu_plugin_sha256,
            "case_contract": str(case_contract_path),
            "case_contract_sha256": sha256_file(case_contract_path),
            "spine_calibration_contract": str(spine_contract_path),
            "spine_calibration_contract_sha256": sha256_file(spine_contract_path),
            "grasu_calibration_contract": str(grasu_contract_path),
            "grasu_calibration_contract_sha256": sha256_file(grasu_contract_path),
            "grasu_frozen_persistent_update_model": str(grasu_frozen_path),
            "grasu_frozen_persistent_update_model_sha256": sha256_file(
                grasu_frozen_path
            ),
            "grasu_control_cycles_per_nonempty_shard": control_cycles_per_shard,
            "grasu_nonempty_destination_shards": nonempty_destination_shards,
            "spine_frozen_mechanism_model": str(spine_frozen_path),
            "spine_frozen_mechanism_model_sha256": sha256_file(
                spine_frozen_path
            ),
            "spine_frozen_mechanism_contract_id": spine_frozen.get(
                "contract_id"
            ),
            "spine_frozen_mechanism_holdout_used_for_fit": spine_frozen.get(
                "holdout_used_for_fit"
            ),
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
                "plus_frozen_calibrated_persistent_device_cycles"
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
