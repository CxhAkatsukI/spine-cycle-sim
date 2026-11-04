"""Continue a stopped SSSP matrix without replaying any measured FPGA arm."""

import json
from pathlib import Path
import re

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import service_state
from .follow import unchanged
from .runtime import identity


def require_stopped(unit):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.service", unit):
        raise ValueError("expected a specific stopped systemd service")
    state = service_state(unit)
    if state["ActiveState"] not in ("inactive", "failed") or state["MainPID"] != "0":
        raise ValueError(f"original service is still live: {unit}")
    return state


def load(source, rows):
    path, digest, parent = source
    journal = Path(path).resolve()
    stopped = {parent: require_stopped(parent)}
    pin = identity(journal)
    if pin["sha256"] != digest:
        raise ValueError("continuation journal does not match its pinned hash")
    previous = json.loads(journal.read_text())
    if (previous["status"] not in ("RUNNING_SINGLE_PASS", "FAILED_RETAINED")
            or (previous["repetitions_per_arm"], previous["warmups"]) != (1, 0)
            or previous["cases"].keys() != rows.keys()
            or not all(row.get("ready") for row in previous["prerequisites"].values())):
        raise ValueError("expected a stopped, admitted all-eight single-pass matrix")
    pending, pins = [], [pin]
    for ds, row in rows.items():
        old = previous["cases"][ds]
        if (row["case"], row["pins"]) != (old["case"], old["pins"]):
            raise ValueError(f"frozen case changed: {ds}")
        if old["status"] == "NOT_REQUESTED":
            pending.append(ds)
        elif old["status"] == "REQUESTED":
            unit, = (arg.split("=", 1)[1] + ".service" for arg in old["command"] if arg.startswith("--unit="))
            stopped[unit] = require_stopped(unit)
            path = journal.parent / ds.lower() / "results.json"
            pins.append(identity(path))
            child = json.loads(path.read_text())
            if (child.get("status") not in ("PREDECLARED", "WAITING_FOR_MEMORY", "WAITING_FOR_BOARD")
                    or child.get("attempts") != [] or child.get("arms") != {}
                    or child.get("dataset") != ds or child.get("algorithm") != "weighted_sssp"):
                raise ValueError(f"cannot resume an ambiguous or attempted case: {ds}")
            row["previous_preboard_result"] = pins[-1]
            pending.append(ds)
        elif old["status"] in ("MEASURED_RESIDENT_PAIR", "FAILED_RETAINED"):
            if "result" in old:
                pins.append(old["result"])
            row.update(old)
        else:
            raise ValueError(f"unrecognized prior case status: {ds}")
    unchanged(pins)
    return previous, sorted(pending, key=lambda ds: rows[ds]["case"]["memory_gib"]), pins, stopped


def claim(source, output):
    journal = Path(source[0]).resolve()
    # Exclusive marker: two continuations must not both start the same unmeasured arm.
    with (journal.parent / "continuation.claim").open("x") as stream:
        stream.write(str(output.resolve()) + "\n")
