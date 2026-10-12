"""Synthesize the single-master candidate and check its complete AXI RTL."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from ...empty_segment.production import require_report
from ...execution import identity
from ...routing import adapter_interface
from ..cross_row.study import compile_command
from ..cross_row.validation import FLAGS as V3_FLAGS, require_functional
from ..probe import probe
from ..validation import compare_traffic
from .study import ROOT, checked, freeze_sources, verify_pins


def run(integration, reference, output, vivado_bin):
    output.mkdir(parents=True, exist_ok=False)
    pins = freeze_sources(output, integration)
    pins.append(identity(reference))
    flags = V3_FLAGS | {"GRASU_REGRAPH_CONTINUOUS_DIRECTORY": "1"}
    build = output / "production"
    build.mkdir()
    command = compile_command(integration, build)
    command.insert(command.index("-D_GTHREAD_USE_COND_INIT_FUNC"), "-DGRASU_REGRAPH_CONTINUOUS_DIRECTORY=1")
    atomic_write_json(output / "manifest.json", {"sources": pins, "flags": flags, "command": command,
                      "claim": "production_HLS_and_synthetic_AXI_RTL_not_FPGA_timing"})
    checked(["bash", "scripts/check_pma_adapter_cross_row.sh", "--out-dir", str(output / "functional"),
             "--continuous-directory"], integration, output / "functional", timeout=240)
    require_functional((output / "functional.stdout.txt").read_text())
    verify_pins(pins)
    checked(command, build, build / "compile", timeout=1200, budget=8)
    candidate = build / "adapter.hw.xo"
    old_interface, old_flags = adapter_interface(reference)
    new_interface, new_flags = adapter_interface(candidate)
    if old_interface != new_interface:
        raise ValueError("candidate changed the external AXI/control/packet ABI")
    if ({k: v for k, v in old_flags.items() if k.startswith("GRASU_")} != V3_FLAGS or
            {k: v for k, v in new_flags.items() if k.startswith("GRASU_")} != flags):
        raise ValueError("unexpected production flags")
    hls = require_report(build)
    arms = {}
    for arm, xo in (("reference", reference), ("candidate", candidate)):
        arms[arm] = probe(ROOT, xo, output / arm, vivado_bin)
        print(arm, "FULL_AXI_RTL_PASS", flush=True)
    comparison = compare_traffic(arms["reference"], arms["candidate"])
    verify_pins(pins)
    result = {"status": "PASS_HLS_AXI_NOT_ROUTED", "interface": new_interface, "flags": flags,
              "hls": hls, "arms": arms, "comparison": comparison,
              "xo": identity(candidate), "hardware_timing_admitted": False}
    atomic_write_json(output / "results.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("integration", "reference", "output", "vivado-bin"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(**{name: path.resolve() for name, path in vars(args).items()})
        print(json.dumps({"status": result["status"]}))
    except BaseException as error:
        if args.output.is_dir():
            atomic_write_json(args.output / "failure.json", {"status": "FAILED_RETAINED", "error": repr(error)})
        raise


if __name__ == "__main__":
    main()
