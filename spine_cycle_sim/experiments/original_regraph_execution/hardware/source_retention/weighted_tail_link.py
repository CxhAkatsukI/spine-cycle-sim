"""Freeze the two-XO weighted SSSP tail variant and its matching host."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import (
    replacement_capsule,
)
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.routing import kernel_interface
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import component

GATHER = "lksg_stream"
MERGER = "kernelLittleGSMerger"
TAIL = "GRASU_REGRAPH_TAIL_PUBLICATION"
PUBLICATION_ROWS = {"name": "publication_rows", "addressQualifier": "0", "id": "5",
                    "port": "S_AXI_CONTROL", "size": "0x4", "offset": "0x30",
                    "hostOffset": "0x0", "hostSize": "0x4", "type": "unsigned int"}


def verify_interface(before, after, kernel):
    old, old_flags = kernel_interface(before, kernel)
    new, new_flags = kernel_interface(after, kernel)
    if (old_flags.get("HAVE_EDGE_PROP") != "1" or old_flags.get("HAVE_UNSIGNED_PROP") != "1"
            or old_flags.get("LITTLE_KERNEL_NUM") != "1" or TAIL in old_flags
            or new_flags != {**old_flags, TAIL: "1"}):
        raise ValueError("only weighted SSSP tail publication may change the compile flags")
    if kernel == GATHER:
        control, = [port for port in old["ports"] if port["name"] == "S_AXI_CONTROL"]
        if control["range"] != "0x30" or [arg["id"] for arg in old["args"]] != list(map(str, range(8))):
            raise ValueError("unexpected fixed-frame Gather control interface")
        control["range"] = "0x38"
        for arg in old["args"][5:]:
            arg["id"] = str(int(arg["id"]) + 1)
        old["args"].insert(5, PUBLICATION_ROWS)
    elif kernel != MERGER:
        raise ValueError("unexpected weighted tail kernel")
    if old != new:
        raise ValueError("weighted tail may only add the Gather publication_rows scalar")


def host_pins(host):
    pins = {name: identity(path) for name, path in (
        ("host", host), ("manifest", host.with_name("manifest.txt")),
        ("checksums", host.with_name("weighted_pma_native_host.sha256")))}
    flags = set(Path(pins["manifest"]["path"]).read_text().splitlines())
    path = pins["host"]["path"]
    checksums = Path(pins["checksums"]["path"]).read_text().splitlines()
    if (host.name != "sharded_k4_sssp_native_host"
            or not {"ALGORITHM=weighted_sssp", "PIPELINE_MODE=sharded-k4",
                    "PREFETCH_COMPACT=1", "TAIL_PUBLICATION=1", f"HOST={path}"} <= flags
            or [pins["host"]["sha256"], path] not in list(map(str.split, checksums))):
        raise ValueError("expected the matching checksummed weighted tail host")
    return pins


def check_bound_host(capsule, host, algorithm):
    if capsule is None:
        return []
    manifest = identity(Path(capsule) / "parent/manifest.json")
    parent = json.loads(Path(manifest["path"]).read_text())
    if "weighted_tail" not in parent:
        return []
    pins = host_pins(Path(host))
    if algorithm != "weighted_sssp" or pins != parent["weighted_tail"]["host"]:
        raise ValueError("board host differs from the exact weighted tail capsule")
    result = [manifest, *pins.values()]
    component.unchanged(result)
    return result


def derive(parent_path, gather, merger, host, output, *, expected):
    parent_pin = identity(parent_path)
    replacements = {GATHER: identity(gather), MERGER: identity(merger)}
    bound_host = host_pins(host)
    if [pin["sha256"] for pin in (parent_pin, *replacements.values(), bound_host["host"])] != expected:
        raise ValueError("exact weighted tail input digests required")
    parent = json.loads(parent_path.read_text())
    if parent.get("mode") != "weighted" or parent.get("ip_cache_seed") or parent.get("weighted_tail"):
        raise ValueError("expected a frozen weighted fixed-frame link")
    xos = [Path(arg) for arg in replacement_capsule.layout(parent)]
    command = list(parent["command"])
    before = {}
    for kernel, new in replacements.items():
        old, = [path for path in xos if path.name.split(".")[0] == kernel]
        before[kernel] = identity(old)
        if (old.name != Path(new["path"]).name or before[kernel] not in parent["pins"]
                or before[kernel]["sha256"] == new["sha256"]):
            raise ValueError("expected a distinct replacement for the pinned kernel")
        verify_interface(old, Path(new["path"]), kernel)
        command[command.index(str(old))] = new["path"]
    command[command.index("-o") + 1] = str(output.resolve() / "candidate.hw.xclbin")
    derived = {**parent, "command": command,
               "pins": [*parent["pins"], parent_pin, *replacements.values(), *bound_host.values()],
               "weighted_tail": {"parent": parent_pin, "before": before,
                                 "after": replacements, "host": bound_host}}
    component.unchanged(derived["pins"])
    replacement_capsule.layout(derived)
    output.mkdir(parents=True, exist_ok=False)
    atomic_write_json(output / "manifest.json", derived)
    return derived


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parent", "gather", "merger", "host", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--sha256", nargs=4, required=True,
                        metavar=("PARENT", "GATHER", "MERGER", "HOST"))
    args = parser.parse_args()
    derive(args.parent, args.gather, args.merger, args.host, args.output, expected=args.sha256)


if __name__ == "__main__":
    main()
