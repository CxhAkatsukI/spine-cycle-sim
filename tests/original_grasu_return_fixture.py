"""Small synthetic source/build closure, never a tool or board result."""

import json
from pathlib import Path
import socket

from test_original_grasu_hardware import packet, xo
from test_original_grasu_routed import TIMING
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware import (
    configuration as config, delivery, gates, preparation, records)

INVOCATION = "1" * 32
UNIT = "original-g-test.service"
STATE = dict(LoadState="loaded", ActiveState="active", SubState="exited", Result="success",
             MainPID="0", ExecMainStatus="0", InvocationID=INVOCATION)


def write(root, name, data):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def build(root):
    source, route = root / "packet", root / "build"
    hashes = packet(source)
    route.mkdir()
    return source, route, hashes


def finish(source, route):
    vendor = route.parent / "vendor"
    legacy = vendor / "include/etc"
    legacy.mkdir(parents=True)
    pins = preparation.verify(source)
    for name in ("ap_utils.h", "autopilot_ssdm_op.h"):
        (legacy / name).write_text("synthetic header")
        pins.append(identity(legacy / name))
    platform = route.parent / "platform.xpfm"
    platform.write_text("synthetic platform")
    pins.append(identity(platform))
    write(route, "environment.json", {"effective": {"values": {"XILINX_HLS": str(vendor)}},
        "tools": {"v++": {"invocation": "/vendor/v++"}}})
    pins += [identity(route / "environment.json"), identity(route / "environment.json")]
    compiles, link = config.commands("/vendor/v++", platform, source, route, legacy_include=legacy)
    write(route, "manifest.json", {"pins": pins, "compilations": compiles, "link": link,
        "policy": config.POLICY, "source_modified": False, "interface_compacted": False,
        "compile_timeout_seconds": 7200, "link_timeout_seconds": 43200, **dict.fromkeys(config.FLAGS, False)})

    def child(command, timeout):
        return dict(command=command, cwd=str(route), exit_code=0, stop_reason="process_exit",
                    cleanup_snapshot_error=None, timeout_seconds=timeout, tree_memory_gib=40, reserve_gib=32)

    probes = []
    for label in records.LABELS:
        row = child(["synthetic", label], 60)
        probes.append(dict(row, label=label))
        write(route, f"preflight/{label}.resources.json", row)
    write(route, "preflight/results.json", {"status": "PREFLIGHT_PASS_NOT_ROUTED", "commands": probes})
    steps, xos = [], []
    (route / "xo").mkdir()
    for name in config.KERNELS:
        path = route / "xo" / (name + ".hw.xo")
        xo(path, name)
        directory = route / "hls" / name
        directory.mkdir(parents=True)
        (directory / (name + "_csynth.xml")).write_text(
            f"<Report><UserAssignments><Part>{config.PART}</Part>"
            "<TargetClockPeriod>6.66667</TargetClockPeriod></UserAssignments></Report>")
        xos.append(dict(abi=gates.inspect_xo(path, name), hls=gates.inspect_hls(directory, name)))
    for name, command in [*(('compile_' + k, c) for k, c in compiles.items()), ("link", link)]:
        row = child(command, 43200 if name == "link" else 7200)
        write(route, name + ".resources.json", row)
        steps.append(dict(row, id=name))
    for name in delivery.ROUTE_FILES:
        if name.endswith(".txt"):
            (route / name).write_text("")
    (route / "original_grasu.hw.xclbin").write_bytes(b"synthetic only")
    timing = route / "link/report/final" / delivery.TIMING
    timing.parent.mkdir(parents=True)
    timing.write_text(TIMING)
    result = dict(status=records.PASS, errors=[], host=socket.gethostname(), contract=preparation.contract(),
        manifest=identity(route / "manifest.json"), xclbin=identity(route / "original_grasu.hw.xclbin"),
        steps=steps, xos=xos, memory_events_after="oom 0\noom_kill 0\noom_group_kill 0\n",
        **dict.fromkeys(config.FLAGS, False))
    write(route, "results.json", result)
    return result
