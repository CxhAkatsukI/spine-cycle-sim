"""Derive a CC link that replaces only the fixed-frame gather XO."""

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import (
    replacement_capsule,
)
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import component

XO_NAME = "lksg_stream.hw.xo"


def gather_abi(path):
    with zipfile.ZipFile(path) as archive:
        root = ET.fromstring(archive.read("lksg_stream/kernel.xml"))
    kernel = root.find("./kernel[@name='lksg_stream']")
    if kernel is None:
        raise ValueError("missing gather kernel metadata")
    ports = [port.attrib for port in kernel.findall("./ports/port")]
    args = [arg.attrib for arg in kernel.findall("./args/arg")]
    if not ports or not args or any(arg["name"] == "publication_rows" for arg in args):
        raise ValueError("expected a fixed-frame gather ABI")
    return {key: kernel.attrib[key] for key in ("name", "vlnv", "hwControlProtocol")}, ports, args


def derive(parent_path, gather_xo, output, *, parent_sha256, gather_sha256):
    parent_pin = identity(parent_path)
    new_pin = identity(gather_xo)
    if (parent_pin["sha256"] != parent_sha256 or new_pin["sha256"] != gather_sha256
            or gather_xo.name != XO_NAME):
        raise ValueError("expected exact parent and gather pins")
    parent = json.loads(parent_path.read_text())
    if parent.get("mode") != "destination" or parent.get("ip_cache_seed"):
        raise ValueError("expected the uncached CC destination parent")
    xos = replacement_capsule.layout(parent)
    old_xo, = [Path(arg) for arg in xos if Path(arg).name == XO_NAME]
    old_pin = identity(old_xo)
    component.unchanged(parent["pins"])
    if (old_pin not in parent["pins"] or old_pin["sha256"] == new_pin["sha256"]
            or gather_abi(old_xo) != gather_abi(gather_xo)):
        raise ValueError("expected a distinct, ABI-compatible fixed-frame gather")
    command = [new_pin["path"] if arg == str(old_xo) else arg for arg in parent["command"]]
    command[command.index("-o") + 1] = str(output.resolve() / "candidate.hw.xclbin")
    derived = {**parent, "command": command, "pins": [*parent["pins"], parent_pin, new_pin],
               "change": "banked fixed-frame gather only",
               "gather_replacement": {"parent": parent_pin, "before": old_pin, "after": new_pin}}
    component.unchanged(derived["pins"])
    replacement_capsule.layout(derived)
    output.mkdir(parents=True, exist_ok=False)
    atomic_write_json(output / "manifest.json", derived)
    return derived


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parent", "gather", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("parent-sha256", "gather-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    derive(args.parent, args.gather, args.output, parent_sha256=args.parent_sha256,
           gather_sha256=args.gather_sha256)


if __name__ == "__main__":
    main()
