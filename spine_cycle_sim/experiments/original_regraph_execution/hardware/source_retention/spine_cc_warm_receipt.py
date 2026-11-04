"""Replay the one-shot warm CC AU Spine arm without running another board sample."""

import json
from pathlib import Path
import re

from spine_cycle_sim.experiments.evaluation_impact.fullgraph_readiness import board_memory
from . import cc_resident_results, clocks, spine_smoke
from .follow import unchanged
from .runtime import identity


ABI = "85808e123f78044eee0905e0f87f19b41b338562f84d10fb200aac43249e5a3f"
HOST_SHA256 = "3f967b7ef10c0ce9bd44ac0ade280e464d7918d1e35a1242b9e690356f61ea10"
BALANCED_HOST_SHA256 = "aa265331a1e292dd8e2bd91d961bd9b3fdb2a1471aa29ba8983410313a223582"
RUNNER_SHA256 = "174fdc4e61ed911b517d303ead7e3ab499d083617611cd4907e72b885602fc80"
INPUTS_SHA256 = "87120570af93f6e659a3ebec45207db475ba83d5c7c194d37c80b104f744ae2e"
ROUTE_INVOCATION = "79463b9047ac4062810a42e50befc9aa"
BDF, AFFINITY = "0000:82:00.1", (124, 125)
TIMING = "impl_1_hw_bb_locked_timing_summary_postroute_physopted.rpt"


def route_pins(binary):
    image = Path(binary["path"])
    paths = [image.with_suffix(image.suffix + ".weighted-manifest"), image.parent / "remote-systemd.txt",
             image.parent / TIMING, image.parent / "bus_skew_routed.rpt"]
    pins = [identity(path) for path in paths]
    manifest, route, timing, skew = (path.read_text() for path in paths)
    if not {f"build_sha256 {ABI}", f"image_sha256 {binary['sha256']}", "target hw"} <= set(manifest.splitlines()):
        raise ValueError("not the warm CC hardware image")
    if not {f"InvocationID={ROUTE_INVOCATION}", "SubState=exited", "Result=success",
            "ExecMainStatus=0"} <= set(route.splitlines()):
        raise ValueError("not the successful pinned warm CC route")
    if "All user specified timing constraints are met." not in timing:
        raise ValueError("warm CC image did not close timing")
    summary = skew.split("2. Bus Skew Report Per Constraint", 1)[0]
    slacks = re.findall(r"^\s*(?:Slow|Fast)(?:\s+[-.\d]+){2}\s+([-.\d]+)\s*$", summary, re.MULTILINE)
    if not slacks or min(map(float, slacks)) < 0:
        raise ValueError("warm CC image did not close bus skew")
    unchanged([binary, *pins])
    return pins


def replay(receipt, frozen_source, *, bdf, affinity):
    """Return an arm and its supporting pins; this does not admit the G+R baseline."""
    if (bdf, tuple(affinity)) != (BDF, AFFINITY):
        raise ValueError("the retained Spine sample requires the same board and CPU affinity")
    receipt_path = Path(receipt["path"])
    unchanged([receipt, frozen_source])
    data = json.loads(receipt_path.read_text())
    if ((data["status"], data["performance_admission"], data["errors"], data["bdf"], data["device"])
            != ("RESIDENT_CC_STATE_WORK_AND_CLOCK_PASS_NOT_PERFORMANCE_ADMISSION", False, [], bdf, 0)):
        raise ValueError("expected a completed single-arm CC state and work screen")
    execution, workload, pins = (data[key] for key in ("execution", "workload", "pins"))
    if ((workload["vertices"], workload["edges"], workload["updates"]) != (515281, 679246, 16)
            or workload["source"] != frozen_source
            or any(workload[key] not in pins for key in ("source", "graph", "update"))):
        raise ValueError("CC arm did not use the frozen AU graph and update batch")
    manifests = [pin for pin in pins if pin["sha256"] == INPUTS_SHA256]
    hosts = [pin for pin in pins if pin["sha256"] == HOST_SHA256]
    runners = [pin for pin in pins if pin["sha256"] == RUNNER_SHA256]
    unchanged(pins)
    if (len(manifests) != 1 or json.loads(Path(manifests[0]["path"]).read_text()) != workload
            or len(hosts) != 1 or len(runners) != 1):
        raise ValueError("wrong input manifest, warm CC host or smoke runner")
    evidence = data["clock_evidence"]
    clock = clocks.replay(evidence)
    binary = clock["binary"]
    route_evidence = route_pins(binary)
    if clock["bdf"] != bdf or binary not in pins or route_evidence[0] not in pins:
        raise ValueError("measured image or card differs from the warm CC route")
    command = ["/usr/bin/taskset", "-c", "124,125", hosts[0]["path"], "--xclbin", binary["path"],
               "--hot", "0", "--mode", "partial", "--samples", "1", "--slice", workload["graph"]["path"],
               "--update", workload["update"]["path"]]
    if ((execution["command"], execution["host_affinity"], execution["exit_code"], execution["stop_reason"],
         execution["cleanup_snapshot_error"], execution["cleanup_signaled_pids"])
            != (command, list(AFFINITY), 0, "process_exit", None, [])):
        raise ValueError("expected one successful cold-layout warm-state sample")
    board_memory.require_unthrottled(data["memory_events"])
    stdout, stderr = data["stdout"], data["stderr"]
    all_pins = [receipt, *pins, *route_evidence[1:], stdout, stderr]
    unchanged([stdout, stderr])
    log = Path(stdout["path"]).read_text()
    cc_resident_results.validate_spine(workload, log.splitlines())
    dims = dict(vertices=workload["vertices"], physical_updates=workload["updates"])
    if (data["batches"] != spine_smoke.validate(log, batches=1, **dims)
            or data["resident_wall_ms"] != spine_smoke.resident_wall(log, **dims)):
        raise ValueError("saved CC state or timing does not replay from the board log")
    unchanged([receipt, stdout])
    return {"command": command, "stdout": stdout, "stderr": stderr, "clock_evidence": evidence,
            "clock": clock}, all_pins
