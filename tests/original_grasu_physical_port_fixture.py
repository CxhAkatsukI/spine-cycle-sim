"""Synthetic external-port build records; never Vivado or board evidence."""

import json
from pathlib import Path
import shutil

from original_grasu_return_fixture import INVOCATION, STATE, UNIT, write
from test_original_grasu_physical_port import ASSETS, proof
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware import configuration as config
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.physical_port import probe, route_inputs


def build(root):
    packet, attempt, bd = (root / name for name in ("packet", "attempt", "bd"))
    for path in (packet, attempt, bd / "hooks"):
        path.mkdir(parents=True)
    platform = root / "platform.xpfm"
    platform.write_text("synthetic platform")
    pins = [identity(platform)]
    for name in probe.HOOK_NAMES:
        source, copied = ASSETS / name, bd / "hooks" / name
        shutil.copyfile(source, copied)
        pins += [identity(source), identity(copied)]
    compiled = [{"synthetic": "not an XO/HLS admission"}]
    command = probe.link_command("/vendor/v++", platform, packet, attempt, bd, bd_only=True)
    write(bd, "environment.json", {"tools": {"v++": {"invocation": "/vendor/v++"}}})
    pins.append(identity(bd / "environment.json"))
    write(bd, "manifest.json", {"pins": pins, "command": command, "policy": config.POLICY,
        "timeout_seconds": 3600, "scope": "external_same_bank_fanin_BD_only_no_synthesis_routing_or_board"})
    child = dict(command=command, cwd=str(bd), exit_code=0, stop_reason="process_exit",
        cleanup_snapshot_error=None, timeout_seconds=3600, tree_memory_gib=40, reserve_gib=32)
    write(bd, "link.resources.json", child)
    for name in ("link.stdout.txt", "link.stderr.txt"):
        (bd / name).write_text("")
    proof(bd / "hooks/physical_port.xml")
    write(bd, "results.json", {"status": route_inputs.PASS, "errors": [],
        "compiled_inputs": compiled, "step": child, "admission": {"admitted": True},
        "physical_port": probe.inspect_proof(bd / "hooks/physical_port.xml"),
        "containment": {"limits": {"memory.max": str(40 * 1024**3),
            "memory.high": str(36 * 1024**3), "memory.swap.max": "0", "memory.oom.group": "1"}},
        "memory_events_after": "oom 0\noom_kill 0\noom_group_kill 0\n",
        **dict.fromkeys(config.FLAGS, False)})
    return packet, attempt, bd, platform, compiled


def change(root, name, mutate):
    path = root / name
    value = json.loads(path.read_text())
    mutate(value)
    write(root, name, value)
