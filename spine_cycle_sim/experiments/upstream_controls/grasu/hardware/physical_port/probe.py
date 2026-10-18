"""Inspect the original-G external interconnect, or link an admitted BD control."""

import argparse
import json
from pathlib import Path
import shutil
import socket
import sys
import time
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.link_runtime import run_link
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.concurrent import Lease
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import high_memory, memory_profiles
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.containment import current, other_builds, verify
from spine_cycle_sim.experiments.upstream_controls.execution import available_memory_bytes
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import environment
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment import probe as environment_probe
from spine_cycle_sim.experiments.sharded_k4_stages.empty_segment.route_environment.contract import require_unchanged
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged
from .. import configuration as config, gates, preparation, records

PROFILE = "original_g_external_metadata_4to1_common_attributes_v2"
HOOK_NAMES = ("pre_link.tcl", "post_link.tcl", "discovery.tcl")


def inputs(packet, attempt):
    pins = preparation.verify(packet)
    report = json.loads((attempt / "results.json").read_text())
    if (report.get("status") != "FAILED_RETAINED" or report.get("contract") != preparation.contract()
            or len(report.get("xos", [])) != 4
            or "All 33 connections" not in (attempt / "link.stdout.txt").read_text()):
        raise ValueError("expected retained original-G HMSS-capacity failure with all four compiled XOs")
    manifest = json.loads((attempt / "manifest.json").read_text())
    if manifest.get("source_modified") is not False or manifest.get("interface_compacted") is not False:
        raise ValueError("author source and all original interfaces must be preserved")
    unchanged(manifest["pins"])
    evidence = []
    for name in config.KERNELS:
        abi = gates.inspect_xo(attempt / "xo" / (name + ".hw.xo"), name)
        hls = gates.inspect_hls(attempt / "compile" / name, name)
        evidence.append({"abi": abi, "hls": hls})
        pins.extend((abi["xo"], hls["report"]))
    if evidence != report["xos"]:
        raise ValueError("compiled XO/HLS identities changed since the retained attempt")
    pins += [identity(attempt / name) for name in ("results.json", "manifest.json", "link.stdout.txt")]
    return pins, evidence


def inspect_proof(path):
    root = ET.parse(path).getroot()
    if root.tag != "physical_port" or root.attrib != {
            "profile": PROFILE, "masters": "46",
            "kernel_ingress": "22", "host_ingress": "1", "source_modified": "false",
            "routed": "false", "board_measured": "false"}:
        raise ValueError("unexpected physical-port diagnostic claim")
    groups = list(root)
    if len(groups) != 8:
        raise ValueError("eight complete metadata groups required")
    seen, slaves = set(), set()
    for group in groups:
        name = group.get("name")
        expected = {f"/g_metadata_{cu}_{half}": (cu, half)
                    for cu in range(1, 5) for half in range(2)}
        if group.tag != "group" or name not in expected or name in seen:
            raise ValueError("duplicate or unexpected group")
        seen.add(name)
        cu, half = expected[name]
        if (group.get("bank") != f"HBM_MEM{cu-1:02d}" or not group.get("clock")
                or not group.get("reset") or group.get("slave") in slaves
                or not (group.get("slave") or "").startswith("/hmss_0/S")):
            raise ValueError("metadata bank, clock/reset or HMSS ingress changed")
        slaves.add(group.get("slave"))
        if [child.attrib for child in group] != [
                {"name": f"/bin_search_{cu}/m_axi_gmem{half*4+index}"} for index in range(4)] \
                or any(child.tag != "master" for child in group):
            raise ValueError("all original metadata masters must remain in lane order")
    return {"proof": identity(path), "groups": 8, "retained_masters": 46,
            "kernel_ingress": 22, "host_ingress": 1}


def link_command(compiler, platform, packet, attempt, output, *, bd_only):
    _, command = config.commands(compiler, platform, packet, output, legacy_include="unused_for_link")
    command = [str(attempt / "xo" / Path(item).name) if item.endswith(".xo") else item for item in command]
    if bd_only:
        command += ["--to_step", "vpl.update_bd"]
    return [*command, "--xp", "param:compiler.userPreSysLinkTcl=" + str(output / "hooks/pre_link.tcl"),
            "--xp", "param:compiler.userPostSysLinkTcl=" + str(output / "hooks/post_link.tcl")]


