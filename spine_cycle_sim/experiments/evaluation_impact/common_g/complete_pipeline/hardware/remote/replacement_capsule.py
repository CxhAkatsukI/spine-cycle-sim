"""Relocate a pinned, pre-synthesized K4 replacement link, not a board result."""

import argparse
import json
from pathlib import Path
import shutil

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import (
    cached_retry, component, memory_profiles,
)
from . import capsule, timing

SCHEMA = "k4-replacement-link-relocation-v1"


def layout(parent):
    argv = parent["command"]
    expected = {"--target": "hw", "--kernel_frequency": "150",
                "--vivado.synth.jobs": "2", "--vivado.impl.jobs": "2"}
    if any(argv.count(flag) != 1 or argv.index(flag) + 1 >= len(argv)
           for flag in (*expected, "--config", "-o")):
        raise ValueError("ambiguous frozen link command")
    if (argv[0] != "v++" or argv.count("--link") != 1 or "--compile" in argv
            or any(argv[argv.index(flag) + 1] != value for flag, value in expected.items())
            or parent["board_tested"] is not False or parent["clock_mhz"] != 150
            or parent["timeout_seconds"] not in (21600, 43200)
            or parent["status"] not in ("PREPARED_NOT_ROUTED", "CACHED_RETRY_PREPARED_NOT_ROUTED")):
        raise ValueError("expected a frozen two-job replacement link, not board evidence")
    xos = [arg for arg in argv if arg.endswith(".xo")]
    counts = {"weighted": 11, "destination": 11, None: 12}
    if (len(xos) != counts.get(parent.get("mode"))
            or len({Path(arg).name for arg in xos}) != len(xos)
            or not any(Path(arg).name == "pma_to_regraph_adapter.hw.xo" for arg in xos)):
        raise ValueError("wrong frozen XO set")
    return {arg: f"inputs/{Path(arg).name}" for arg in xos}


def inventory(root):
    return {str(path.relative_to(root)): sha256_file(path)
            for path in sorted(root.rglob("*")) if path.is_file()}


def check_cache(root, expected):
    if any(path.is_symlink() for path in root.rglob("*")) or inventory(root) != expected:
        raise ValueError("IP cache differs from the frozen seed")


def platform_pin(platform):
    if not platform.is_file() or platform.suffix != ".xpfm":
        raise ValueError("frozen XPFM platform required")
    return {"name": platform.name, "files": inventory(platform.parent)}


def prepare(previous, output, *, timing_profile=None):
    parent_path = previous / "manifest.json"
    parent_id = identity(parent_path)
    parent = json.loads(parent_path.read_text())
    replacements = layout(parent)
    component.unchanged(parent["pins"])
    pins = {row["path"]: row["sha256"] for row in parent["pins"]}
    output.mkdir(parents=True, exist_ok=False)
    files = []

    def copy(path, member, *, expected=None):
        pin = identity(path)
        if expected is not None and pin["sha256"] != expected:
            raise ValueError("parent input changed: " + str(path))
        target = output / member
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        if sha256_file(target) != pin["sha256"]:
            raise ValueError("copied input changed: " + member)
        files.append({"member": member, "source": pin, "sha256": pin["sha256"]})

    copy(parent_path, "parent/manifest.json", expected=parent_id["sha256"])
    for arg, member in replacements.items():
        copy(Path(arg), member, expected=pins[str(Path(arg).resolve())])
    config = Path(parent["command"][parent["command"].index("--config") + 1])
    timing.configure(config.read_text(), timing_profile)
    copy(config, "parent/link.cfg", expected=pins[str(config.resolve())])
    platform, = [Path(line.removeprefix("platform=")) for line in config.read_text().splitlines()
                 if line.startswith("platform=")]
    shim = Path(parent["packet"]) / "gcc_compat/bits/gthr-default.h"
    copy(shim, "gcc_compat/bits/gthr-default.h")
    cache = {}
    if parent.get("ip_cache_seed"):
        seed = Path(parent["ip_cache_seed"]["path"])
        copy(seed, "parent/ip-cache-seed.json", expected=pins[str(seed.resolve())])
        inventory_rows = json.loads(seed.read_text())
        cached_retry.validate_seed(previous, inventory_rows)
        for row in inventory_rows["files"]:
            member = row["relative"]
            cache[member] = row["sha256"]
            copy(previous / "ip_cache" / member, "cache/" + member, expected=cache[member])
    component.unchanged(parent["pins"] + [parent_id])
    packet = {"schema": SCHEMA, "parent": parent_id, "files": files,
              "platform": platform_pin(platform), "xo_replacements": replacements,
              "cache_files": cache, "policy": capsule.POLICY,
              "timeout_seconds": 43200, **dict.fromkeys(capsule.FLAGS, False)}
    if timing_profile is not None:
        packet["timing_profile"] = timing_profile
    atomic_write_json(output / "capsule.json", packet)
    verify(output, platform)
    return packet


