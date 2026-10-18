"""Require one terminal, unchanged external-port BD before a new full link."""

import json
from pathlib import Path
import re

from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import route_finished, service_state
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged
from .. import configuration as config, records
from . import probe

PASS = "PHYSICAL_PORT_BD_PASS_NOT_ROUTE_TIMING_OR_BOARD_ADMISSION"
PROFILE = "original_g_external_metadata_4to1_v1"


def service_identity(unit, invocation):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit) or \
            not re.fullmatch(r"[0-9a-f]{32}", invocation):
        raise ValueError("exact external-port BD service and invocation required")


def admit(packet, attempt, bd, *, unit, invocation):
    service_identity(unit, invocation)
    state = service_state(unit)
    if not route_finished(state, invocation):
        raise ValueError("external-port BD producer is still running")
    pins, compiled = probe.inputs(packet, attempt)
    read = lambda name: json.loads((bd / name).read_text())
    result, manifest, environment = (read(name) for name in
                                    ("results.json", "manifest.json", "environment.json"))
    if result.get("status") != PASS or result.get("errors") != [] or \
            result.get("compiled_inputs") != compiled or any(
                result.get(flag) is not False for flag in config.FLAGS) or \
            manifest.get("scope") != "external_same_bank_fanin_BD_only_no_synthesis_routing_or_board" or \
            manifest.get("policy") != config.POLICY or manifest.get("timeout_seconds") != 3600:
        raise ValueError("complete source-preserving external-port BD result required")
    observed = manifest.get("command", [])
    if not isinstance(observed, list) or not all(isinstance(item, str) for item in observed) or \
            observed.count("--platform") != 1 or observed[-1] == "--platform":
        raise ValueError("one pinned external-port BD platform required")
    platform = Path(observed[observed.index("--platform") + 1])
    if not platform.is_absolute() or identity(platform) not in manifest["pins"]:
        raise ValueError("external-port BD platform is not pinned")
    command = probe.link_command(environment["tools"]["v++"]["invocation"],
                                 platform, packet, attempt, bd, bd_only=True)
    step = result.get("step", {})
    records.clean_child(step)
    if manifest.get("command") != command or step != read("link.resources.json") or \
            step.get("command") != command or step.get("cwd") != str(bd) or \
            step.get("timeout_seconds") != 3600 or step.get("tree_memory_gib") != 40 or \
            step.get("reserve_gib") != 32 or result.get("admission", {}).get("admitted") is not True:
        raise ValueError("external-port BD command or bounded raw execution differs")
    proof = probe.inspect_proof(bd / "hooks/physical_port.xml")
    if result.get("physical_port") != proof:
        raise ValueError("external-port BD proof differs from the completed result")
    events = dict(line.split() for line in result.get("memory_events_after", "").splitlines())
    if any(events.get(key) != "0" for key in ("oom", "oom_kill", "oom_group_kill")):
        raise ValueError("external-port BD memory/OOM record missing or failed")
    limits = result.get("containment", {}).get("limits", {})
    if not all(str(limits.get(key, "")).isdigit() and 0 < int(limits[key]) <= bound * 1024**3
               for key, bound in (("memory.max", 40), ("memory.high", 36))) or \
            int(limits["memory.high"]) > int(limits["memory.max"]) or \
            limits.get("memory.swap.max") != "0" or limits.get("memory.oom.group") != "1":
        raise ValueError("external-port BD finite containment evidence missing or failed")
    pins += manifest["pins"]
    indexed = {pin["path"]: pin["sha256"] for pin in pins}
    for name in ("pre_link.tcl", "post_link.tcl"):
        source, copied = Path(probe.__file__).with_name(name), bd / "hooks" / name
        if identity(source)["sha256"] != identity(copied)["sha256"] or \
                indexed.get(str(copied)) != identity(copied)["sha256"]:
            raise ValueError("full link must use the exact tested external-port hooks")
    pins += [identity(bd / name) for name in ("results.json", "manifest.json", "environment.json",
        "link.resources.json", "link.stdout.txt", "link.stderr.txt", "hooks/physical_port.xml")]
    unchanged(pins)
    if service_state(unit) != state:
        raise ValueError("external-port BD service changed during admission")
    return {"profile": PROFILE, "bd": str(bd), "unit": unit, "invocation": invocation,
            "service": state, "pins": pins, "source_modified": False,
            "physical_interconnect_changed": True, "publication_performance_match": False}
