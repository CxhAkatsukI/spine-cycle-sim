#!/usr/bin/env python3
"""Run the frozen current-model matrix used by evaluation-refresh Fig. 8."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATERIALIZATION_ROOT = Path(
    "/data/tmp/chuxiao/large_graph_campaign_v1/workloads"
)
DEFAULT_EVIDENCE_ROOT = Path(
    "/data/tmp/chuxiao/evaluation_refresh_current_fpga_v15_fig8_20260812"
)
DEFAULT_FROZEN_MODELS = (
    ROOT / "docs/evaluation_refresh_20260810/calibration_v12_frozen"
)
DEFAULT_SPINE_FROZEN_MODEL = (
    ROOT
    / "docs/evaluation_refresh_20260810/calibration_v15_frozen"
    / "frozen_spine_mechanism_component_models.json"
)
DATASETS = (
    ("au", "AU", "sx_askubuntu"),
    ("su", "SU", "sx_superuser"),
    ("wk", "WK", "wiki_talk_temporal"),
    ("so", "SO", "sx_stackoverflow"),
    ("pk", "PK", "soc_pokec"),
)
DEFAULT_BATCH_UPDATES = (64, 512, 4096)
DEFAULT_CROSS_UPDATES = 512


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
            f"MEMORY_WAIT available={available:.1f}GiB "
            f"reserve={reserve_gib:.1f}GiB",
            flush=True,
        )
        time.sleep(poll_seconds)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    temporary.replace(path)


def case_directory(evidence_root: Path, dataset_key: str, updates: int) -> Path:
    return evidence_root / "cases" / f"{dataset_key}_u{updates}"


def valid_case(path: Path) -> bool:
    manifest = path / "manifest.json"
    comparison = path / "comparison.json"
    if not manifest.is_file() or not comparison.is_file():
        return False
    return (
        load_json(manifest).get("status") == "PASS"
        and load_json(comparison).get("correctness") == "pass"
    )


def build_tasks(
    selected_dataset_keys: tuple[str, ...],
    cross_updates: int,
    batch_updates: tuple[int, ...],
) -> list[tuple[str, str, str, int]]:
    selected = [row for row in DATASETS if row[0] in selected_dataset_keys]
    tasks = [(key, label, dataset_id, cross_updates) for key, label, dataset_id in selected]
    if "au" in selected_dataset_keys:
        tasks.extend(
            ("au", "AU", "sx_askubuntu", updates) for updates in batch_updates
        )
    return list(dict.fromkeys(tasks))


def case_command(
    *,
    materialization_root: Path,
    evidence_root: Path,
    frozen_models: Path,
    spine_frozen_model: Path,
    dataset_key: str,
    dataset_id: str,
    updates: int,
) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "scripts/run_current_fig8_update_only_case.py"),
        "--materialization-manifest",
        str(materialization_root / dataset_id / "materialization_manifest.json"),
        "--dataset-id",
        dataset_id,
        "--dataset-key",
        dataset_key,
        "--updates",
        str(updates),
        "--out-dir",
        str(case_directory(evidence_root, dataset_key, updates)),
        "--frozen-models-dir",
        str(frozen_models),
        "--spine-frozen-model",
        str(spine_frozen_model),
    ]


def run_one(
    *,
    materialization_root: Path,
    evidence_root: Path,
    frozen_models: Path,
    spine_frozen_model: Path,
    dataset_key: str,
    dataset_id: str,
    updates: int,
    reserve_gib: float,
    poll_seconds: float,
    status: dict[str, Any],
    status_path: Path,
    lock: threading.Lock,
) -> tuple[str, bool, str]:
    task_id = f"{dataset_key}:u{updates}"
    out_dir = case_directory(evidence_root, dataset_key, updates)
    if valid_case(out_dir):
        with lock:
            status["tasks"][task_id] = {"state": "PASS", "reused": True}
            write_json(status_path, status)
        return task_id, True, "reused"

    wait_for_memory(reserve_gib, poll_seconds)
    out_dir.mkdir(parents=True, exist_ok=True)
    command = case_command(
        materialization_root=materialization_root,
        evidence_root=evidence_root,
        frozen_models=frozen_models,
        spine_frozen_model=spine_frozen_model,
        dataset_key=dataset_key,
        dataset_id=dataset_id,
        updates=updates,
    )
    with lock:
        status["tasks"][task_id] = {
            "state": "RUNNING",
            "command": command,
            "started_unix": time.time(),
        }
        write_json(status_path, status)
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
    passed = completed.returncode == 0 and valid_case(out_dir)
    with lock:
        status["tasks"][task_id] = {
            "state": "PASS" if passed else "FAIL",
            "returncode": completed.returncode,
            "elapsed_seconds": elapsed,
            "log": str(log_path),
        }
        write_json(status_path, status)
    return task_id, passed, str(log_path)


def publish_view(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() and link.resolve() == target.resolve():
        return
    if link.exists() or link.is_symlink():
        raise RuntimeError(f"refusing to replace existing Fig. 8 view: {link}")
    relative = os.path.relpath(target, start=link.parent)
    link.symlink_to(relative, target_is_directory=True)


def publish_views(
    evidence_root: Path,
    selected_dataset_keys: tuple[str, ...],
    cross_updates: int,
    batch_updates: tuple[int, ...],
) -> None:
    for key, _label, _dataset_id in DATASETS:
        if key not in selected_dataset_keys:
            continue
        publish_view(
            evidence_root / "cross_dataset" / key,
            case_directory(evidence_root, key, cross_updates),
        )
    if "au" in selected_dataset_keys:
        for updates in batch_updates:
            publish_view(
                evidence_root / "batch_sensitivity" / f"b{updates}",
                case_directory(evidence_root, "au", updates),
            )


def run_group(
    tasks: list[tuple[str, str, str, int]],
    *,
    jobs: int,
    kwargs: dict[str, Any],
) -> bool:
    passed = True
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as executor:
        futures = [
            executor.submit(
                run_one,
                dataset_key=key,
                dataset_id=dataset_id,
                updates=updates,
                **kwargs,
            )
            for key, _label, dataset_id, updates in tasks
        ]
        for future in as_completed(futures):
            task_id, task_passed, detail = future.result()
            print(
                f"FIG8_MATRIX_{'PASS' if task_passed else 'FAIL'} "
                f"{task_id} {detail}",
                flush=True,
            )
            passed = passed and task_passed
    return passed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--materialization-root", type=Path, default=DEFAULT_MATERIALIZATION_ROOT
    )
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE_ROOT)
    parser.add_argument("--frozen-models-dir", type=Path, default=DEFAULT_FROZEN_MODELS)
    parser.add_argument(
        "--spine-frozen-model", type=Path, default=DEFAULT_SPINE_FROZEN_MODEL
    )
    parser.add_argument("--dataset", action="append", choices=[row[0] for row in DATASETS])
    parser.add_argument("--cross-updates", type=int, default=DEFAULT_CROSS_UPDATES)
    parser.add_argument("--batch-updates", action="append", type=int)
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--memory-reserve-gib", type=float, default=64.0)
    parser.add_argument("--memory-poll-seconds", type=float, default=10.0)
    args = parser.parse_args()

    materialization_root = args.materialization_root.resolve()
    evidence_root = args.evidence_root.resolve()
    frozen_models = args.frozen_models_dir.resolve()
    spine_frozen_model = args.spine_frozen_model.resolve()
    selected_dataset_keys = tuple(args.dataset or [row[0] for row in DATASETS])
    batch_updates = tuple(args.batch_updates or DEFAULT_BATCH_UPDATES)
    if args.cross_updates <= 0 or any(value <= 0 for value in batch_updates):
        raise SystemExit("update counts must be positive")
    if not frozen_models.is_dir():
        raise SystemExit(
            f"missing frozen calibration; Fig. 8 must wait for: {frozen_models}"
        )
    if not spine_frozen_model.is_file():
        raise SystemExit(
            f"missing frozen Spine v15 model; Fig. 8 must wait for: "
            f"{spine_frozen_model}"
        )
    for key, _label, dataset_id in DATASETS:
        if key not in selected_dataset_keys:
            continue
        manifest = materialization_root / dataset_id / "materialization_manifest.json"
        if not manifest.is_file():
            raise SystemExit(f"missing materialization manifest: {manifest}")

    tasks = build_tasks(selected_dataset_keys, args.cross_updates, batch_updates)
    status_path = evidence_root / "matrix_status.json"
    status: dict[str, Any] = {
        "schema_version": 1,
        "status": "RUNNING",
        "timing_boundary": "setup_inclusive_update_only",
        "frozen_models_dir": str(frozen_models),
        "spine_frozen_model": str(spine_frozen_model),
        "cross_updates": args.cross_updates,
        "batch_updates": list(batch_updates),
        "memory_reserve_gib": args.memory_reserve_gib,
        "tasks": {},
    }
    write_json(status_path, status)
    lock = threading.Lock()
    kwargs = {
        "materialization_root": materialization_root,
        "evidence_root": evidence_root,
        "frozen_models": frozen_models,
        "spine_frozen_model": spine_frozen_model,
        "reserve_gib": args.memory_reserve_gib,
        "poll_seconds": args.memory_poll_seconds,
        "status": status,
        "status_path": status_path,
        "lock": lock,
    }
    compact = [task for task in tasks if task[0] in {"au", "su", "wk"}]
    large = [task for task in tasks if task[0] in {"so", "pk"}]
    passed = run_group(compact, jobs=args.jobs, kwargs=kwargs)
    passed = run_group(large, jobs=1, kwargs=kwargs) and passed
    if passed:
        publish_views(
            evidence_root,
            selected_dataset_keys,
            args.cross_updates,
            batch_updates,
        )
    status["status"] = "PASS" if passed else "FAIL"
    status["completed_unix"] = time.time()
    write_json(status_path, status)
    print(
        f"FIG8_CURRENT_MATRIX_{status['status']} tasks={len(tasks)} "
        f"status={status_path}",
        flush=True,
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