def run(packet, attempt, output, environment_root, xilinx, platform, compatibility, *,
        bd_parent=None, memory_profile=None):
    policy = memory_profiles.select(config.POLICY, memory_profile)
    memory_profiles.host(policy)
    if memory_profile is not None and bd_parent is None:
        raise ValueError("high-memory profile requires the separately admitted full-link parent")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING_PHYSICAL_PORT_BD_DIAGNOSTIC", "errors": [],
              "host": socket.gethostname(), "policy": policy, "memory_profile": memory_profile,
              **dict.fromkeys(config.FLAGS, False)}
    save = lambda: atomic_write_json(output / "results.json", report)
    group, lease = None, None
    save()
    try:
        pins, report["compiled_inputs"] = inputs(packet, attempt)
        timeout, minimum_disk = (43200, 160) if bd_parent is not None else (3600, 80)
        if bd_parent is not None:
            from .route_inputs import admit
            checked = admit(packet, attempt, Path(bd_parent["bd"]),
                            unit=bd_parent["unit"], invocation=bd_parent["invocation"])
            if checked != bd_parent:
                raise ValueError("tested BD parent changed before full-link preparation")
            report["bd_parent"] = checked
            pins += checked["pins"]
        group = current()
        report["containment"] = verify(group)
        if shutil.disk_usage(output).free < minimum_disk * 1024**3:
            raise ValueError(f"{minimum_disk} GiB free disk required for external-port link")
        owner = high_memory.ObservedLease if memory_profiles.observed(policy) else Lease
        lease = owner(Path.home() / ".cache/spine-cycle-sim/compiler-reservations", group)
        for name in ("tmp", "user-data", "hooks"):
            (output / name).mkdir()
        for name in HOOK_NAMES:
            source = Path(__file__).with_name(name)
            shutil.copyfile(source, output / "hooks" / name)
            pins += [identity(source), identity(output / "hooks" / name)]
        effective, contract = environment.capture(environment_root, output, xilinx, platform, compatibility)
        atomic_write_json(output / "environment.json", contract)
        pins += contract["pins"] + [identity(output / "environment.json")]
        pins += [identity(Path(module.__file__)) for name, module in list(sys.modules.items())
                 if name.startswith("spine_cycle_sim.") and getattr(module, "__file__", None)]
        command = link_command(contract["tools"]["v++"]["invocation"], platform, packet, attempt,
                               output, bd_only=bd_parent is None)
        atomic_write_json(output / "manifest.json", {"pins": pins, "command": command,
            "policy": policy, "memory_profile": memory_profile, "timeout_seconds": timeout,
            "bd_parent": bd_parent, "source_modified": False, "physical_interconnect_changed": True,
            "scope": ("external_same_bank_fanin_full_link_not_timing_or_board_admission" if bd_parent is not None
                      else "external_same_bank_fanin_BD_only_no_synthesis_routing_or_board")})
        pins.append(identity(output / "manifest.json"))
        deadline = time.monotonic() + 86400
        while True:
            unchanged(pins)
            report["admission"] = lease.sample(available_memory_bytes(), other_builds(), policy, commit=True)
            report["status"] = "WAITING_FOR_COMPLETE_MEMORY_BUDGETS"
            save()
            if report["admission"]["admitted"]:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("physical port probe admission timed out")
            time.sleep(10)
        if bd_parent is not None:
            report["status"] = "ENVIRONMENT_PREFLIGHT"
            save()
            report["preflight"] = environment_probe.run(output, effective, contract)
            pins.append(identity(output / "preflight/results.json"))
            unchanged(pins)
            if admit(packet, attempt, Path(bd_parent["bd"]), unit=bd_parent["unit"],
                     invocation=bd_parent["invocation"]) != bd_parent:
                raise ValueError("tested BD parent changed before full link")
            require_unchanged(contract, effective)
        report["status"] = ("ROUTING_EXTERNAL_PORT_CONTROL_NOT_BOARD_ADMISSION" if bd_parent is not None
                            else "GENERATING_BD_NOT_ROUTING_OR_BOARD")
        save()
        report["step"] = run_link(command, output, output / "link", timeout=timeout,
                                  environment=effective, tree_memory_gib=40, reserve_gib=policy["reserve_gib"])
        records.clean_child(report["step"])
        unchanged(pins)
        report["physical_port"] = inspect_proof(output / "hooks/physical_port.xml")
        if bd_parent is not None:
            report["xclbin"] = identity(output / "original_grasu.hw.xclbin")
            report["status"] = "EXTERNAL_PORT_LINK_PASS_AWAITING_CLOCK_TIMING_AND_BOARD"
        else:
            report["status"] = "PHYSICAL_PORT_BD_PASS_NOT_ROUTE_TIMING_OR_BOARD_ADMISSION"
    except BaseException as error:
        report.update(status="FAILED_RETAINED", errors=[repr(error)])
        raise
    finally:
        if lease is not None:
            lease.release()
        if group is not None:
            report["memory_events_after"] = (group / "memory.events").read_text()
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("packet", "attempt", "output", "environment-root", "xilinx", "platform", "compatibility"):
        parser.add_argument("--" + option, required=True, type=Path)
    run(**vars(parser.parse_args()))
