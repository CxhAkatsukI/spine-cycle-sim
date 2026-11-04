"""Replace only the source-property reader in the frozen CC banked link."""

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

KERNEL = "kernelHBMWrapper"
XO_NAME = KERNEL + ".hw.xilinx_u55c_gen3x16_xdma_3_202210_1.xo"


def derive(parent_path, execution_path, output, *, parent_sha256, execution_sha256):
    parent_pin, execution_pin = map(identity, (parent_path, execution_path))
    if (parent_pin["sha256"], execution_pin["sha256"]) != (parent_sha256, execution_sha256):
        raise ValueError("expected exact parent and component execution pins")
    parent = json.loads(parent_path.read_text())
    execution = json.loads(execution_path.read_text())
    if (parent.get("mode") != "destination" or parent.get("ip_cache_seed")
            or parent.get("change") != "banked fixed-frame gather only"
            or parent["gather_replacement"]["after"] not in parent["pins"]
            or execution.get("status") != "COMPONENT_XO_PASS_NOT_ROUTED"
            or execution.get("board_tested") is not False):
        raise ValueError("expected the banked CC parent and a successful component build")
    xos = replacement_capsule.layout(parent)
    if parent["gather_replacement"]["after"]["path"] not in xos:
        raise ValueError("banked gather is not in the frozen link")
    old_xo, = [Path(arg) for arg in xos if Path(arg).name == XO_NAME]
    old_pin = identity(old_xo)
    new_xo = Path(execution["xo"]["path"])
    new_pin = identity(new_xo)
    if (new_xo.name != XO_NAME or old_pin not in parent["pins"] or new_pin != execution["xo"]
            or old_pin["sha256"] == new_pin["sha256"]
            or kernel_interface(old_xo, KERNEL) != kernel_interface(new_xo, KERNEL)):
        raise ValueError("expected a distinct source wrapper with identical ABI and defines")

    command = list(parent["command"])
    command[command.index(str(old_xo))] = new_pin["path"]
    command[command.index("-o") + 1] = str(output.resolve() / "candidate.hw.xclbin")
    derived = {**parent, "command": command,
               "pins": [*parent["pins"], parent_pin, execution_pin, new_pin],
               "change": "CC source-property reader bursts on banked gather",
               "source_wrapper_replacement": {"parent": parent_pin, "component": execution_pin,
                                              "before": old_pin, "after": new_pin}}
    component.unchanged(derived["pins"])
    replacement_capsule.layout(derived)
    output.mkdir(parents=True, exist_ok=False)
    atomic_write_json(output / "manifest.json", derived)
    return derived


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("parent", "execution", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("parent-sha256", "execution-sha256"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    derive(args.parent, args.execution, args.output, parent_sha256=args.parent_sha256,
           execution_sha256=args.execution_sha256)


if __name__ == "__main__":
    main()
