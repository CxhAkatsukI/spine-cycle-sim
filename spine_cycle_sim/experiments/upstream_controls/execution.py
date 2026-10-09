"""Bounded subprocess execution and source/dependency identities for controls."""

from __future__ import annotations

import os
from pathlib import Path
import resource
import shlex
import signal
import subprocess
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file


def available_memory_bytes() -> int:
    with Path("/proc/meminfo").open(encoding="ascii") as stream:
        for line in stream:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    raise RuntimeError("MemAvailable missing; refuse an unbounded memory launch")


def _limits(memory_bytes: int, stack_bytes: int) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_STACK, (stack_bytes, stack_bytes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def run_bounded(command: list[str], cwd: Path, prefix: Path, *, timeout: int,
                memory_gib: int, reserve_gib: int) -> dict:
    memory_bytes = memory_gib * 1024**3
    available = available_memory_bytes()
    if available < (memory_gib + reserve_gib) * 1024**3:
        raise RuntimeError("insufficient available memory for process limit plus reserve")
    prefix.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with prefix.with_suffix(".stdout.txt").open("w") as stdout, \
            prefix.with_suffix(".stderr.txt").open("w") as stderr:
        process = subprocess.Popen(
            command, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True,
            preexec_fn=lambda: _limits(memory_bytes, 128 * 1024**2),
        )
        timed_out = False
        while True:
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                break
            if time.monotonic() - started >= timeout:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                _, status, usage = os.wait4(process.pid, 0)
                break
            time.sleep(0.05)
        process.returncode = os.waitstatus_to_exitcode(status)
    record = {
        "command": command, "cwd": str(cwd), "exit_code": process.returncode,
        "timed_out": timed_out, "wall_seconds": time.monotonic() - started,
        "peak_rss_kib": usage.ru_maxrss, "memory_limit_gib": memory_gib,
        "rss_scope": "wait4_maximum_process_RSS_not_simultaneous_tree_sum",
        "reserve_gib": reserve_gib, "available_before_bytes": available,
        "stdout": str(prefix.with_suffix(".stdout.txt")),
        "stderr": str(prefix.with_suffix(".stderr.txt")),
    }
    atomic_write_json(prefix.with_suffix(".resources.json"), record)
    return record


def dependency_identities(path: Path, cwd: Path) -> list[dict]:
    # GCC's -MT probe fixes the target; shlex handles escaped spaces in paths.
    contents = path.read_text().replace("\\\n", "")
    target, separator, dependencies = contents.partition(":")
    if not separator or target.strip() != "probe":
        raise ValueError("unexpected GCC dependency target")
    identities = []
    for token in sorted(set(shlex.split(dependencies))):
        dependency = Path(token)
        dependency = dependency if dependency.is_absolute() else cwd / dependency
        identities.append({"path": str(dependency.resolve()),
                           "sha256": sha256_file(dependency)})
    return identities
