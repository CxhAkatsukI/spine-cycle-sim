"""Memory-admitted diagnostic links with per-attempt and short admission locks."""

import fcntl
import json
from pathlib import Path
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment.__main__ import execute
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment.contract import reconstruct
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment.probe import run as preflight
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import (
    current, other_builds, verify)
from ...search_pipeline.synthesis import unchanged


def run(build, output):
    manifest = json.loads((output / "manifest.json").read_text())
    if (manifest["status"] != "PREPARED_DIAGNOSTIC_LINK_NOT_BASELINE_ADMISSION" or
            [manifest[key] for key in ("tree_memory_gib", "reserve_gib", "background_memory_gib",
             "allow_bounded_builds", "timeout_seconds", "queue_timeout_seconds")] != [40, 24, 8, True, 21600, 86400]):
        raise ValueError("declared diagnostic route safety policy differs")
    record = output / "execution.json"
    lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", current())
    with (output / "supervisor.lock").open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if record.exists():
            raise FileExistsError("diagnostic route already supervised")
        guard = verify(current())
        atomic_write_json(output / "containment.json", guard)
        started, consecutive, route_started = time.monotonic(), 0, False
        try:
            unchanged(manifest["pins"])
            while True:
                state = lease.sample(available_memory_bytes(), other_builds(), manifest,
                                     commit=consecutive >= 7)
                consecutive = consecutive + 1 if state["admitted"] else 0
                state.update(status="QUEUED_WAITING_FOR_SAFE_MEMORY", route_started=False,
                             consecutive_safe_samples=consecutive, queue_seconds=time.monotonic() - started)
                atomic_write_json(record, state)
                if lease.held:
                    break
                if state["queue_seconds"] >= manifest["queue_timeout_seconds"]:
                    state["status"] = "QUEUE_TIMEOUT_NOT_STARTED"
                    atomic_write_json(record, state)
                    return state
                time.sleep(2)
            unchanged(manifest["pins"])
            environment, contract = reconstruct(build, output)
            if contract != json.loads((output / "environment.json").read_text()):
                raise ValueError("prepared environment changed")
            atomic_write_json(record, {**state, "status": "MEMORY_ADMITTED_PREFLIGHT", "route_started": False})
            preflight(output, environment, contract)
            manifest["pins"].append(identity(output / "preflight/results.json"))
            atomic_write_json(output / "manifest.json", manifest)
            route_started = True
            atomic_write_json(record, {**state, "status": "DIAGNOSTIC_ROUTING", "route_started": True})
            result = execute(output, manifest, environment, contract)
            result.update(route_started=True, cgroup=guard, admission=state,
                          integrated_rtl_admitted=False, FPGA_timing_admitted=False,
                          production_baseline_admitted=False, publication_match_admitted=False)
            atomic_write_json(record, result)
            return result
        except BaseException as error:
            failure = {"status": "SUPERVISOR_FAILED_RETAINED", "error": repr(error),
                       "route_started": route_started, "production_baseline_admitted": False}
            atomic_write_json(output / "failure.json", failure)
            atomic_write_json(record, failure)
            raise
        finally:
            lease.release()
            events = current() / "memory.events"
            if events.exists():
                atomic_write_json(output / "cgroup_events.json", dict(
                    line.split() for line in events.read_text().splitlines()))
