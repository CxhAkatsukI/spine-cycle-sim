#!/usr/bin/env python3
"""Run the common real compact Full PageRank matrix on Spine and GraSU."""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.hls_pagerank_real_comparison import (  # noqa: E402
    pair_row,
    system_row,
    validate_grasu_pagerank_result,
    validate_spine_pagerank_result,
)
from spine_cycle_sim.experiments.real_small_batches import (  # noqa: E402
    validate_real_small_batch_manifest,
)
from spine_cycle_sim.experiments.shared_workloads import sha256_file  # noqa: E402


DEFAULT_INPUT_MANIFEST = (
    ROOT / "configs" / "experiments" / "hls_weighted_real_small_batches_20260726.json"
)
DEFAULT_SPINE_PROFILE = (
    ROOT / "configs" / "architectures" / "spine_shared_engine_9c08763.json"
)
DEFAULT_GRASU_PROFILE = (
    ROOT
    / "configs"
    / "architectures"
    / "grasu_regraph_weighted_pma_hls_proposed_pagerank_ff13a67.json"
)
DEFAULT_CAPABILITIES = (
    ROOT / "configs" / "contracts" / "grasu_regraph_capabilities_v1.json"
)
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
PAGERANK_ITERATIONS = 3
PAGERANK_DAMPING = 0.85


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    serialized = [
        {
            key: json.dumps(value, separators=(",", ":"))
            if isinstance(value, (tuple, list, dict))
            else value
            for key, value in row.items()
        }
        for row in rows
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(serialized[0]))
        writer.writeheader()
        writer.writerows(serialized)


def _profile(path: Path, expected_id: str) -> tuple[dict[str, object], float]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile.get("profile_id") != expected_id:
        raise ValueError(f"profile identity mismatch: {path}")
    clock_name = "data" if expected_id.startswith("spine_") else "kernel"
    clock = next(item for item in profile["clocks"] if item["name"] == clock_name)
    return profile, float(clock["achieved_mhz"])


def _select_runs(
    runs: list[dict[str, object]], run_ids: list[str], limit: int | None
) -> list[dict[str, object]]:
    known = {str(run["run_id"]) for run in runs}
    unknown = sorted(set(run_ids) - known)
    if unknown:
        raise ValueError(f"unknown PageRank comparison run IDs: {unknown}")
    selected = [run for run in runs if not run_ids or run["run_id"] in run_ids]
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        selected = selected[:limit]
    if not selected:
        raise ValueError("PageRank comparison selection is empty")
    return selected


def _command(
    run: Mapping[str, object],
    system: str,
    *,
    args: argparse.Namespace,
    out_dir: Path,
) -> list[str]:
    graph = ROOT / run["graph"]["path"]  # type: ignore[index]
    update = ROOT / run["update"]["path"]  # type: ignore[index]
    if system == "spine":
        return [
            args.python,
            str(ROOT / "scripts" / "run_sst_spine_vertical.py"),
            "--no-build",
            "--scenario",
            "full_pagerank",
            "--validation-mode",
            "generic",
            "--profile",
            str(args.spine_profile.resolve()),
            "--workload",
            str(graph.resolve()),
            "--update-workload",
            str(update.resolve()),
            "--pagerank-iterations",
            str(PAGERANK_ITERATIONS),
            "--pagerank-damping",
            str(PAGERANK_DAMPING),
            "--max-cycles",
            str(args.max_cycles),
            "--sst",
            str(args.sst.resolve()),
            "--lib-dir",
            str(args.lib_dir.resolve()),
            "--out-dir",
            str(out_dir.resolve()),
        ]
    if system == "grasu_regraph":
        return [
            args.python,
            str(ROOT / "scripts" / "run_sst_grasu_regraph_hls_pagerank.py"),
            "--no-build",
            "--profile",
            str(args.grasu_profile.resolve()),
            "--capability-catalog",
            str(args.capability_catalog.resolve()),
            "--workload",
            str(graph.resolve()),
            "--update-workload",
            str(update.resolve()),
            "--max-cycles",
            str(args.max_cycles),
            "--sst",
            str(args.sst.resolve()),
            "--lib-dir",
            str(args.lib_dir.resolve()),
            "--out-dir",
            str(out_dir.resolve()),
        ]
    raise ValueError(f"unsupported system: {system}")


def _run_process(command: list[str], log_path: Path, timeout: float) -> float:
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, _ = process.communicate(timeout=10.0)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, _ = process.communicate()
        log_path.write_text(stdout, encoding="utf-8")
        raise RuntimeError(f"child exceeded {timeout:.1f}s") from error
    wall_seconds = time.monotonic() - started
    log_path.write_text(stdout, encoding="utf-8")
    if process.returncode != 0:
        raise RuntimeError(f"child failed rc={process.returncode}; see {log_path}")
    return wall_seconds


