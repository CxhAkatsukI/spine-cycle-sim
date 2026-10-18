"""Synthetic compilation/BD/full-link chain; not vendor execution evidence."""

from pathlib import Path
import shutil
from unittest.mock import patch

import original_grasu_return_fixture as original
from original_grasu_return_fixture import write
from test_original_grasu_physical_port import ASSETS, proof
from test_original_grasu_routed import TIMING
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware import configuration as config, gates, preparation, records
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.physical_port import delivery, probe, replay, route_inputs

BD_UNIT, BD_INVOCATION = "original-g-bd-test.service", "2" * 32


def state(unit):
    return dict(original.STATE, InvocationID=BD_INVOCATION) if unit == BD_UNIT else original.STATE


def chain(root, packet, compiled):
    original.finish(packet, compiled)
    (compiled / "hls").rename(compiled / "compile")
    built = records.read(compiled, "results.json")
    for name, row in zip(config.KERNELS, built["xos"]):
        row["hls"] = gates.inspect_hls(compiled / "compile" / name, name)
    built.update(status="FAILED_RETAINED", errors=["synthetic All 33 connections failure"])
    built["steps"][-1]["exit_code"] = 1
    write(compiled, "link.resources.json", {k: v for k, v in built["steps"][-1].items() if k != "id"})
    (compiled / "link.stdout.txt").write_text("All 33 connections are occupied")
    write(compiled, "results.json", built)
    bd, outer = root / "bd", root / "continuation"
    route = outer / "link_attempt"
    platform = root / "platform.xpfm"

    def lane(output, *, bd_parent=None):
        (output / "hooks").mkdir(parents=True)
        pins = preparation.verify(packet) + [identity(platform)]
        for name in ("pre_link.tcl", "post_link.tcl"):
            source, target = ASSETS / name, output / "hooks" / name
            shutil.copyfile(source, target)
            pins += [identity(source), identity(target)]
        proof(output / "hooks/physical_port.xml")
        write(output, "environment.json", records.read(compiled, "environment.json"))
        pins.append(identity(output / "environment.json"))
        timeout = 43200 if bd_parent is not None else 3600
        command = probe.link_command("/vendor/v++", platform, packet, compiled, output, bd_only=bd_parent is None)
        if bd_parent is not None:
            pins += bd_parent["pins"]
        write(output, "manifest.json", dict(pins=pins, command=command, policy=config.POLICY,
            timeout_seconds=timeout, bd_parent=bd_parent, source_modified=False, physical_interconnect_changed=True,
            scope="external_same_bank_fanin_full_link_not_timing_or_board_admission" if bd_parent is not None
            else "external_same_bank_fanin_BD_only_no_synthesis_routing_or_board"))
        step = dict(command=command, cwd=str(output), timeout_seconds=timeout, tree_memory_gib=40, reserve_gib=32,
                    exit_code=0, stop_reason="process_exit", cleanup_snapshot_error=None)
        write(output, "link.resources.json", step)
        for name in ("link.stdout.txt", "link.stderr.txt"):
            (output / name).write_text("")
        result = dict(status=replay.LINK_PASS if bd_parent is not None else route_inputs.PASS,
            errors=[], compiled_inputs=built["xos"], step=step, admission=dict(admitted=True),
            physical_port=probe.inspect_proof(output / "hooks/physical_port.xml"),
            containment=dict(limits={"memory.max": str(40 * 1024**3), "memory.high": str(36 * 1024**3),
                                     "memory.swap.max": "0", "memory.oom.group": "1"}),
            memory_events_after="oom 0\noom_kill 0\noom_group_kill 0\n", **dict.fromkeys(config.FLAGS, False))
        if bd_parent is not None:
            for name in delivery.PREFLIGHT:
                target = output / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(compiled / name, target)
            result["preflight"] = records.read(output, "preflight/results.json")
            result["bd_parent"] = bd_parent
            (output / "original_grasu.hw.xclbin").write_bytes(b"synthetic external-port bitstream")
            result["xclbin"] = identity(output / "original_grasu.hw.xclbin")
            report = output / "link/report/final" / delivery.direct.TIMING
            report.parent.mkdir(parents=True)
            report.write_text(TIMING)
        write(output, "results.json", result)

    lane(bd)
    with patch.object(route_inputs, "service_state", side_effect=state):
        parent = route_inputs.admit(packet, compiled, bd, unit=BD_UNIT, invocation=BD_INVOCATION)
    lane(route, bd_parent=parent)
    write(outer, "results.json", dict(status=replay.LINK_PASS, errors=[], profile=route_inputs.PROFILE,
        physical_interconnect_changed=True, pins=preparation.verify(packet), bd_parent=parent,
        child_report=identity(route / "results.json"), **dict.fromkeys(config.FLAGS, False)))
    return bd, outer
