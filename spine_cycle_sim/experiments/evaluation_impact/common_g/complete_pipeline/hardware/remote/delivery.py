"""Seal a terminal remote link for transport; do not rewrite its absolute pins."""

import json
from pathlib import Path
import re
import shutil
import socket

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ....continuous_board.execution.supervisor import route_finished, service_state
from ....search_pipeline.synthesis import unchanged
from . import capsule

SCHEMA = "remote-production-return-v1"
PASS = "LINK_PASS_AWAITING_TIMING_AND_BOARD"
LABELS = ("vitis_version", "vivado_version", "gcc_version", "gxx_version", "thread_compile", "thread_execute")
ROUTE_FILES = ("manifest.json", "execution.json", "environment.json", "link.cfg", "preflight/results.json",
               "route.stdout.txt", "route.stderr.txt", "route.resources.json", "candidate.hw.xclbin",
               *[f"preflight/{label}.{suffix}" for label in LABELS
                 for suffix in ("stdout.txt", "stderr.txt", "resources.json")])


def completed(execution, manifest, preflight):
    child = execution.get("route", {})
    if execution.get("status") != PASS or execution.get("errors") != [] or any(
            value.get(flag) is not False for value in (execution, manifest) for flag in capsule.FLAGS) or \
            type(child.get("exit_code")) is not int or child["exit_code"] != 0 or \
            child.get("stop_reason") != "process_exit" or "cleanup_snapshot_error" not in child or \
            child["cleanup_snapshot_error"] is not None:
        raise ValueError("successful unchanged remote link required, not queued/running/failed")
    commands = preflight.get("commands", [])
    if preflight.get("status") != "PREFLIGHT_PASS_NOT_ROUTED" or \
            tuple(row.get("label") for row in commands) != LABELS or any(
                type(row.get("exit_code")) is not int or row["exit_code"] != 0 or
                row.get("stop_reason") != "process_exit" or "cleanup_snapshot_error" not in row or
                row["cleanup_snapshot_error"] is not None for row in commands):
        raise ValueError("all six remote environment checks must pass")
    events = dict(line.split() for line in execution.get("memory_events_after", "").splitlines())
    if any(events.get(key) != "0" for key in ("oom", "oom_kill", "oom_group_kill")):
        raise ValueError("terminal remote cgroup evidence missing or OOM observed")


def seal(root, attempt, output, *, unit, invocation):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit) or \
            not re.fullmatch(r"[0-9a-f]{32}", invocation):
        raise ValueError("exact remote service and invocation required")
    state = service_state(unit)
    if not route_finished(state, invocation):
        raise ValueError("route service is still running; no return package")
    packet, parent = capsule.verify(root)
    execution = json.loads((attempt / "execution.json").read_text())
    manifest = json.loads((attempt / "manifest.json").read_text())
    preflight = json.loads((attempt / "preflight/results.json").read_text())
    completed(execution, manifest, preflight)
    expected = {"capsule": identity(root / "capsule.json"), "manifest": identity(attempt / "manifest.json"),
                "xclbin": identity(attempt / "candidate.hw.xclbin")}
    if any(execution.get(key) != value for key, value in expected.items()) or \
            execution.get("host") != socket.gethostname() or execution.get("parent") != packet["parent"] or \
            manifest.get("parent") != packet["parent"] or manifest.get("relocation") != expected["capsule"] or \
            manifest.get("clock_mhz") != 150 or manifest.get("policy") != capsule.POLICY:
        raise ValueError("remote terminal identities differ from the frozen production capsule")
    pins = [*manifest["pins"], *expected.values(), identity(attempt / "preflight/results.json")]
    unchanged(pins)
    reports = list((attempt / "reports").glob("**/impl_1_hw_bb_locked_timing_summary_routed.rpt"))
    if len(reports) != 1:
        raise ValueError("one final routed timing report required")
    output.mkdir(parents=True, exist_ok=False)
    files = []

    def copy(source, member):
        before = identity(source)
        target = output / member
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if identity(source) != before or sha256_file(target) != before["sha256"]:
            raise ValueError("return input changed during copy")
        files.append({"member": member, "source": before, "sha256": before["sha256"]})

    for member in ("capsule.json", *[row["member"] for row in packet["files"]]):
        copy(root / member, "capsule/" + member)
    for member in ROUTE_FILES:
        copy(attempt / member, "route/" + member)
    copy(reports[0], "route/timing.rpt")
    unchanged(pins)
    if service_state(unit) != state:
        raise ValueError("remote invocation changed during sealing")
    receipt = {"schema": SCHEMA, "status": "SEALED_LINK_NOT_TIMING_OR_BOARD_ADMISSION",
               "host": socket.gethostname(), "unit": unit, "invocation": invocation, "service": state,
               "remote_capsule": str(root), "remote_attempt": str(attempt), "files": files,
               "checked_remote_pin_count": len(manifest["pins"]), "parent": packet["parent"],
               **dict.fromkeys(capsule.FLAGS, False)}
    atomic_write_json(output / "receipt.json", receipt)
    return identity(output / "receipt.json")


def verify(output, digest):
    receipt_path = output / "receipt.json"
    if not re.fullmatch("[0-9a-f]{64}", digest) or sha256_file(receipt_path) != digest:
        raise ValueError("receipt differs from the digest obtained over trusted transport")
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("schema") != SCHEMA or receipt.get("status") != "SEALED_LINK_NOT_TIMING_OR_BOARD_ADMISSION" or \
            any(receipt.get(flag) is not False for flag in capsule.FLAGS) or \
            not route_finished(receipt["service"], receipt["invocation"]):
        raise ValueError("terminal remote return receipt required")
    seen = set()
    for row in receipt["files"]:
        member = Path(row["member"])
        if member.is_absolute() or ".." in member.parts or member in seen or \
                not (output / member).resolve().is_relative_to(output.resolve()):
            raise ValueError("unsafe or duplicate return member")
        seen.add(member)
        if sha256_file(output / member) != row["sha256"] or row["source"]["sha256"] != row["sha256"]:
            raise ValueError("returned artifact changed: " + str(member))
    packet, parent = capsule.verify(output / "capsule")
    expected = {"capsule/capsule.json", *["capsule/" + row["member"] for row in packet["files"]],
                *["route/" + member for member in (*ROUTE_FILES, "timing.rpt")]}
    if {str(member) for member in seen} != expected or receipt.get("parent") != packet["parent"]:
        raise ValueError("return package scope differs from production capsule")
    return receipt, packet, parent
