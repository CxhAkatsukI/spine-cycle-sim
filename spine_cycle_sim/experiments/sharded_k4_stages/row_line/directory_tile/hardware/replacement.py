"""Replace only the adapter in an existing production route after RTL gates."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.routing import adapter_interface, relocate_config
from .component import environment, execute, unchanged


def gated_sources(packet):
    evidence = packet / "evidence"
    synthesis = evidence / "adapter/execution.json"
    rtl = evidence / "rtl-destination/execution.json"
    synth = json.loads(synthesis.read_text())
    simulation = json.loads(rtl.read_text())
    candidate = packet / "build/pma_to_regraph_adapter.hw.xo"
    if (synth["status"] != "COMPONENT_XO_PASS_NOT_ROUTED"
            or synth["xo"] != identity(candidate)
            or simulation["status"] != "FINITE_RANDOM_STALL_RTL_PASS_NOT_BOARD"):
        raise ValueError("candidate requires matching successful synthesis and finite RTL")
    sources, records = [], [identity(synthesis), identity(rtl)]
    for gate in (synthesis, rtl):
        manifest = gate.parent / "manifest.json"
        records.append(identity(manifest))
        pins = json.loads(manifest.read_text())["pins"]
        # Historical runner code remains recorded in its manifest, not a hardware dependency.
        selected = [p for p in pins if "spine_cycle_sim/experiments/" not in p["path"]]
        unchanged(selected)
        sources.append({p["path"]: p for p in selected})
    if any(sources[1].get(path) != pin for path, pin in sources[0].items()):
        raise ValueError("RTL and synthesis source dependencies differ")
    return candidate, records + list(sources[1].values())


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
    if len(xos) != 12 or len(adapters) != 1 or len(set(xos)) != 12:
        raise ValueError("expected twelve unique production PageRank XOs")
    old_pins = {p["path"]: p for p in old["pins"]}
    for xo in xos:
        if old_pins.get(str(xo), {}).get("sha256") != identity(xo)["sha256"]:
            raise ValueError("production XO differs from its frozen route")
    candidate, pins = gated_sources(packet)
    if adapter_interface(candidate) != adapter_interface(adapters[0]):
        raise ValueError("replacement changes adapter ABI or compile-time semantics")
    config = Path(argv[argv.index("--config") + 1])
    if old_pins.get(str(config)) != identity(config):
        raise ValueError("production connectivity changed")
    output.mkdir(parents=True, exist_ok=False)
    relocated = output / "link.cfg"
    relocated.write_text(relocate_config(config.read_text(), output))
    argv[argv.index(str(adapters[0]))] = str(candidate)
    argv[argv.index("--config") + 1] = str(relocated)
    argv[argv.index("-o") + 1] = str(output / "candidate.hw.xclbin")
    argv += ["--vivado.synth.jobs", "2", "--vivado.impl.jobs", "2"]
    pins += [identity(p) for p in [old_manifest, config, relocated, candidate, *xos]]
    manifest = {"status": "PREPARED_NOT_ROUTED", "command": argv, "pins": pins,
                "packet": str(packet), "production": str(production), "clock_mhz": 150,
                "change": "adapter only; same twelve-XO production design and connectivity",
                "board_tested": False, "timeout_seconds": 21600}
    atomic_write_json(output / "manifest.json", manifest)
    return manifest


def run(output):
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    unchanged(manifest["pins"])
    effective = environment(Path(manifest["packet"]))
    temporary = output / "tmp"
    temporary.mkdir()
    effective.update({key: str(temporary) for key in ("TMPDIR", "TMP", "TEMP")})
    return execute(output / "execution", manifest["command"], effective,
                   manifest["pins"] + [identity(manifest_path), identity(Path(__file__))], kind="LINK",
                   binary=output / "candidate.hw.xclbin", timeout=manifest["timeout_seconds"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", type=Path)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.execute:
        print(run(args.output.resolve()))
    else:
        if args.production is None or args.packet is None:
            parser.error("preparation requires --production and --packet")
        print(prepare(args.production, args.packet, args.output))
