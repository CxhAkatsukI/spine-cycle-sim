#!/usr/bin/env python3
"""Replay current G+R update phases for control-envelope observability."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v13_update_observability_20260812"
)
DEFAULT_WORKLOAD_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_exact_20260811/workloads"
)
DEFAULT_LIBRARY = ROOT / "cpp/sst/build/sst-current-fpga-v13"
CAPABILITY_CATALOG = (
    ROOT / "configs/contracts/grasu_regraph_sharded_k4_hls_capabilities_v8.json"
)
ROLE_DATASETS = {
    "calibration": ("au", "su"),
    "holdout": ("wk", "r19"),
}
ALGORITHMS = (
    "weighted_sssp",
    "connected_components",
    "thresholded_residual_pagerank",
)
SOURCE = {"au": 11, "su": 23, "wk": 0, "r19": 113}
WORKLOAD_TAG = {
    "weighted_sssp": "weighted_sssp",
    "connected_components": "connected_components",
    "thresholded_residual_pagerank": "residual_pagerank",
}
PROFILE = {
    "weighted_sssp": (
        ROOT / "configs/architectures/grasu_regraph_sharded_k4_weighted_hls_v8.json"
    ),
    "connected_components": (
        ROOT / "configs/architectures/grasu_regraph_sharded_k4_cc_hls_v8.json"
    ),
    "thresholded_residual_pagerank": (
        ROOT / "configs/architectures/grasu_regraph_sharded_k4_residual_hls_v8.json"
    ),
}


def available_gib() -> float:
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / (1024.0 * 1024.0)
    raise RuntimeError("/proc/meminfo does not report MemAvailable")


def wait_for_memory(reserve_gib: float, poll_seconds: float) -> None:
    while available_gib() < reserve_gib:
        print(
            f"MEMORY_WAIT available={available_gib():.1f}GiB "
            f"reserve={reserve_gib:.1f}GiB",
            flush=True,
        )
        time.sleep(poll_seconds)


def workload_paths(
    workload_root: Path, dataset: str, algorithm: str
) -> tuple[Path, Path]:
    stem = f"{dataset}_{WORKLOAD_TAG[algorithm]}_insert_u8"
    return workload_root / f"{stem}.initial.slice", workload_root / f"{stem}.update.slice"


def output_directory(
    output_root: Path, role: str, dataset: str, algorithm: str
) -> Path:
    return output_root / role / dataset / algorithm


def build_command(
    workload_root: Path,
    output_root: Path,
    library: Path,
    role: str,
    dataset: str,
    algorithm: str,
) -> list[str]:
    workload, update = workload_paths(workload_root, dataset, algorithm)
    common = [
        "--profile",
        str(PROFILE[algorithm]),
        "--capability-catalog",
        str(CAPABILITY_CATALOG),
        "--workload",
        str(workload),
        "--update-workload",
        str(update),
        "--out-dir",
        str(output_directory(output_root, role, dataset, algorithm)),
        "--lib-dir",
        str(library),
        "--max-cycles",
        "2000000000",
        "--downstream-sharing",
        "shared",
        "--update-only",
        "--no-build",
    ]
    if algorithm == "weighted_sssp":
        return [
            sys.executable,
            str(ROOT / "scripts/run_sst_grasu_regraph_hls_weighted.py"),
            *common,
            "--source",
            str(SOURCE[dataset]),
        ]
    if algorithm == "connected_components":
        return [
            sys.executable,
            str(ROOT / "scripts/run_sst_connected_components.py"),
            "--architecture",
            "grasu",
            *common,
        ]
    return [
        sys.executable,
        str(ROOT / "scripts/run_sst_grasu_regraph_hls_residual_pagerank.py"),
        *common,
        "--residual-contract",
        "grasu_hardware_warm_dangling_linf",
        "--pagerank-epsilon",
        "1e-6",
        "--residual-max-iterations",
        "256",
    ]


def manifest_path(out_dir: Path) -> Path | None:
    return next(
        (
            path
            for path in (out_dir / "run_manifest.json", out_dir / "manifest.json")
            if path.is_file()
        ),
        None,
    )


def valid_result(out_dir: Path, plugin_sha256: str) -> bool:
    manifest = manifest_path(out_dir)
    result_path = out_dir / "result.json"
    if manifest is None or not result_path.is_file():
        return False
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    observability = result.get("update_observability")
    manifest_update_only = (
        manifest_payload.get("update_only") is True
        or (
            manifest_payload.get("measurement_window") == "pure_update_only"
            and manifest_payload.get("graph_compute_executed") is False
        )
    )
    return (
        manifest_payload.get("status") == "PASS"
        and manifest_update_only
        and manifest_payload.get("sst_plugin_sha256") == plugin_sha256
        and result.get("success") is True
        and result.get("measurement_window") == "pure_update_only"
        and result.get("compute_cycles") == 0
        and result.get("memory_locality_ledger_match") is True
        and result.get("correctness_mismatches") == 0
        and isinstance(observability, dict)
        and observability.get("end_cycle", 0) > observability.get("start_cycle", 0)
    )


def write_status(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    temporary.replace(path)


def run_one(
    *,
    workload_root: Path,
    output_root: Path,
    library: Path,
    plugin_sha256: str,
    role: str,
    dataset: str,
    algorithm: str,
    reserve_gib: float,
    poll_seconds: float,
    status: dict[str, Any],
    status_path: Path,
    lock: threading.Lock,
) -> tuple[str, bool, str]:
    task_id = f"{dataset}:{algorithm}"
    out_dir = output_directory(output_root, role, dataset, algorithm)
    if valid_result(out_dir, plugin_sha256):
        return task_id, True, "reused"
    wait_for_memory(reserve_gib, poll_seconds)
    out_dir.mkdir(parents=True, exist_ok=True)
    command = build_command(
        workload_root, output_root, library, role, dataset, algorithm
    )
    with lock:
        status["tasks"][task_id] = {
            "state": "RUNNING",
            "command": command,
            "started_unix": time.time(),
        }
        write_status(status_path, status)
    started = time.monotonic()
    log_path = out_dir / "matrix_driver.log"
    with log_path.open("w", encoding="utf-8") as sink:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            stdout=sink,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )
    elapsed = time.monotonic() - started
    passed = completed.returncode == 0 and valid_result(out_dir, plugin_sha256)
    with lock:
        status["tasks"][task_id] = {
            "state": "PASS" if passed else "FAIL",
            "returncode": completed.returncode,
            "elapsed_seconds": elapsed,
            "log": str(log_path),
        }
        write_status(status_path, status)
    return task_id, passed, str(log_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=tuple(ROLE_DATASETS), required=True)
    parser.add_argument("--workload-root", type=Path, default=DEFAULT_WORKLOAD_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--lib-dir", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--memory-reserve-gib", type=float, default=64.0)
    parser.add_argument("--memory-poll-seconds", type=float, default=10.0)
    parser.add_argument("--dataset", action="append")
    parser.add_argument("--algorithm", action="append", choices=ALGORITHMS)
    args = parser.parse_args()

    if args.jobs <= 0 or args.memory_reserve_gib <= 0:
        raise ValueError("jobs and memory reserve must be positive")
    role_datasets = ROLE_DATASETS[args.role]
    datasets = tuple(args.dataset or role_datasets)
    if any(dataset not in role_datasets for dataset in datasets):
        raise ValueError(f"{args.role} runner cannot execute non-{args.role} datasets")
    algorithms = tuple(args.algorithm or ALGORITHMS)
    workload_root = args.workload_root.resolve()
    output_root = args.out_root.resolve()
    library = args.lib_dir.resolve()
    plugin = library / "libspine_cycle.so"
    if not plugin.is_file():
        raise FileNotFoundError(plugin)
    import hashlib

    plugin_sha256 = hashlib.sha256(plugin.read_bytes()).hexdigest()
    for dataset in datasets:
        for algorithm in algorithms:
            for path in workload_paths(workload_root, dataset, algorithm):
                if not path.is_file():
                    raise FileNotFoundError(path)

    status_path = output_root / f"{args.role}_status.json"
    status: dict[str, Any] = {
        "schema_version": 1,
        "role": args.role,
        "plugin": str(plugin),
        "plugin_sha256": plugin_sha256,
        "workload_root": str(workload_root),
        "memory_reserve_gib": args.memory_reserve_gib,
        "tasks": {},
    }
    output_root.mkdir(parents=True, exist_ok=True)
    write_status(status_path, status)
    lock = threading.Lock()
    passed = True
    tasks = [(dataset, algorithm) for dataset in datasets for algorithm in algorithms]
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [
            executor.submit(
                run_one,
                workload_root=workload_root,
                output_root=output_root,
                library=library,
                plugin_sha256=plugin_sha256,
                role=args.role,
                dataset=dataset,
                algorithm=algorithm,
                reserve_gib=args.memory_reserve_gib,
                poll_seconds=args.memory_poll_seconds,
                status=status,
                status_path=status_path,
                lock=lock,
            )
            for dataset, algorithm in tasks
        ]
        for future in as_completed(futures):
            task_id, task_passed, detail = future.result()
            print(
                f"OBSERVABILITY_{'PASS' if task_passed else 'FAIL'} "
                f"{task_id} {detail}",
                flush=True,
            )
            passed = passed and task_passed
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
