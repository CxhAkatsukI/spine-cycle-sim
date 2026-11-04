"""Replace ABI-checked components in the frozen production PageRank route."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.routing import (
    adapter_interface, kernel_interface, relocate_config,
)
from .component import environment, execute, unchanged
from .tail_publication import gather_replacement


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


def prepare(production, packet, output, *, gather_component=None, tail_hosts=None,
            source_wrapper=None, seed_production_cache=False):
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
    if (gather_component is None) != (tail_hosts is None):
        raise ValueError("tail publication requires a matched gather and host pair")
    changed = ["adapter"]
    if gather_component is not None:
        original = next(p for p in xos if p.name == "lksg_stream.hw.xo")
        gather, gather_pins = gather_replacement(original, gather_component, tail_hosts)
        argv[argv.index(str(original))] = str(gather)
        pins += gather_pins
        changed.append("gather")
    if source_wrapper is not None:
        wrapper = "kernelHBMWrapper"
        original, = [p for p in xos if p.name == wrapper + ".hw.xo"]
        source_wrapper = source_wrapper.resolve()
        if (source_wrapper.name != original.name
                or kernel_interface(source_wrapper, wrapper) != kernel_interface(original, wrapper)):
            raise ValueError("replacement changes the source wrapper ABI or compile-time semantics")
        argv[argv.index(str(original))] = str(source_wrapper)
        pins.append(identity(source_wrapper))
        changed.append("source wrapper")
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
                "change": " and ".join(changed) + " only; same twelve-XO production design and connectivity",
                "board_tested": False, "timeout_seconds": 21600}
    if tail_hosts is not None:
        manifest["tail_hosts"] = identity(tail_hosts)
    if seed_production_cache:
        from .cached_retry import seed_cache

        completed = production / "results.json"
        result = json.loads(completed.read_text())
        if result["status"] != "ROUTED_NOT_BOARD_TESTED" or result["steps"][-1]["exit_code"] != 0:
            raise ValueError("completed production cache required")
        seed = output / "ip-cache-seed.json"
        atomic_write_json(seed, seed_cache(production / "ip_cache", output / "ip_cache"))
        pins += [identity(completed), identity(seed)]
        manifest["ip_cache_seed"] = identity(seed)
    atomic_write_json(output / "manifest.json", manifest)
    return manifest


def run(output, *, admission_wait=0):
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    unchanged(manifest["pins"])
    if "ip_cache_seed" in manifest:
        from .cached_retry import validate_seed

        validate_seed(output, json.loads((output / "ip-cache-seed.json").read_text()))
    effective = environment(Path(manifest["packet"]))
    temporary = output / "tmp"
    temporary.mkdir()
    effective.update({key: str(temporary) for key in ("TMPDIR", "TMP", "TEMP")})
    return execute(output / "execution", manifest["command"], effective,
                   manifest["pins"] + [identity(manifest_path), identity(Path(__file__))], kind="LINK",
                   binary=output / "candidate.hw.xclbin", timeout=manifest["timeout_seconds"],
                   admission_wait=admission_wait)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", type=Path)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--gather-component", type=Path)
    parser.add_argument("--tail-hosts", type=Path)
    parser.add_argument("--source-wrapper", type=Path)
    parser.add_argument("--seed-production-cache", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--admission-wait", type=int, default=0)
    args = parser.parse_args()
    if args.execute:
        print(run(args.output.resolve(), admission_wait=args.admission_wait))
    else:
        if args.production is None or args.packet is None:
            parser.error("preparation requires --production and --packet")
        print(prepare(args.production, args.packet, args.output,
                      gather_component=args.gather_component, tail_hosts=args.tail_hosts,
                      source_wrapper=args.source_wrapper,
                      seed_production_cache=args.seed_production_cache))
