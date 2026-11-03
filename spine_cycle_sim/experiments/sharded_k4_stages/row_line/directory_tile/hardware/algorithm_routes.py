"""Prepare an adapter-only relink of the eleven-XO SSSP or CC image."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.routing import adapter_interface, relocate_config
from . import component
from .algorithm_components import mode_for


def gate_sources(packet):
    # The compile command parser requires a fresh output, so inspect the recorded command.
    evidence = packet / "evidence"
    synth = evidence / "adapter"
    argv = json.loads((synth / "manifest.json").read_text())["command"]
    mode, _, _ = mode_for(packet, argv)
    summary = evidence / "execution.json"
    record = json.loads(summary.read_text())
    if record["status"] != "COMPONENT_GATES_PASS_NOT_ROUTED" or record["mode"] != mode:
        raise ValueError("passing algorithm-specific component gates required")
    xo = packet / "build/pma_to_regraph_adapter.hw.xo"
    candidate = identity(xo)
    if Path(argv[argv.index("-o") + 1]) != xo:
        raise ValueError("compiled adapter output differs from relink candidate")
    rtl = evidence / ("rtl-" + mode)
    paths = [summary]
    dependencies = []
    for directory, expected in ((synth, "COMPONENT_XO_PASS_NOT_ROUTED"),
                                (rtl, "FINITE_RANDOM_STALL_RTL_PASS_NOT_BOARD")):
        result, manifest = (directory / name for name in ("execution.json", "manifest.json"))
        report = json.loads(result.read_text())
        if report["status"] != expected or (directory == synth and report["xo"] != candidate):
            raise ValueError("adapter output or gate status changed")
        paths.extend((result, manifest))
        inputs = json.loads(manifest.read_text())["pins"]
        dependencies.append({p["path"]: p for p in inputs
                             if "spine_cycle_sim/experiments/" not in p["path"]})
    if any(dependencies[1].get(path) != pin for path, pin in dependencies[0].items()):
        raise ValueError("synthesis and RTL dependencies differ")
    component.unchanged(dependencies[1].values())
    return xo, mode, [*map(identity, paths), *dependencies[1].values()]


def prepare(production, packet, output):
    production, packet, output = map(Path.resolve, (production, packet, output))
    old_manifest = production / "manifest.json"
    old = json.loads(old_manifest.read_text())
    argv = list(old["command"])
    if ("--link" not in argv or argv[argv.index("--target") + 1] != "hw"
            or argv[argv.index("--kernel_frequency") + 1] != "150"):
        raise ValueError("expected production 150-MHz hardware link")
    xos = [Path(arg) for arg in argv if arg.endswith(".xo")]
    adapters = [p for p in xos if p.name == "pma_to_regraph_adapter.hw.xo"]
    if len(xos) != 11 or len(set(xos)) != 11 or len(adapters) != 1:
        raise ValueError("expected eleven distinct production XOs including one adapter")
    config = Path(argv[argv.index("--config") + 1])
    old_pins = {p["path"]: p for p in old["pins"]}
    for path in [config, *xos]:
        if old_pins.get(str(path), {}).get("sha256") != identity(path)["sha256"]:
            raise ValueError("production link input differs from its frozen route: " + str(path))
    candidate, mode, pins = gate_sources(packet)
    if adapter_interface(candidate) != adapter_interface(adapters[0]):
        raise ValueError("replacement changes adapter ABI or compile-time semantics")
    output.mkdir(parents=True, exist_ok=False)
    relocated = output / "link.cfg"
    relocated.write_text(relocate_config(config.read_text(), output))
    argv[argv.index(str(adapters[0]))] = str(candidate)
    argv[argv.index("--config") + 1] = str(relocated)
    argv[argv.index("-o") + 1] = str(output / "candidate.hw.xclbin")
    argv += ["--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2"]
    pins += [identity(p) for p in [old_manifest, config, relocated, candidate, *xos]]
    manifest = {"status": "PREPARED_NOT_ROUTED", "command": argv, "pins": pins,
                "packet": str(packet), "production": str(production), "mode": mode,
                "clock_mhz": 150, "board_tested": False, "timeout_seconds": 21600,
                "change": "adapter only; same eleven-XO production design and connectivity"}
    atomic_write_json(output / "manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("production", "packet", "output"):
        parser.add_argument("--" + argument, required=True, type=Path)
    args = parser.parse_args()
    print(prepare(args.production, args.packet, args.output)["status"])
