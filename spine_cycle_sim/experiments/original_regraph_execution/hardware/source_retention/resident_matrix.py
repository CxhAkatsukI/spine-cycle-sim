"""Shared single-pass FPGA child execution and high-active R admission."""

import json
from pathlib import Path
import subprocess
import sys

from .. import artifact
from ..board_execution import active_min_follow
from . import active_min_admission, active_min_resident as resident
from .follow import unchanged
from .runtime import identity


MEASURED = "MEASURED_RESIDENT_PAIR"
INPUTS = ("previous", "route", "host", "r_report", "r_inputs", "g_report", "g_reference")


def admitted_odd(args, gate):
    journal = args.odd_output / "queue.json"
    result = args.odd_output / "pair/results.json"
    fixture = active_min_follow.fixture_pin(args, [])
    pins = [identity(journal), identity(result), fixture]
    queue = json.loads(journal.read_text())
    unchanged(pins)
    if (queue.get("status"), queue.get("result"), queue.get("retention_gate_pass")) != (
            "PAIRED_ACTIVE_MIN_R_GATE_PASS", artifact.identity(result), True) or fixture not in queue["pins"]:
        raise ValueError("odd-frontier R queue did not admit the frozen hardware result")
    odd = active_min_admission.replay_r(result, args.algorithm, args.odd_inputs, gate["host"], gate["image"])
    if (odd["report"] != pins[1] or
            odd["candidate_clock"]["driver_reported_mhz"] != gate["resident_mhz"]):
        raise ValueError("odd-frontier R screen did not use the admitted image and clock")
    return odd, pins


def child_service(prefix, dataset, budget, module):
    return [
        "systemd-run", "--user", "--wait", "--collect",
        f"--unit={prefix}-{dataset.lower()}", f"--working-directory={Path.cwd()}",
        f"--property=MemoryMax={budget}G", f"--property=MemoryHigh={budget - 2}G",
        "--property=MemorySwapMax=0", "--property=OOMPolicy=kill", "--property=KillMode=control-group",
        "--property=RuntimeMaxSec=8h", sys.executable, "-m", module,
    ]


def child_command(args, dataset, budget, output, *, packet=None):
    comparison = ("--cc-wall-packet", packet) if packet is not None else ("--comparator", args.comparator)
    return [
        *child_service(args.child_prefix, dataset, budget, resident.__spec__.name),
        "--algorithm", args.algorithm, "--dataset", dataset, "--output", str(output),
        "--wait-seconds", str(args.wait_seconds), comparison[0], str(comparison[1]),
        *(part for key in INPUTS for part in ("--" + key.replace("_", "-"), str(getattr(args, key)))),
    ]


def run_child(command, log, output, dataset, gate, boundary):
    with log.open("x") as stream:
        job = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=8 * 3600 + 60)
    evidence = {"status": "FAILED_RETAINED", "service_exit": job.returncode}
    result = output / "results.json"
    if result.is_file():
        pin = identity(result)
        child = json.loads(result.read_text())
        unchanged([pin])
        evidence.update(result=pin, child_status=child.get("status"), attempts=child.get("attempts"))
        if child.get("status") == MEASURED:
            if (child.get("stage_gates"), child.get("dataset"), child.get("boundary"),
                    child.get("repetitions_per_arm"), child.get("warmups"), child.get("attempts")) != (
                        gate, dataset, boundary, 1, 0, ["spine", "gr"]):
                raise ValueError(f"{dataset} result differs from the admitted single-pass protocol")
            if job.returncode == 0:
                evidence["status"] = MEASURED
    return evidence