def _run_system(
    run: dict[str, object],
    system: str,
    *,
    args: argparse.Namespace,
    spine_profile_id: str,
    spine_mhz: float,
    grasu_profile_id: str,
    grasu_mhz: float,
    execution_sha256: str,
) -> dict[str, object]:
    out_dir = args.out_dir / str(run["run_id"]) / system
    out_dir.mkdir(parents=True, exist_ok=True)
    command = _command(run, system, args=args, out_dir=out_dir)
    cache_path = out_dir / "comparison_cache.json"
    input_sha256 = hashlib.sha256(
        json.dumps(run, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    reusable = False
    wall_seconds = -1.0
    if args.resume and cache_path.is_file():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        reusable = (
            cache.get("status") == "PASS"
            and cache.get("command") == command
            and cache.get("input_sha256") == input_sha256
            and cache.get("execution_sha256") == execution_sha256
        )
        if reusable:
            wall_seconds = float(cache["wall_seconds"])
    if not reusable:
        wall_seconds = _run_process(
            command, out_dir / "parent_driver.log", args.timeout_seconds
        )

    if system == "spine":
        raw_result_path = out_dir / "summary.json"
        result = json.loads(raw_result_path.read_text(encoding="utf-8"))
        problems = validate_spine_pagerank_result(
            run,
            result,
            expected_profile_id=spine_profile_id,
            expected_core_mhz=spine_mhz,
            iterations=PAGERANK_ITERATIONS,
            damping=PAGERANK_DAMPING,
        )
        dram = {
            "reads": result["dram_reads"],
            "writes": result["dram_writes"],
            "activates": result["dram_activates"],
            "precharges": result["dram_precharges"],
            "total_energy_pj": result["dram_total_energy_pj"],
        }
        profile_id = spine_profile_id
    else:
        raw_result_path = out_dir / "manifest.json"
        child = json.loads(raw_result_path.read_text(encoding="utf-8"))
        problems = validate_grasu_pagerank_result(
            run,
            child,
            expected_profile_sha256=sha256_file(args.grasu_profile),
            expected_core_mhz=grasu_mhz,
            iterations=PAGERANK_ITERATIONS,
            damping=PAGERANK_DAMPING,
        )
        result = child["result"]
        dram = child["dram"]
        profile_id = grasu_profile_id
    if problems:
        raise RuntimeError(f"{run['run_id']}/{system} failed gates: {problems}")
    row = system_row(
        run,
        system=system,
        result=result,
        dram=dram,
        wall_seconds=wall_seconds,
        profile_id=profile_id,
    )
    row["raw_result_path"] = str(raw_result_path.resolve().relative_to(ROOT))
    row["raw_result_sha256"] = sha256_file(raw_result_path)
    if not reusable:
        cache_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "PASS",
                    "command": command,
                    "input_sha256": input_sha256,
                    "execution_sha256": execution_sha256,
                    "wall_seconds": wall_seconds,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-manifest", type=Path, default=DEFAULT_INPUT_MANIFEST)
    parser.add_argument("--spine-profile", type=Path, default=DEFAULT_SPINE_PROFILE)
    parser.add_argument("--grasu-profile", type=Path, default=DEFAULT_GRASU_PROFILE)
    parser.add_argument("--capability-catalog", type=Path, default=DEFAULT_CAPABILITIES)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--run-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--max-cycles", type=int, default=100_000_000)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    if args.jobs <= 0 or args.timeout_seconds <= 0.0 or args.max_cycles <= 0:
        raise ValueError("jobs, timeout, and max cycles must be positive")

    manifest = validate_real_small_batch_manifest(ROOT, args.input_manifest)
    selected = _select_runs(list(manifest["runs"]), args.run_id, args.limit)
    spine_profile, spine_mhz = _profile(
        args.spine_profile, "spine_shared_engine_9c08763"
    )
    grasu_profile, grasu_mhz = _profile(
        args.grasu_profile,
        "grasu_regraph_weighted_pma_hls_proposed_pagerank_ff13a67",
    )
    parameters = grasu_profile["parameters"]
    if (
        parameters["pagerank_iterations"] != PAGERANK_ITERATIONS
        or abs(float(parameters["pagerank_damping"]) - PAGERANK_DAMPING) > 1.0e-9
    ):
        raise ValueError("GraSU profile does not match the common PageRank contract")
    capabilities = json.loads(args.capability_catalog.read_text(encoding="utf-8"))
    grasu_capability = next(
        item
        for item in capabilities["profiles"]
        if item["profile_id"] == grasu_profile["profile_id"]
    )
    if grasu_capability["profile_sha256"] != sha256_file(args.grasu_profile):
        raise ValueError("GraSU capability/profile hash mismatch")
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    fingerprint_paths = [
        Path(__file__),
        ROOT
        / "spine_cycle_sim"
        / "experiments"
        / "hls_pagerank_real_comparison.py",
        ROOT / "scripts" / "run_sst_spine_vertical.py",
        ROOT / "scripts" / "run_sst_grasu_regraph_hls_pagerank.py",
        args.input_manifest,
        args.spine_profile,
        args.grasu_profile,
        args.capability_catalog,
        args.lib_dir / "libspine_cycle.so",
        args.sst,
    ]
    execution_sha256 = hashlib.sha256(
        b"".join(path.resolve().read_bytes() for path in fingerprint_paths)
    ).hexdigest()
    started = time.monotonic()
    rows: list[dict[str, object]] = []
    futures = {}
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        for run in selected:
            for system in ("spine", "grasu_regraph"):
                future = executor.submit(
                    _run_system,
                    run,
                    system,
                    args=args,
                    spine_profile_id=str(spine_profile["profile_id"]),
                    spine_mhz=spine_mhz,
                    grasu_profile_id=str(grasu_profile["profile_id"]),
                    grasu_mhz=grasu_mhz,
                    execution_sha256=execution_sha256,
                )
                futures[future] = (run["run_id"], system)
        for future in as_completed(futures):
            run_id, system = futures[future]
            row = future.result()
            rows.append(row)
            print(
                f"PASS {run_id}/{system}: e2e_ms={float(row['e2e_ms']):.6f} "
                f"requests={row['backend_requests']}",
                flush=True,
            )
    rows.sort(key=lambda row: (str(row["run_id"]), str(row["system"])))
    by_run: dict[str, dict[str, dict[str, object]]] = {}
    for row in rows:
        by_run.setdefault(str(row["run_id"]), {})[str(row["system"])] = row
    pairs = [
        pair_row(systems["spine"], systems["grasu_regraph"])
        for _, systems in sorted(by_run.items())
        if set(systems) == {"spine", "grasu_regraph"}
    ]
    if len(pairs) != len(selected):
        raise RuntimeError("PageRank comparison lacks one complete pair per run")
    csv_rows = [{key: value for key, value in row.items() if key != "ranks"} for row in rows]
    _write_csv(args.out_dir / "system_rows.csv", csv_rows)
    _write_csv(args.out_dir / "pairs.csv", pairs)
    complete = len(selected) == len(manifest["runs"]) and not args.run_id
    matrix_manifest = {
        "schema_version": 1,
        "matrix_id": "hls_full_pagerank_real_compact_comparison_20260726",
        "status": "PASS",
        "complete_matrix": complete,
        "claim_class": "profile_clock_adjusted_real_compact_execution_driven",
        "algorithm": "full_pagerank",
        "pagerank_iterations": PAGERANK_ITERATIONS,
        "pagerank_damping": PAGERANK_DAMPING,
        "input_manifest": str(args.input_manifest.resolve()),
        "input_manifest_sha256": sha256_file(args.input_manifest),
        "spine_profile_id": spine_profile["profile_id"],
        "spine_profile_sha256": sha256_file(args.spine_profile),
        "grasu_profile_id": grasu_profile["profile_id"],
        "grasu_profile_sha256": sha256_file(args.grasu_profile),
        "capability_catalog": str(args.capability_catalog.resolve()),
        "capability_catalog_sha256": sha256_file(args.capability_catalog),
        "execution_sha256": execution_sha256,
        "selected_run_ids": [run["run_id"] for run in selected],
        "system_rows": len(rows),
        "pairs": len(pairs),
        "all_correct": all(int(row["correctness_mismatches"]) == 0 for row in rows)
        and all(bool(pair["cross_system_ranks_match"]) for pair in pairs),
        "matrix_wall_seconds": time.monotonic() - started,
        "system_rows_sha256": sha256_file(args.out_dir / "system_rows.csv"),
        "pairs_sha256": sha256_file(args.out_dir / "pairs.csv"),
        "timing_window": {
            "spine": "zero-time compact L0 preload; timed update maintenance plus compute",
            "grasu_regraph": "zero-time PMA build; timed PMA and degree update plus compute",
            "clock_rule": "convert cycles using each profile clock",
        },
        "limitations": [
            "Inputs are compact real-edge slices, not full datasets.",
            "GraSU/ReGraph PageRank is HLS-equivalent proposed, not a compiled xclbin.",
            "Simulator cycles are not calibrated cycle-for-cycle against hw.",
            "DRAM energy covers active channels only and excludes on-chip energy.",
            "Sequential/random address classification remains open.",
        ],
    }
    (args.out_dir / "matrix_manifest.json").write_text(
        json.dumps(matrix_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"PASS real Full PageRank comparison: pairs={len(pairs)} "
        f"complete={complete} wall_s={matrix_manifest['matrix_wall_seconds']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
