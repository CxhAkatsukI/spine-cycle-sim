"""Seal terminal algorithm links without rewriting their remote source pins."""

import json
from pathlib import Path
import re
import shutil
import socket

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import memory_profiles
from ....continuous_board.execution.supervisor import route_finished, service_state
from ....search_pipeline.synthesis import unchanged
from ..remote.delivery import LABELS, ROUTE_FILES
from . import inputs, memory, routing

SCHEMA = "production-algorithm-link-return-v1"
PASS = "LINK_PASS_UNVERIFIED_RTL_AWAITING_TIMING_AND_BOARD"
FLAGS = ("rtl_admitted", "board_admitted", "publication_match")
MEMBERS = (*["route/" + name for name in ROUTE_FILES], "route/timing.rpt",
           "route/placement-review.json", "route/original-review/results.json",
           "compile/manifest.json", "compile/execution.json", "sources.json")


def completed(root):
    execution, manifest, probes = (json.loads((root / name).read_text()) for name in
                                 ("execution.json", "manifest.json", "preflight/results.json"))
    child = execution.get("route", {})
    profile = manifest.get("memory_profile")
    policy = memory.select(profile, check_host=False)
    memory_profiles.route_evidence(execution, policy, child)
    if execution.get("status") != PASS or execution.get("errors") != [] or any(
            record.get(flag) is not False for record in (execution, manifest) for flag in FLAGS):
        raise ValueError("terminal successful experimental algorithm link required")
    for row in (child, *probes.get("commands", [])):
        if type(row.get("exit_code")) is not int or row["exit_code"] != 0 or \
                row.get("stop_reason") != "process_exit" or \
                "cleanup_snapshot_error" not in row or row["cleanup_snapshot_error"] is not None:
            raise ValueError("link and all six preflight processes must exit cleanly")
    if probes.get("status") != "PREFLIGHT_PASS_NOT_ROUTED" or \
            tuple(row.get("label") for row in probes.get("commands", [])) != LABELS:
        raise ValueError("all six environment probes required")
    for row in probes["commands"]:
        raw = json.loads((root / f"preflight/{row['label']}.resources.json").read_text())
        if raw != {key: value for key, value in row.items() if key != "label"}:
            raise ValueError("raw environment record differs from summary")
    if json.loads((root / "route.resources.json").read_text()) != child or \
            child.get("command") != manifest.get("command") or \
            child.get("tree_memory_gib") != 40 or child.get("reserve_gib") != policy["reserve_gib"] or \
            child.get("timeout_seconds") != 43200 or manifest.get("policy") != policy or \
            manifest.get("clock_mhz") != 150 or manifest.get("algorithm") not in inputs.ALGORITHMS or \
            execution.get("algorithm") != manifest["algorithm"] or \
            execution.get("integration_revision") != manifest.get("integration_revision"):
        raise ValueError("raw link record, finite policy or algorithm differs")
    events = dict(line.split() for line in execution.get("memory_events_after", "").splitlines())
    if any(events.get(key) != "0" for key in ("oom", "oom_kill", "oom_group_kill")):
        raise ValueError("terminal cgroup must report zero OOM events")
    return execution, manifest


def seal(compilation, route, output, *, unit, invocation):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit) or \
            not re.fullmatch(r"[0-9a-f]{32}", invocation):
        raise ValueError("exact service and invocation required")
    state = service_state(unit)
    if not route_finished(state, invocation):
        raise ValueError("algorithm route is still running")
    execution, manifest = completed(route)
    compile_manifest = json.loads((compilation / "manifest.json").read_text())
    source_index = Path(compile_manifest["source_manifest"]["path"])
    source = inputs.verify(source_index.parent)
    pins = manifest["pins"]
    unchanged(pins)
    indexed = {pin["path"]: pin["sha256"] for pin in pins}
    required = (compilation / "manifest.json", compilation / "execution.json", source_index,
                route / "placement-review.json", route / "link.cfg", route / "environment.json")
    if any(indexed.get(str(path)) != identity(path)["sha256"] for path in required) or \
            execution.get("manifest") != identity(route / "manifest.json") or \
            execution.get("xclbin") != identity(route / "candidate.hw.xclbin") or \
            execution.get("host") != socket.gethostname() or \
            execution["route"].get("cwd") != str(route) or \
            compile_manifest.get("algorithm") != manifest["algorithm"] or \
            source["integration_revision"] != manifest["integration_revision"] or \
            compile_manifest.get("source_manifest") != identity(source_index):
        raise ValueError("completed link is not the declared unchanged source/compile closure")
    checked = json.loads((route / "placement-review.json").read_text())
    if checked.get("status") != routing.PASS:
        raise ValueError("successful fresh export and storage screen required")
    reports = list((route / "reports").glob("**/impl_1_hw_bb_locked_timing_summary_routed.rpt"))
    if len(reports) != 1:
        raise ValueError("one final routed timing report required")
    output.mkdir(parents=True, exist_ok=False)
    sources = {**{"route/" + name: route / name for name in ROUTE_FILES},
               "route/timing.rpt": reports[0],
               "route/placement-review.json": route / "placement-review.json",
               "route/original-review/results.json": route / "original-review/results.json",
               "compile/manifest.json": compilation / "manifest.json",
               "compile/execution.json": compilation / "execution.json", "sources.json": source_index}
    files = []
    for member in MEMBERS:
        original = sources[member]
        before = identity(original)
        target = output / member
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        if identity(original) != before or sha256_file(target) != before["sha256"]:
            raise ValueError("artifact changed during return copy")
        files.append({"member": member, "source": before, "sha256": before["sha256"]})
    unchanged(pins)
    if service_state(unit) != state:
        raise ValueError("route service changed during sealing")
    receipt = {"schema": SCHEMA, "status": "SEALED_LINK_NOT_TIMING_OR_BOARD_ADMISSION",
               "algorithm": manifest["algorithm"], "integration_revision": manifest["integration_revision"],
               "host": socket.gethostname(), "remote_route": str(route), "files": files,
               "checked_remote_pin_count": len(pins), "unit": unit, "invocation": invocation,
               "service": state, **dict.fromkeys(FLAGS, False)}
    atomic_write_json(output / "receipt.json", receipt)
    return identity(output / "receipt.json")


def verify(root, digest):
    if not re.fullmatch("[0-9a-f]{64}", digest) or sha256_file(root / "receipt.json") != digest:
        raise ValueError("return receipt differs from trusted SSH digest")
    receipt = json.loads((root / "receipt.json").read_text())
    if receipt.get("schema") != SCHEMA or receipt.get("status") != "SEALED_LINK_NOT_TIMING_OR_BOARD_ADMISSION" or \
            any(receipt.get(flag) is not False for flag in FLAGS) or \
            not route_finished(receipt["service"], receipt["invocation"]):
        raise ValueError("terminal unchanged algorithm receipt required")
    seen = set()
    for row in receipt["files"]:
        member = Path(row["member"])
        path = root / member
        if not member.parts or member.is_absolute() or ".." in member.parts or str(member) in seen or \
                path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("unsafe or duplicate returned member")
        if sha256_file(path) != row["sha256"] or row["source"]["sha256"] != row["sha256"]:
            raise ValueError("returned artifact changed: " + str(member))
        seen.add(str(member))
    if seen != set(MEMBERS):
        raise ValueError("incomplete or extra algorithm return members")
    return receipt
