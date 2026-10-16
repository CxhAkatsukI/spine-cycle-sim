"""Hold one exclusive board lease throughout all eighteen guarded host runs."""

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution import runtime
from spine_cycle_sim.experiments.sharded_k4_stages.board import require_idle_board
from .. import artifact
from ..source_build.snapshot import unchanged
from . import analysis
from .preparation import REPEATS, unique, validate_plan


@contextmanager
def leased_board(device):
    if type(device) is not int or device not in (0, 1):
        raise ValueError("known U55C device index required")
    render = Path(("/dev/dri/renderD128", "/dev/dri/renderD131")[device])
    if not render.exists():
        raise FileNotFoundError(render)
    path = Path(f"/tmp/chuxiao-sharded-k4-board-{device}.lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        opened = os.fstat(fd)
        named = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise ValueError("exclusive lease must be a regular unchanged lock file")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield render, fd
    finally:
        os.close(fd)


def run(manifest, output):
    job = json.loads(manifest.read_text())
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "rows": [], "attempts": [],
              "board_launch_attempted": False, "board_programmed": False,
              "hardware_timing_measured": False, "publication_match": False,
              "convergence_measured": False, "host_inclusive_measured": False,
              "boundary": job["boundary"], "device_index": job["device_index"],
              "pins": unique([artifact.identity(manifest), *job["pins"]])}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        validate_plan(job)
        unchanged(report["pins"])
        binary = Path(job["host"]["path"])
        runtime.require_clean_environment(binary, output)
        if any(os.environ.get(key) for key in ("ORIGINAL_R_LEASE_FD", "ORIGINAL_R_EXPECT_BDF")):
            raise ValueError("inherited original-R device/lease override is forbidden")
        with leased_board(job["device_index"]) as (render, fd):
            require_idle_board(render)
            captured = runtime.capture(binary, render, output / "runtime")
            report["runtime"] = captured
            report["pins"] = unique([*report["pins"], *captured["pins"]])
            environment = dict(os.environ, ORIGINAL_R_LEASE_FD=str(fd),
                ORIGINAL_R_EXPECT_BDF=captured["device"]["bdf"], MALLOC_ARENA_MAX="2")
            save()
            for repeat in range(REPEATS):
                for case in job["cases"]:
                    unchanged(report["pins"])
                    runtime.unchanged(captured, render)
                    runtime.require_clean_environment(binary, output)
                    require_idle_board(render)
                    name = f"r{repeat}_{case['graph']}_{case['binding']}"
                    destination = output / "cases" / name
                    command = ["/usr/bin/taskset", "-c", "124,125", str(binary), "board", case["input"],
                               "original_example", case["binding"], str(destination),
                               job["xclbin"]["path"], str(job["device_index"])]
                    record = {"name": name, "command": command, "timeout_seconds": 600,
                              "lease_fd_forwarded": True, "exit_code": None, "timed_out": False}
                    report["attempts"].append(record)
                    report.update(status="RUNNING_" + name, board_launch_attempted=True, board_programmed=None)
                    save()
                    started = time.monotonic()
                    try:
                        with (output / (name + ".stdout.txt")).open("w") as stdout, \
                                (output / (name + ".stderr.txt")).open("w") as stderr:
                            result = subprocess.run(command, cwd=output, env=environment, stdout=stdout,
                                stderr=stderr, pass_fds=(fd,), timeout=600)
                        record["exit_code"] = result.returncode
                    except subprocess.TimeoutExpired:
                        record["timed_out"] = True
                        raise
                    finally:
                        record["wall_seconds"] = time.monotonic() - started
                        save()
                    if record["exit_code"]:
                        raise ValueError("guarded original-R host failed; no automatic reset or retry")
                    observation = json.loads((destination / "result.json").read_text())
                    checked = analysis.inspect(observation, destination, case, captured["device"]["bdf"])
                    report["rows"].append({"graph": case["graph"], "binding": case["binding"], "repeat": repeat,
                        "directory": str(destination), "observation": observation, "analysis": checked})
                    report["pins"] = unique([*report["pins"], *checked["pins"]])
                    report.update(board_programmed=True, hardware_timing_measured=True)
                    save()
                    print(name + " guarded FPGA correctness PASS", flush=True)
            report["summaries"] = analysis.matrix(report["rows"])
            runtime.unchanged(captured, render)
            unchanged(report["pins"])
        report["status"] = analysis.PASS
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        save()
        raise
    save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(run(args.manifest.resolve(), args.output.resolve())["status"], flush=True)
