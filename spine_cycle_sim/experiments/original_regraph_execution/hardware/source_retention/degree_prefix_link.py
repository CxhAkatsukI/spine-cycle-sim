"""Freeze a ResPR link with only the ordered degree-update XO replaced."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import (
    replacement_capsule,
)
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.routing import kernel_interface
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import (
    cached_retry, component,
)

KERNEL = "grasu_degree_update"
HOST_NAME = "sharded_k4_residual_pagerank_native_host"
PREFIX_ARG = {"name": "active_source_prefix", "addressQualifier": "0", "id": "5",
              "port": "S_AXI_CONTROL", "size": "0x4", "offset": "0x38",
              "hostOffset": "0x0", "hostSize": "0x4", "type": "unsigned int"}


def verify_interface(before, after):
    old, old_defines = kernel_interface(before, KERNEL)
    new, new_defines = kernel_interface(after, KERNEL)
    ports = {port["name"]: port for port in old["ports"]}
    master, control = ports["M_AXI_GMEM0"], ports["S_AXI_CONTROL"]
    if master["dataWidth"] != "64" or control["range"] != "0x38" or len(old["args"]) != 5:
        raise ValueError("expected the original five-argument degree update")
    master["dataWidth"], control["range"] = "512", "0x40"
    old["args"].append(PREFIX_ARG)
    if old != new or old_defines != new_defines:
        raise ValueError("degree replacement must preserve the existing stream, registers and compile defines")


def derive(parent_path, candidate, host, synthesis, protocol, output, *, parent_sha256, xo_sha256):
    parent_pin, new_pin = identity(parent_path), identity(candidate)
    if (parent_pin["sha256"] != parent_sha256 or new_pin["sha256"] != xo_sha256
            or candidate.name != f"{KERNEL}.hw.xo" or host.name != HOST_NAME):
        raise ValueError("exact parent, replacement XO and native ResPR host required")
    parent = json.loads(parent_path.read_text())
    seed = parent["ip_cache_seed"]
    if parent.get("mode") is not None or not parent.get("tail_hosts") or seed not in parent["pins"]:
        raise ValueError("the frozen ResPR tail-publication link is required")
    xos = replacement_capsule.layout(parent)
    old, = (Path(arg) for arg in xos if Path(arg).name == candidate.name)
    old_pin = identity(old)
    component.unchanged(parent["pins"])
    if old_pin not in parent["pins"] or old_pin["sha256"] == new_pin["sha256"]:
        raise ValueError("the original and a distinct replacement degree XO are required")
    verify_interface(old, candidate)
    host_manifest = host.with_name("manifest.txt")
    host_checksums = host.with_name("weighted_pma_native_host.sha256")
    flags = set(host_manifest.read_text().splitlines())
    if not {"ALGORITHM=residual_pagerank", "PIPELINE_MODE=sharded-k4", "PREFETCH_COMPACT=1",
            "TAIL_PUBLICATION=1", f"HOST={host.resolve()}"} <= flags:
        raise ValueError("native host must support the existing tail-publication ABI")
    pins = {"parent": parent_pin, "before": old_pin, "after": new_pin, "host": identity(host),
            "host_manifest": identity(host_manifest), "host_checksums": identity(host_checksums),
            "synthesis": identity(synthesis), "protocol": identity(protocol)}
    if not any(fields == [pins["host"]["sha256"], str(host.resolve())]
               for fields in map(str.split, host_checksums.read_text().splitlines())):
        raise ValueError("native host must match its build checksum")
    inventory = json.loads(Path(seed["path"]).read_text())
    cached_retry.validate_seed(parent_path.parent, inventory)
    command = [new_pin["path"] if arg == str(old) else arg for arg in parent["command"]]
    command[command.index("-o") + 1] = str(output.resolve() / "candidate.hw.xclbin")
    derived = {**parent, "command": command, "pins": [*parent["pins"], *pins.values()],
               "change": "ordered degree prefix cache; R components unchanged", "degree_prefix": pins}
    component.unchanged(derived["pins"])
    replacement_capsule.layout(derived)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(parent_path.parent / "ip_cache", output / "ip_cache")
    cached_retry.validate_seed(output, inventory)
    atomic_write_json(output / "manifest.json", derived)
    return derived


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parent", "candidate", "host", "synthesis", "protocol", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--parent-sha256", required=True)
    parser.add_argument("--xo-sha256", required=True)
    args = parser.parse_args()
    derive(args.parent, args.candidate, args.host, args.synthesis, args.protocol, args.output,
           parent_sha256=args.parent_sha256, xo_sha256=args.xo_sha256)


if __name__ == "__main__":
    main()
