#!/usr/bin/env python3
"""Run the current sharded-K4 G+R calibration matrix with a frozen plugin."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SIMULATION_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v11_20260812"
)
DEFAULT_LIBRARY = ROOT / "cpp/sst/build/sst-current-fpga-v11"
CAPABILITY_CATALOG = (
    ROOT / "configs/contracts/grasu_regraph_sharded_k4_hls_capabilities_v8.json"
)
DATASETS = ("au", "su", "wk", "r19")
ALGORITHMS = (
    "weighted_sssp",
    "connected_components",
    "thresholded_residual_pagerank",
)
SOURCE = {"au": 11, "su": 23, "wk": 0, "r19": 113}
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
OUTPUT_DIRECTORY = {
    "weighted_sssp": "weighted_sssp_unified6739_v1",
    "connected_components": "connected_components_unified6739_v1",
    "thresholded_residual_pagerank": (
        "thresholded_residual_pagerank_unified6739_v1"
    ),
}
WORKLOAD_TAG = {
    "weighted_sssp": "weighted_sssp",
    "connected_components": "connected_components",
    "thresholded_residual_pagerank": "residual_pagerank",
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def available_gib() -> float:
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / (1024.0 * 1024.0)
    raise RuntimeError("/proc/meminfo does not report MemAvailable")


def wait_for_memory(reserve_gib: float, poll_seconds: float) -> None:
    while True:
        available = available_gib()
        if available >= reserve_gib:
            return
        print(
            f"MEMORY_WAIT available={available:.1f}GiB reserve={reserve_gib:.1f}GiB",
            flush=True,
        )
        time.sleep(poll_seconds)


def workload_paths(
    simulation_root: Path, dataset: str, algorithm: str
) -> tuple[Path, Path]:
    stem = f"{dataset}_{WORKLOAD_TAG[algorithm]}_insert_u8"
    workload_root = simulation_root / "workloads"
    return (
        workload_root / f"{stem}.initial.slice",
        workload_root / f"{stem}.update.slice",
    )


def output_directory(
    simulation_root: Path, dataset: str, algorithm: str
) -> Path:
    return (
        simulation_root
        / "runs_current_v1"
        / dataset
        / "grasu_regraph"
        / OUTPUT_DIRECTORY[algorithm]
    )


def build_command(
    simulation_root: Path,
    library: Path,
    dataset: str,
    algorithm: str,
) -> list[str]:
    workload, update = workload_paths(simulation_root, dataset, algorithm)
    out_dir = output_directory(simulation_root, dataset, algorithm)
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
        str(out_dir),
        "--lib-dir",
        str(library),
        "--max-cycles",
        "2000000000",
        "--downstream-sharing",
        "shared",
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
    if algorithm == "thresholded_residual_pagerank":
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
    return [
        sys.executable,
        str(ROOT / "scripts/run_sst_connected_components.py"),
        "--architecture",
        "grasu",
        *common,
        "--hardware-full-recompute",
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


def valid_existing_result(out_dir: Path, profile: Path, plugin: Path) -> bool:
    manifest = manifest_path(out_dir)
    if manifest is None or not (out_dir / "result.json").is_file():
        return False
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    return (
        payload.get("status") == "PASS"
        and payload.get("sst_plugin_sha256") == sha256_file(plugin)
        and payload.get("profile_sha256") == sha256_file(profile)
    )


def write_status(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    temporary.replace(path)


def run_one(
    simulation_root: Path,
    library: Path,
    dataset: str,
    algorithm: str,
    reserve_gib: float,
    poll_seconds: float,
    status: dict[str, Any],
    status_path: Path,
    lock: threading.Lock,
) -> tuple[str, bool, str]:
    task_id = f"{dataset}:{algorithm}"
    out_dir = output_directory(simulation_root, dataset, algorithm)
    plugin = library / "libspine_cycle.so"
    if valid_existing_result(out_dir, PROFILE[algorithm], plugin):
        with lock:
            status["tasks"][task_id] = {"state": "PASS", "reused": True}
            write_status(status_path, status)
        return task_id, True, "reused"

    wait_for_memory(reserve_gib, poll_seconds)
    out_dir.mkdir(parents=True, exist_ok=True)
    command = build_command(simulation_root, library, dataset, algorithm)
    with lock:
        status["tasks"][task_id] = {
            "state": "RUNNING",
            "command": command,
            "started_unix": time.time(),
        }
        write_status(status_path, status)
    start = time.monotonic()
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
    elapsed = time.monotonic() - start
    passed = completed.returncode == 0 and valid_existing_result(
        out_dir, PROFILE[algorithm], plugin
    )
    with lock:
        status["tasks"][task_id] = {
            "state": "PASS" if passed else "FAIL",
            "returncode": completed.returncode,
            "elapsed_seconds": elapsed,
            "log": str(log_path),
        }
        write_status(status_path, status)
    return task_id, passed, str(log_path)


def run_group(
    tasks: list[tuple[str, str]],
    *,
    jobs: int,
    simulation_root: Path,
    library: Path,
    reserve_gib: float,
    poll_seconds: float,
    status: dict[str, Any],
    status_path: Path,
    lock: threading.Lock,
) -> bool:
    passed = True
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = [
            executor.submit(
                run_one,
                simulation_root,
                library,
                dataset,
                algorithm,
                reserve_gib,
                poll_seconds,
                status,
                status_path,
                lock,
            )
            for dataset, algorithm in tasks
        ]
        for future in as_completed(futures):
            task_id, task_passed, detail = future.result()
            print(
                f"MATRIX_{'PASS' if task_passed else 'FAIL'} {task_id} {detail}",
                flush=True,
            )
            passed = passed and task_passed
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--simulation-root", type=Path, default=DEFAULT_SIMULATION_ROOT)
    parser.add_argument("--lib-dir", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--memory-reserve-gib", type=float, default=64.0)
    parser.add_argument("--memory-poll-seconds", type=float, default=10.0)
    parser.add_argument("--dataset", action="append", choices=DATASETS)
    parser.add_argument("--algorithm", action="append", choices=ALGORITHMS)
    args = parser.parse_args()

    simulation_root = args.simulation_root.resolve()
    library = args.lib_dir.resolve()
    plugin = library / "libspine_cycle.so"
    if not plugin.is_file():
        raise SystemExit(f"missing frozen plugin: {plugin}")
    datasets = tuple(args.dataset or DATASETS)
    algorithms = tuple(args.algorithm or ALGORITHMS)
    for dataset in datasets:
        for algorithm in algorithms:
            for path in workload_paths(simulation_root, dataset, algorithm):
                if not path.is_file():
                    raise SystemExit(f"missing workload: {path}")

    status_path = simulation_root / "grasu_unified_plugin_matrix_status.json"
    status: dict[str, Any] = {
        "schema_version": 1,
        "plugin": str(plugin),
        "plugin_sha256": sha256_file(plugin),
        "memory_reserve_gib": args.memory_reserve_gib,
        "tasks": {},
    }
    lock = threading.Lock()
    write_status(status_path, status)
    small = [
        (dataset, algorithm)
        for dataset in datasets
        if dataset != "r19"
        for algorithm in algorithms
    ]
    large = [
        (dataset, algorithm)
        for dataset in datasets
        if dataset == "r19"
        for algorithm in algorithms
    ]
    passed = run_group(
        small,
        jobs=max(1, args.jobs),
        simulation_root=simulation_root,
        library=library,
        reserve_gib=args.memory_reserve_gib,
        poll_seconds=args.memory_poll_seconds,
        status=status,
        status_path=status_path,
        lock=lock,
    )
    passed = run_group(
        large,
        jobs=1,
        simulation_root=simulation_root,
        library=library,
        reserve_gib=args.memory_reserve_gib,
        poll_seconds=args.memory_poll_seconds,
        status=status,
        status_path=status_path,
        lock=lock,
    ) and passed
    print(
        f"GRASU_UNIFIED_MATRIX_{'PASS' if passed else 'FAIL'} status={status_path}",
        flush=True,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
