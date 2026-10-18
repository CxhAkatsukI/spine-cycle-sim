"""Lease a strictly admitted production SSSP artifact for G-only comparisons."""

import os
from pathlib import Path
import re
import subprocess
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.board import require_idle_board
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.execution import wait_for_board
from ...complete_pipeline.hardware.remote import admission
from ...continuous_board.execution import runtime
from ...continuous_board.execution.supervisor import runner_pins
from ...search_pipeline.synthesis import unchanged
from ..analysis import CLAIMS
from . import analysis, inputs

PASS = "MATCHED_PRODUCTION_G_BOARD_PASS_NOT_ORIGINAL_OR_PUBLICATION_MATCH"
POLICY = {"tree_memory_gib": 4, "reserve_gib": 32, "allow_bounded_builds": True}


def run(preflight, original_preflight, returned, parent, original, output, *, receipt_sha256,
        device=0, repeats=3, preflight_sha256=inputs.PREFLIGHT_SHA256,
        original_preflight_sha256=inputs.ORIGINAL_PREFLIGHT_SHA256):
    if type(device) is not int or device not in (0, 1) or type(repeats) is not int or not 3 <= repeats <= 10 or \
            not re.fullmatch(r"[0-9a-f]{64}", receipt_sha256):
        raise ValueError("known device, 3--10 repeats and exact returned receipt required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "attempts": [], "rows": [],
              "boundary": analysis.BOUNDARY, "board_launch_attempted": False,
              **dict.fromkeys(CLAIMS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    memory = None
    try:
        group = current()
        report["containment"] = verify(group, memory_gib=4)
        host, cases, pins = inputs.load(preflight, original_preflight, preflight_sha256=preflight_sha256,
                                      original_preflight_sha256=original_preflight_sha256)
        checked = admission.review(returned, original, output / "routed_admission",
                                   parent_directory=parent, receipt_sha256=receipt_sha256)
        pins += [*checked["pins"], checked["candidate"], checked["timing"]["report"], *runner_pins()]
        report.update(admission=checked, pins=pins, device_index=device, repeats=repeats)
        unchanged(pins)
        runtime.require_clean_environment(host, output)
        if os.environ.get("MATCHED_G_LEASE_FD"):
            raise ValueError("inherited matched-G board lease forbidden")
        memory = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
        available = available_memory_bytes()
        report["memory_admission"] = memory.sample(available, other_builds(), POLICY,
                                                   commit=available >= 36 * 1024**3)
        save()
        if not memory.held:
            raise MemoryError("complete finite peer budgets and reserve do not fit; board not requested")
        with wait_for_board(device, report, save, pins) as (render, fd):
            require_idle_board(render)
            captured = runtime.capture(host, render, output / "runtime")
            pins += captured["pins"]
            report.update(runtime=captured, pins=pins)
            environment = dict(os.environ, MATCHED_G_LEASE_FD=str(fd),
                               CONTINUOUS_G_EXPECT_BDF=captured["device"]["bdf"], MALLOC_ARENA_MAX="2")
            for repeat in range(repeats):
                for case in cases:
                    unchanged(pins)
                    runtime.unchanged(captured, render)
                    runtime.require_clean_environment(host, output)
                    require_idle_board(render)
                    if available_memory_bytes() < 36 * 1024**3:
                        raise MemoryError("matched-G reserve no longer fits")
                    name = f"r{repeat}_{case['id']}"
                    command = ["/usr/bin/taskset", "-c", "120", str(host), "--board", case["packet"]["path"],
                               checked["candidate"]["path"], str(device)]
                    attempt = {"id": name, "command": command, "timeout_seconds": 600, "exit_code": None}
                    report["attempts"].append(attempt)
                    report.update(status="RUNNING_" + name, board_launch_attempted=True, board_programmed=None)
                    save()
                    stdout, stderr = (output / (name + suffix) for suffix in (".stdout.txt", ".stderr.txt"))
                    started = time.monotonic()
                    try:
                        with stdout.open("w") as out, stderr.open("w") as err:
                            result = subprocess.run(command, cwd=output, env=environment, pass_fds=(fd,),
                                                    stdout=out, stderr=err, timeout=600)
                        attempt["exit_code"] = result.returncode
                    finally:
                        attempt["wall_seconds"] = time.monotonic() - started
                        save()
                    if result.returncode:
                        raise ValueError("matched-G board host failed; no automatic reset or retry")
                    observed = analysis.inspect(stdout.read_text(), stderr.read_text(), case)
                    pins += [identity(stdout), identity(stderr)]
                    report["rows"].append({"case": case["id"], "repeat": repeat, "analysis": observed})
                    report.update(board_programmed=True, hardware_timing_measured=True)
                    save()
                    print(name + " matched production G full-state FPGA PASS", flush=True)
            report["summaries"] = analysis.summaries(report["rows"], [case["id"] for case in cases], repeats)
            runtime.unchanged(captured, render)
            unchanged(pins)
        report["status"] = PASS
    except BaseException as error:
        report.update(status="FAILED_RETAINED")
        report["errors"].append(repr(error))
        raise
    finally:
        if memory is not None:
            memory.release()
        if report.get("containment"):
            report["memory_events_after"] = (Path(report["containment"]["path"]) / "memory.events").read_text()
        save()
    return report
