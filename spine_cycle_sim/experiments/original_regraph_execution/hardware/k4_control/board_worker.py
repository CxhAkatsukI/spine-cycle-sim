"""Execute the fixed actual-K4 matrix while holding one exclusive board lease."""

import argparse
from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import subprocess
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution import runtime
from spine_cycle_sim.experiments.sharded_k4_stages.board import require_idle_board
from .. import artifact
from ..board_execution.worker import leased_board
from ..board_execution.preparation import REPEATS, unique
from ..source_build.snapshot import unchanged
from . import analysis, board_analysis, board_matrix, board_plan


@contextmanager
def wait_for_lease(device, report, save, *, timeout=1800, poll_seconds=10):
    started = time.monotonic()
    with ExitStack() as stack:
        while True:
            try:
                acquired = stack.enter_context(leased_board(device))
                break
            except BlockingIOError:
                elapsed = time.monotonic() - started
                report.update(status="WAITING_FOR_EXCLUSIVE_K4_BOARD_LEASE", lease_wait_seconds=elapsed)
                save()
                if elapsed >= timeout:
                    raise TimeoutError("board lease remained busy; no FPGA programming attempted")
                time.sleep(min(poll_seconds, timeout - elapsed))
        yield acquired


def run(manifest, output):
    job = json.loads(manifest.read_text())
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "rows": [], "attempts": [],
              "board_launch_attempted": False, "board_programmed": False, "hardware_timing_measured": False,
              "boundary": job["boundary"], "device_index": job["device_index"],
              "source_contract": job["source_contract"], "routed_candidate": job["xclbin"],
              "pins": unique([artifact.identity(manifest), *job["pins"]]),
              **dict.fromkeys(board_plan.CLAIMS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        board_plan.validate(job)
        if job["host"] not in report["pins"] or job["xclbin"] not in report["pins"]:
            raise ValueError("admitted host and routed bitstream must both be frozen")
        unchanged(report["pins"])
        binary = Path(job["host"]["path"])
        runtime.require_clean_environment(binary, output)
        if any(os.environ.get(key) for key in ("ORIGINAL_R_LEASE_FD", "ORIGINAL_R_EXPECT_BDF")):
            raise ValueError("inherited device/lease override is forbidden")
        with wait_for_lease(job["device_index"], report, save) as (render, fd):
            require_idle_board(render)
            captured = runtime.capture(binary, render, output / "runtime")
            report["runtime"] = captured
            report["pins"] = unique([*report["pins"], *captured["pins"]])
            environment = dict(os.environ, ORIGINAL_R_LEASE_FD=str(fd),
                ORIGINAL_R_EXPECT_BDF=captured["device"]["bdf"], MALLOC_ARENA_MAX="2")
            save()
            for repeat in range(REPEATS):
                for case in job["cases"]:
                    if case["status"] == analysis.UNSUPPORTED:
                        report["rows"].append(board_matrix.unsupported(case, repeat))
                        save()
                        continue
                    unchanged(report["pins"])
                    runtime.unchanged(captured, render)
                    runtime.require_clean_environment(binary, output)
                    require_idle_board(render)
                    name = f"r{repeat}_{case['graph']}_{case['binding']}"
                    destination = output / "cases" / name
                    command = ["/usr/bin/taskset", "-c", "124,125", str(binary), "board", case["input"],
                               case["binding"], str(destination), job["xclbin"]["path"], str(job["device_index"])]
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
                        report["pins"] = unique([*report["pins"], *[
                            artifact.identity(output / (name + suffix)) for suffix in (".stdout.txt", ".stderr.txt")
                            if (output / (name + suffix)).is_file()]])
                        save()
                    if record["exit_code"] or (output / (name + ".stderr.txt")).stat().st_size:
                        raise ValueError("guarded K4 host failed or emitted diagnostics; no reset or retry")
                    observed = json.loads((destination / "result.json").read_text())
                    checked = board_analysis.readback(observed, destination, case, captured["device"]["bdf"])
                    report["rows"].append({"graph": case["graph"], "binding": case["binding"], "repeat": repeat,
                        "status": board_analysis.PASS, "directory": str(destination),
                        "observation": observed, "analysis": checked})
                    report["pins"] = unique([*report["pins"], *checked["pins"]])
                    report.update(board_programmed=True, hardware_timing_measured=True)
                    save()
                    print(name + " guarded K4 FPGA correctness PASS", flush=True)
            report["summaries"] = board_matrix.summarize(report["rows"], job["cases"])
            runtime.unchanged(captured, render)
            unchanged(report["pins"])
        report["status"] = board_matrix.PASS
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        save()
        raise
    save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(run(args.manifest.resolve(), args.output.resolve())["status"], flush=True)
