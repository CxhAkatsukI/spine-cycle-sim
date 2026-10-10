"""Freeze a paired hardware diagnostic and execute with bounded resources."""

from __future__ import annotations

import csv
import fcntl
import os
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from .analysis import analyze_log


def identity(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": sha256_file(path)}


def select_case(matrix: Path, case: str) -> dict:
    with matrix.open() as stream:
        rows = [row for row in csv.DictReader(stream, delimiter="\t") if row["case"] == case]
    if len(rows) != 1:
        raise ValueError("case must identify exactly one frozen matrix row")
    return rows[0]


def run_study(*, integration: Path, matrix: Path, case: str, baseline_host: Path,
              trace_host: Path, output: Path, device: int, repeats: int,
              timeout: int = 600, memory_gib: int = 8) -> dict:
    if repeats < 1 or device not in (0, 1):
        raise ValueError("positive repeat count and a known board index required")
    row = select_case(matrix, case)
    if row["algorithm"] not in ("weighted_sssp", "connected_components", "residual_pagerank", "full_pagerank"):
        raise ValueError("unsupported sharded host algorithm")
    output.mkdir(parents=True, exist_ok=False)
    pinned = {name: identity(Path(path)) for name, path in {
        "matrix": matrix, "graph": row["graph"], "xclbin": row["gr_xclbin"],
        "baseline_host": baseline_host, "trace_host": trace_host,
    }.items()}
    source_names = ["tools/sharded_k4_native_host.cpp", "tools/sharded_k4_pagerank_native_host.cpp",
                    "tools/weighted_pma_native_host.cpp", "include/sharded_event_trace.hpp",
                    "kernels/pma_to_regraph_adapter/pma_to_regraph_adapter.cpp",
                    "scripts/run_pma_native_hw.sh", "scripts/build_weighted_pma_native_host.sh"]
    source = [identity(integration / name) for name in source_names]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=integration, text=True).strip()
    diff = subprocess.check_output(["git", "diff", "--binary"], cwd=integration, text=True)
    (output / "integration.diff").write_text(diff)
    manifest = {"schema": 1, "case": row, "inputs": pinned, "integration_head": head,
                "integration_source": source, "repeats": repeats, "device_index": device,
                "host_affinity": sorted(os.sched_getaffinity(0)), "memory_limit_gib": memory_gib,
                "reserve_gib": 16, "timeout_seconds": timeout,
                "claim": "observational_host_trace_of_unchanged_routed_K4_not_A4_or_publication_match"}
    atomic_write_json(output / "manifest.json", manifest)
    lock_path = Path(f"/tmp/chuxiao-sharded-k4-board-{device}.lock")
    render = ("/dev/dri/renderD128", "/dev/dri/renderD131")[device]
    if not Path(render).exists():
        raise FileNotFoundError(render)
    attempts = []
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for repeat in range(repeats):
            for arm, host, trace in (("baseline", baseline_host, "0"),
                                     ("trace_disabled", trace_host, "0"),
                                     ("trace_enabled", trace_host, "1")):
                users = subprocess.run(["fuser", render], capture_output=True, text=True)
                if users.returncode != 1:
                    raise RuntimeError(f"board is occupied or occupancy check failed: {users.stdout} {users.stderr}")
                name = f"r{repeat}_{arm}"
                run_dir = output / name
                if run_dir.exists():
                    raise FileExistsError(run_dir)
                command = ["env", f"GRASU_SHARDED_EVENT_TRACE={trace}",
                           "GRASU_UPDATE_REPEATS=1", "bash",
                           str(integration / "scripts/run_pma_native_hw.sh"),
                           "--algorithm", row["algorithm"], "--host", str(host),
                           "--xclbin", row["gr_xclbin"], "--graph", row["graph"],
                           "--out-dir", str(run_dir), "--source", row["source"],
                           "--max-supersteps", "256", "--device-index", str(device),
                           "--timeout", str(max(1, timeout - 20))]
                resources = run_bounded(command, integration, output / f"{name}_process",
                                        timeout=timeout, memory_gib=memory_gib, reserve_gib=16)
                attempt = {"arm": arm, "repeat": repeat, "resources": resources}
                attempts.append(attempt)
                atomic_write_json(output / "attempts.json", attempts)
                if resources["exit_code"] != 0:
                    raise RuntimeError(f"hardware run failed; raw attempt preserved in {output}")
                attempt["analysis"] = analyze_log((run_dir / "run.log").read_text(),
                                                   require_trace=trace == "1")
                attempt["result"] = identity(run_dir / "result.txt")
                atomic_write_json(output / "attempts.json", attempts)
                print(f"{case} {name} PASS peak_rss_kib={resources['peak_rss_kib']}", flush=True)
    checks = {name: sha256_file(Path(item["path"])) == item["sha256"]
              for name, item in pinned.items()}
    checks["source_unchanged_during_run"] = all(
        sha256_file(Path(item["path"])) == item["sha256"] for item in source)
    checks["all_result_bytes_equal"] = len({a["result"]["sha256"] for a in attempts}) == 1
    checks["same_correctness_and_rounds"] = all(
        a["analysis"]["result"] == attempts[0]["analysis"]["result"] for a in attempts)
    summary = {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
               "attempts": attempts, "claim": manifest["claim"]}
    atomic_write_json(output / "summary.json", summary)
    if summary["status"] != "PASS":
        raise RuntimeError("paired hardware diagnostic invariants failed")
    return summary
