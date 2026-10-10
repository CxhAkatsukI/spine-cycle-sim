"""Route-only process-tree RSS and live-memory watchdog.

Vivado workers share a process group; per-process address-space limits alone
do not constrain the simultaneous memory use of a link job.
"""

import os
from pathlib import Path
import resource
import signal
import subprocess
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes


def tree_rss_kib(table: str, root: int) -> tuple[int, list[int]]:
    rows = [tuple(map(int, line.split())) for line in table.splitlines() if line.strip()]
    if any(len(row) != 4 for row in rows):
        raise ValueError("expected pid, ppid, pgid, rss process snapshot")
    owned = {root} | {pid for pid, _, group, _ in rows if group == root}
    while True:
        expanded = owned | {pid for pid, parent, _, _ in rows if parent in owned}
        if expanded == owned:
            break
        owned = expanded
    live = [(pid, rss) for pid, _, _, rss in rows if pid in owned]
    return sum(rss for _, rss in live), sorted(pid for pid, _ in live)


def _child_limits() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (64 * 1024**3, 64 * 1024**3))
    resource.setrlimit(resource.RLIMIT_STACK, (128 * 1024**2, 128 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run_link(command: list[str], cwd: Path, prefix: Path, *, timeout: int = 14400,
             tree_memory_gib: int = 40, reserve_gib: int = 16,
             poll_seconds: float = 2, environment: dict | None = None) -> dict:
    if timeout <= 0 or tree_memory_gib <= 0 or reserve_gib < 0 or poll_seconds <= 0:
        raise ValueError("invalid route watchdog budget")
    available = available_memory_bytes()
    if available < (tree_memory_gib + reserve_gib) * 1024**3:
        raise RuntimeError("insufficient memory for route tree budget plus reserve")
    started = time.monotonic()
    peak = 0
    minimum_available = available
    reason = "process_exit"
    prefix.parent.mkdir(parents=True, exist_ok=True)
    with prefix.with_suffix(".stdout.txt").open("w") as stdout, \
            prefix.with_suffix(".stderr.txt").open("w") as stderr:
        process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=stdout,
                                   stderr=stderr, start_new_session=True,
                                   preexec_fn=_child_limits)
        try:
            while process.poll() is None:
                snapshot = subprocess.check_output(
                    ["ps", "-eo", "pid=,ppid=,pgid=,rss="], text=True, timeout=10)
                rss, pids = tree_rss_kib(snapshot, process.pid)
                peak = max(peak, rss)
                current = available_memory_bytes()
                minimum_available = min(minimum_available, current)
                elapsed = time.monotonic() - started
                if rss * 1024 > tree_memory_gib * 1024**3:
                    reason = "tree_rss_budget"
                elif current < reserve_gib * 1024**3:
                    reason = "live_memory_reserve"
                elif elapsed >= timeout:
                    reason = "timeout"
                atomic_write_json(prefix.with_suffix(".progress.json"), {
                    "pid": process.pid, "wall_seconds": elapsed, "tree_rss_kib": rss,
                    "peak_tree_rss_kib": peak, "available_bytes": current,
                    "owned_pids": pids, "stop_reason": reason})
                if reason != "process_exit":
                    os.killpg(process.pid, signal.SIGKILL)
                    break
                time.sleep(poll_seconds)
            process.wait()
        except BaseException:
            reason = "watchdog_error_or_interruption"
            raise
        finally:
            # Also reap workers still in the session if the launcher exited.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            record = {"command": command, "cwd": str(cwd),
                      "exit_code": process.returncode, "stop_reason": reason,
                      "wall_seconds": time.monotonic() - started,
                      "peak_tree_rss_kib": peak,
                      "rss_scope": "sampled_simultaneous_tree_sum_shared_pages_counted_per_process",
                      "minimum_available_bytes": minimum_available,
                      "available_before_bytes": available,
                      "tree_memory_gib": tree_memory_gib, "reserve_gib": reserve_gib,
                      "per_process_address_space_gib": 64,
                      "host_affinity": sorted(os.sched_getaffinity(0)),
                      "timeout_seconds": timeout}
            atomic_write_json(prefix.with_suffix(".resources.json"), record)
    return record
