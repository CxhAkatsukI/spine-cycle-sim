"""Route after stable memory admission, with hard and sampled memory guards."""

import fcntl
import json
from pathlib import Path
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from ....empty_segment.route_environment.__main__ import execute
from ....empty_segment.route_environment.contract import reconstruct
from ....execution import identity
from .containment import GIB, current, other_builds, verify
from .admission import eligible, required_bytes, reservations


def unchanged(manifest: dict) -> None:
    if any(identity(Path(pin["path"])) != pin for pin in manifest["pins"]):
        raise ValueError("prepared route input changed; refusing execution")


def run(build: Path, output: Path) -> dict:
    record = output / "execution.json"
    if record.exists():
        raise FileExistsError("attempt already supervised; use a fresh preparation")
    manifest = json.loads((output / "manifest.json").read_text())
    if [manifest[key] for key in ("tree_memory_gib", "reserve_gib", "timeout_seconds",
                                 "queue_timeout_seconds")] != [40, 24, 21600, 86400]:
        raise ValueError("declared hardware safety policy differs")
    guard = verify(current())
    atomic_write_json(output / "containment.json", guard)
    lock = Path.home() / ".cache/spine-cycle-sim/sharded-k4-routing.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        started, consecutive = time.monotonic(), 0
        try:
            unchanged(manifest)
            while True:
                verify(current())
                available, active = available_memory_bytes(), other_builds()
                budgets = reservations(active, current()) if manifest.get("allow_bounded_builds", False) else active
                consecutive = consecutive + 1 if eligible(available, budgets, manifest) else 0
                state = {"status": "QUEUED_WAITING_FOR_SAFE_MEMORY", "route_started": False,
                    "available_gib": available / GIB, "required_gib": required_bytes(manifest, budgets) / GIB,
                    "other_builds": active, "build_reservations": budgets,
                    "allow_bounded_builds": manifest.get("allow_bounded_builds", False),
                    "consecutive_safe_samples": consecutive, "queue_seconds": time.monotonic() - started}
                atomic_write_json(record, state)
                if consecutive >= 8:
                    break
                if state["queue_seconds"] >= manifest["queue_timeout_seconds"]:
                    state["status"] = "QUEUE_TIMEOUT_NOT_STARTED"
                    atomic_write_json(record, state)
                    return state
                time.sleep(2)
            unchanged(manifest)
            environment, contract = reconstruct(build, output)
            if contract != json.loads((output / "environment.json").read_text()):
                raise ValueError("prepared route environment differs")
            atomic_write_json(record, {**state, "status": "ROUTING", "route_started": True})
            result = execute(output, manifest, environment, contract)
            result.update(route_started=True, cgroup=guard, queue_seconds=state["queue_seconds"])
            atomic_write_json(record, result)
            return result
        except BaseException as error:
            failure = {"status": "SUPERVISOR_FAILED", "error": str(error),
                       "route_started": json.loads(record.read_text()).get("route_started", False)
                       if record.exists() else False}
            atomic_write_json(output / "failure.json", failure)
            atomic_write_json(record, failure)
            raise
        finally:
            events = current() / "memory.events"
            if events.exists():
                atomic_write_json(output / "cgroup_events.json", dict(
                    line.split() for line in events.read_text().splitlines()))
