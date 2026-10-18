"""Check terminal original-G build records independently of transport or XRT."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote.delivery import LABELS
from . import configuration as config, preparation

PASS = "ORIGINAL_G_LINK_PASS_AWAITING_TIMING_CORRECTNESS_AND_BOARD"


def read(root, name):
    return json.loads((root / name).read_text())


def clean_child(row):
    if type(row.get("exit_code")) is not int or row["exit_code"] != 0 or \
            row.get("stop_reason") != "process_exit" or row.get("cleanup_snapshot_error", True) is not None:
        raise ValueError("original G child did not exit cleanly")


def completed(root, *, remote_route, remote_packet):
    execution, manifest, environment, probes = (read(root, name) for name in
        ("results.json", "manifest.json", "environment.json", "preflight/results.json"))
    if execution.get("status") != PASS or execution.get("errors") != [] or \
            execution.get("contract") != preparation.contract() or any(
                row.get(flag) is not False for row in (execution, manifest) for flag in config.FLAGS) or \
            manifest.get("source_modified") is not False or manifest.get("interface_compacted") is not False or \
            manifest.get("policy") != config.POLICY or manifest.get("compile_timeout_seconds") != 7200 or \
            manifest.get("link_timeout_seconds") != 43200:
        raise ValueError("successful source-preserving original G link required")
    if probes.get("status") != "PREFLIGHT_PASS_NOT_ROUTED" or \
            tuple(row.get("label") for row in probes.get("commands", [])) != LABELS:
        raise ValueError("all six original G environment probes required")
    for row in probes["commands"]:
        clean_child(row)
        if read(root, f"preflight/{row['label']}.resources.json") != {k: v for k, v in row.items() if k != "label"}:
            raise ValueError("original G raw probe differs")
    values = environment["effective"]["values"]
    legacy = Path(values["XILINX_HLS"]) / "include/etc"
    compiler = environment["tools"]["v++"]["invocation"]
    link = manifest["link"]
    platform = Path(link[link.index("--platform") + 1])
    compilations, expected_link = config.commands(compiler, platform, remote_packet, remote_route,
                                                 legacy_include=legacy)
    pins = manifest["pins"]
    indexed = {row["path"]: row["sha256"] for row in pins}
    if any(indexed[row["path"]] != row["sha256"] for row in pins) or \
            not platform.is_absolute() or str(platform) not in indexed or \
            manifest.get("compilations") != compilations or link != expected_link or any(
                str(legacy / name) not in indexed for name in ("ap_utils.h", "autopilot_ssdm_op.h")):
        raise ValueError("original G command/header/platform closure changed")
    expected_steps = [*("compile_" + name for name in config.KERNELS), "link"]
    steps = execution.get("steps", [])
    if [row.get("id") for row in steps] != expected_steps or len(execution.get("xos", [])) != len(config.KERNELS):
        raise ValueError("all original G compiles and one link required")
    for row, name in zip(steps, expected_steps):
        clean_child(row)
        raw = {k: v for k, v in row.items() if k != "id"}
        command = expected_link if name == "link" else compilations[name.removeprefix("compile_")]
        if read(root, name + ".resources.json") != raw or row.get("command") != command or \
                row.get("cwd") != str(remote_route) or row.get("tree_memory_gib") != 40 or \
                row.get("reserve_gib") != 32 or row.get("timeout_seconds") != (43200 if name == "link" else 7200):
            raise ValueError("original G raw build command or bounded policy differs")
    events = dict(line.split() for line in execution.get("memory_events_after", "").splitlines())
    if any(events.get(key) != "0" for key in ("oom", "oom_kill", "oom_group_kill")):
        raise ValueError("original G cgroup OOM evidence missing or failed")
    return execution, manifest
