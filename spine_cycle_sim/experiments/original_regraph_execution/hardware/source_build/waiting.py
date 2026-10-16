"""Wait for memory admission, without reserving a compiler or a board."""

import json
from pathlib import Path
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from .. import artifact
from . import configuration as config, execution, placement as physical, snapshot


def run(root: Path, upstream: Path, audit: Path, control: Path,
        environment: Path, output: Path, *, wait_seconds: int,
        topology: str = config.DEFAULT_TOPOLOGY, placement: str = physical.DEFAULT) -> dict:
    physical.validate(topology, placement)
    little, big = config.counts(topology)
    if type(wait_seconds) is not int or not 1 <= wait_seconds <= 86400:
        raise ValueError("memory wait must be between one second and one day")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "WAITING_FOR_MEMORY", "errors": [], "samples": 0,
              "wait_seconds": wait_seconds, "poll_seconds": 10, "pins": [],
              "build_output": str(output / "build"), "board_programmed": False,
              "hardware_timing_measured": False, "publication_match": False,
              "configuration": topology, "little": little, "big": big, "placement": placement}

    def save():
        atomic_write_json(output / "queue.json", report)

    save()
    try:
        group = current()
        verify(group, memory_gib=config.POLICY["tree_memory_gib"])
        captured = json.loads(environment.read_text())
        report["pins"] = (execution.prerequisites(audit, control) + execution.runner_pins()
                          + [artifact.identity(environment), *captured["pins"]])
        lease = Lease(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
        deadline = time.monotonic() + wait_seconds
        while True:
            snapshot.unchanged(report["pins"])
            report["admission"] = lease.sample(
                available_memory_bytes(), other_builds(), config.POLICY, commit=False)
            report["samples"] += 1
            save()
            if report["admission"]["admitted"]:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("memory admission deadline reached; no compiler launched")
            time.sleep(min(10, remaining))
        report["status"] = "STARTING_INDEPENDENTLY_ADMITTED_BUILD"
        save()
        # The real runner acquires its atomic lease again; a race fails closed.
        built = execution.run(root, upstream, audit, control, environment, output / "build",
                              topology=topology, placement=placement)
        snapshot.unchanged(report["pins"])
        report["status"] = built["status"]
        report["build_result"] = artifact.identity(output / "build/results.json")
        save()
        return report
    except BaseException as error:
        report["status"] = "FAILED_RETAINED"
        report["errors"].append(repr(error))
        save()
        raise
