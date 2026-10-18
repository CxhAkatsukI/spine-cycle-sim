"""Lease one U55C and run the admitted original-G eight-case matrix."""

from contextlib import ExitStack, contextmanager
import json
import os
from pathlib import Path
import subprocess
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.board import require_idle_board
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution.worker import leased_board
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution import runtime
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import runner_pins
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged
from ...host.fixtures import NAMES
from .. import admission, configuration as config
from . import analysis, preflight, preparation

PREFLIGHT_SHA256 = "bee145c72883f4c0d9ec85ca0eccab207bfdebd1050d9a978d4645d7ae9cc701"
PASS = "ORIGINAL_G_U55C_MATRIX_PASS_NOT_PUBLICATION_OR_MATCHED_G_COMPARISON"


@contextmanager
def wait_for_board(device, report, save, pins, *, maximum_wait=3600):
    deadline = time.monotonic() + maximum_wait
    with ExitStack() as stack:
        while True:
            unchanged(pins)
            if available_memory_bytes() < 36 * 1024**3:
                raise MemoryError("original G board reserve no longer fits")
            try:
                lease = stack.enter_context(leased_board(device))
                break
            except BlockingIOError:
                report.update(status="WAITING_FOR_EXCLUSIVE_BOARD_NOT_PROGRAMMED")
                save()
                if time.monotonic() >= deadline:
                    raise TimeoutError("original G exclusive board wait expired")
                time.sleep(min(10, max(0, deadline - time.monotonic())))
        yield lease


def inputs(root):
    pin = identity(root / "results.json")
    report = json.loads((root / "results.json").read_text())
    manifest = json.loads((root / "inputs/manifest.json").read_text())
    if pin["sha256"] != PREFLIGHT_SHA256 or report.get("status") != preflight.STATUS or report.get("errors") != [] or \
            any(report.get(flag) is not False for flag in config.FLAGS) or \
            manifest.get("status") != "ORIGINAL_G_CAPTURE_REPLAY_PASS_NOT_BOARD" or \
            manifest.get("baseline_sha256") != preparation.BASELINE_SHA256 or \
            [row.get("id") for row in manifest["cases"]] != list(NAMES) or len(report["steps"]) != 21 or \
            {(row["variant"], row["id"]) for row in report["cases"]} != {(v, name) for v in ("release", "ubsan") for name in NAMES}:
        raise ValueError("reviewed original G runtime-closure host preflight required")
    binaries = [row for row in report["binaries"] if row["variant"] == "release"]
    if len(binaries) != 1:
        raise ValueError("one original G Release host required")
    pins = [pin, *report["pins"], *manifest["pins"], *report["runtime_libraries"]]
    unchanged(pins)
    return Path(binaries[0]["path"]), manifest["cases"], pins


def run(preflight_root, admitted, output, *, device=0, repeats=3):
    if type(device) is not int or device not in (0, 1) or type(repeats) is not int or not 3 <= repeats <= 10:
        raise ValueError("known original G board and 3--10 repetitions required")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "errors": [], "rows": [], "attempts": [],
              "board_launch_attempted": False, "boundary": analysis.BOUNDARY,
              **dict.fromkeys(config.FLAGS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    save()
    try:
        report["containment"] = verify(current(), memory_gib=4)
        host, cases, host_pins = inputs(preflight_root)
        admitted_pin = identity(admitted / "summary.json")
        checked = json.loads((admitted / "summary.json").read_text())
        if checked.get("status") != admission.PASS or any(checked.get(flag) is not False for flag in config.FLAGS):
            raise ValueError("original G strict source/ABI/clock/timing admission required")
        pins = [*host_pins, admitted_pin, *checked["pins"], checked["candidate"], *runner_pins()]
        report["pins"] = list({row["path"]: row for row in pins}.values())
        unchanged(pins)
        runtime.require_clean_environment(host, output)
        if any(os.environ.get(key) for key in ("ORIGINAL_G_LEASE_FD", "ORIGINAL_G_EXPECT_BDF")):
            raise ValueError("inherited original G lease/device override forbidden")
        with wait_for_board(device, report, save, pins) as (render, fd):
            require_idle_board(render)
            captured = runtime.capture(host, render, output / "runtime")
            pins += captured["pins"]
            report.update(runtime=captured, device_index=device, repeats=repeats)
            environment = dict(os.environ, ORIGINAL_G_LEASE_FD=str(fd),
                ORIGINAL_G_EXPECT_BDF=captured["device"]["bdf"], MALLOC_ARENA_MAX="2")
            for repeat in range(repeats):
                for case in cases:
                    unchanged(pins)
                    runtime.unchanged(captured, render)
                    runtime.require_clean_environment(host, output)
                    require_idle_board(render)
                    if available_memory_bytes() < 36 * 1024**3:
                        raise MemoryError("original G board reserve no longer fits")
                    name = f"r{repeat}_{case['id']}"
                    command = ["/usr/bin/taskset", "-c", "120", str(host), "--board", case["packet"]["path"],
                               checked["candidate"]["path"], str(device)]
                    attempt = {"id": name, "command": command, "timeout_seconds": 600,
                               "lease_fd_forwarded": True, "exit_code": None}
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
                        raise ValueError("original G board host failed; no automatic reset or retry")
                    observed = analysis.inspect(stdout, stderr, case, captured["device"]["bdf"])
                    pins += [identity(stdout), identity(stderr)]
                    report["pins"] = list({row["path"]: row for row in pins}.values())
                    report["rows"].append({"case": case["id"], "repeat": repeat, "analysis": observed})
                    report.update(board_programmed=True, hardware_timing_measured=True)
                    save()
                    print(name + " original G complete-state FPGA PASS", flush=True)
            report["summaries"] = analysis.summaries(report["rows"], list(NAMES), repeats)
            runtime.unchanged(captured, render)
            unchanged(pins)
        report.update(status=PASS, pins=list({row["path"]: row for row in pins}.values()))
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        raise
    finally:
        save()
    return report
