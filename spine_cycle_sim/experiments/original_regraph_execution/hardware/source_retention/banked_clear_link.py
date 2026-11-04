"""Derive a retention link that replaces only the gather XO."""

import argparse
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import (
    replacement_capsule,
)
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.routing import kernel_interface
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import (
    cached_retry, component,
)

XO_NAME = "lksg_stream.hw.xo"
CC = "cc-banked"
RESPR = "respr-lazy"
LAZY_CLEAR = "GRASU_REGRAPH_LAZY_GATHER_CLEAR"


def gather_abi(path, *, tail):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("lksg_stream/kernel.xml"))
    kernel = root.find("./kernel[@name='lksg_stream']")
    if kernel is None:
        raise ValueError("missing gather kernel metadata")
    ports = [port.attrib for port in kernel.findall("./ports/port")]
    args = [arg.attrib for arg in kernel.findall("./args/arg")]
    publication = [arg for arg in args if arg["name"] == "publication_rows"]
    if (not ports or not args or len(publication) != int(tail)
            or tail and publication[0]["id"] != "5"):
        raise ValueError("unexpected gather publication ABI")
    return {key: kernel.attrib[key] for key in ("name", "vlnv", "hwControlProtocol")}, ports, args


def derive(parent_path, gather_xo, output, *, parent_sha256, gather_sha256, profile=CC):
    parent_pin = identity(parent_path)
    new_pin = identity(gather_xo)
    if (parent_pin["sha256"] != parent_sha256 or new_pin["sha256"] != gather_sha256
            or gather_xo.name != XO_NAME):
        raise ValueError("expected exact parent and gather pins")
    parent = json.loads(parent_path.read_text())
    seed = parent.get("ip_cache_seed")
    tail = profile == RESPR
    if (profile not in (CC, RESPR)
            or parent.get("mode") != (None if tail else "destination")
            or bool(seed) != tail):
        raise ValueError("expected the frozen parent for the selected gather profile")
    xos = replacement_capsule.layout(parent)
    old_xo, = [Path(arg) for arg in xos if Path(arg).name == XO_NAME]
    old_pin = identity(old_xo)
    component.unchanged(parent["pins"])
    if (old_pin not in parent["pins"] or old_pin["sha256"] == new_pin["sha256"]
            or gather_abi(old_xo, tail=tail) != gather_abi(gather_xo, tail=tail)):
        raise ValueError("expected a distinct, ABI-compatible gather")
    if tail:
        _, old_flags = kernel_interface(old_xo, "lksg_stream")
        _, new_flags = kernel_interface(gather_xo, "lksg_stream")
        if (old_flags.get("GRASU_REGRAPH_TAIL_PUBLICATION") != "1"
                or LAZY_CLEAR in old_flags or new_flags != {**old_flags, LAZY_CLEAR: "1"}):
            raise ValueError("expected only the ResPR packed validity compile flag to change")
        if seed not in parent["pins"]:
            raise ValueError("unbound IP cache seed")
        inventory = json.loads(Path(seed["path"]).read_text())
        cached_retry.validate_seed(parent_path.parent, inventory)
    command = [new_pin["path"] if arg == str(old_xo) else arg for arg in parent["command"]]
    command[command.index("-o") + 1] = str(output.resolve() / "candidate.hw.xclbin")
    derived = {**parent, "command": command, "pins": [*parent["pins"], parent_pin, new_pin],
               "change": "packed validity gather only" if tail else "banked fixed-frame gather only",
               "gather_replacement": {"parent": parent_pin, "before": old_pin, "after": new_pin}}
    component.unchanged(derived["pins"])
    replacement_capsule.layout(derived)
    output.mkdir(parents=True, exist_ok=False)
    if tail:
        shutil.copytree(parent_path.parent / "ip_cache", output / "ip_cache")
        cached_retry.validate_seed(output, inventory)
    atomic_write_json(output / "manifest.json", derived)
    return derived


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parent", "gather", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("parent-sha256", "gather-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--profile", choices=(CC, RESPR), default=CC)
    args = parser.parse_args()
    derive(args.parent, args.gather, args.output, parent_sha256=args.parent_sha256,
           gather_sha256=args.gather_sha256, profile=args.profile)


if __name__ == "__main__":
    main()