def verify(root, platform):
    packet = json.loads((root / "capsule.json").read_text())
    if (packet["schema"] != SCHEMA or packet["policy"] != capsule.POLICY
            or packet["timeout_seconds"] != 43200 or packet["platform"] != platform_pin(platform)
            or any(packet[key] is not False for key in capsule.FLAGS)):
        raise ValueError("relocation, platform or resource contract changed")
    files = {}
    for row in packet["files"]:
        member = row["member"]
        path = root / member
        if (Path(member).is_absolute() or ".." in Path(member).parts or member in files
                or not path.resolve().is_relative_to(root.resolve())
                or sha256_file(path) != row["sha256"] or row["sha256"] != row["source"]["sha256"]):
            raise ValueError("unsafe or modified capsule member: " + member)
        files[member] = row["source"]
    parent = json.loads((root / "parent/manifest.json").read_text())
    timing.configure((root / "parent/link.cfg").read_text(), packet.get("timing_profile"))
    replacements = layout(parent)
    config = parent["command"][parent["command"].index("--config") + 1]
    expected_members = {"parent/manifest.json", "parent/link.cfg", "gcc_compat/bits/gthr-default.h",
                        *replacements.values()}
    pinned = {row["path"]: row["sha256"] for row in parent["pins"]}
    bindings = {config: "parent/link.cfg", **replacements}
    if (files["parent/manifest.json"] != packet["parent"]
            or replacements != packet["xo_replacements"]
            or any(files[member]["sha256"] != pinned.get(files[member]["path"])
                   for member in bindings.values())):
        raise ValueError("relocated files do not match the frozen parent")
    if parent.get("ip_cache_seed"):
        expected_members.add("parent/ip-cache-seed.json")
        if files["parent/ip-cache-seed.json"] != parent["ip_cache_seed"]:
            raise ValueError("cache inventory does not match the parent")
        seed = json.loads((root / "parent/ip-cache-seed.json").read_text())
        if packet["cache_files"] != {row["relative"]: row["sha256"] for row in seed["files"]}:
            raise ValueError("relocated cache does not match the parent")
        expected_members.update("cache/" + member for member in packet["cache_files"])
        check_cache(root / "cache", packet["cache_files"])
    elif packet["cache_files"]:
        raise ValueError("unplanned cache seed")
    if set(files) != expected_members:
        raise ValueError("unexpected or missing capsule members")
    return packet, parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("prepare")
    export.add_argument("--parent", required=True, type=Path)
    export.add_argument("--output", required=True, type=Path)
    export.add_argument("--timing-profile", choices=(timing.PROFILE,))
    execute = commands.add_parser("execute")
    for name in ("capsule", "output", "xilinx", "platform", "compatibility"):
        execute.add_argument("--" + name, required=True, type=Path)
    execute.add_argument("--capsule-sha256", required=True)
    execute.add_argument("--memory-profile", choices=memory_profiles.OBSERVED_PROFILES)
    args = parser.parse_args()
    if args.command == "prepare":
        print(prepare(args.parent.resolve(), args.output.resolve(),
                      timing_profile=args.timing_profile)["parent"]["sha256"])
    else:
        from . import study

        if sha256_file(args.capsule / "capsule.json") != args.capsule_sha256:
            raise ValueError("remote capsule differs from the locally exported capsule")
        report = study.run(*(getattr(args, name).resolve() for name in (
            "capsule", "output", "xilinx", "platform", "compatibility")),
            memory_profile=args.memory_profile, candidate=True)
        print(report["status"])


if __name__ == "__main__":
    main()
