"""Transport the distinct external-port profile without rewriting frozen records."""

import argparse
from pathlib import Path
import re
import shutil
import socket

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged
from .. import configuration as config, delivery as direct, preparation, records
from . import probe, route_inputs

SCHEMA = "original-grasu-external-port-return-v1"
STATUS = "SEALED_EXTERNAL_PORT_LINK_NOT_TIMING_OR_BOARD_ADMISSION"
TEXT = ("results.json", "manifest.json", "environment.json")
RAW = tuple("link." + suffix for suffix in ("stdout.txt", "stderr.txt", "resources.json"))
HOOKS = tuple("hooks/" + name for name in ("pre_link.tcl", "post_link.tcl", "physical_port.xml"))
PREFLIGHT = ("preflight/results.json", *[f"preflight/{label}.{suffix}" for label in records.LABELS
    for suffix in ("stdout.txt", "stderr.txt", "resources.json")])
COMPILES = tuple(f"compile_{name}.{suffix}" for name in config.KERNELS
                 for suffix in ("stdout.txt", "stderr.txt", "resources.json"))


def members():
    return {"continuation/results.json", *["packet/" + name for name in (
        "packet.json", "link.cfg", *["source/" + name for name in config.SOURCE_HASHES])],
        *["compiled/" + name for name in (*TEXT, *RAW, *COMPILES, *PREFLIGHT)],
        *[f"compiled/xo/{name}.hw.xo" for name in config.KERNELS],
        *[f"compiled/hls/{name}/{name}_csynth.xml" for name in config.KERNELS],
        *["bd/" + name for name in (*TEXT, *RAW, *HOOKS)],
        *["route/" + name for name in (*TEXT, *RAW, *HOOKS, *PREFLIGHT,
            "original_grasu.hw.xclbin", direct.TIMING)]}


def seal(packet, continuation, output, *, unit, invocation):
    route_inputs.service_identity(unit, invocation)
    state = route_inputs.service_state(unit)
    if not route_inputs.route_finished(state, invocation):
        raise ValueError("external-port full-link producer is still running")
    outer = records.read(continuation, "results.json")
    route = continuation / "link_attempt"
    result, manifest = (records.read(route, name) for name in TEXT[:2])
    parent = manifest["bd_parent"]
    bd = Path(parent["bd"])
    command = manifest["command"]
    xos = [Path(item) for item in command if item.endswith(".xo")]
    if len(xos) != 4 or len({path.parent.parent for path in xos}) != 1:
        raise ValueError("one retained compilation parent with four XOs required")
    compiled = xos[0].parent.parent
    checked = route_inputs.admit(packet, compiled, bd, unit=parent["unit"], invocation=parent["invocation"])
    if checked != parent or outer.get("child_report") != identity(route / "results.json"):
        raise ValueError("exact BD or full-link child identity changed")
    records.compilations(compiled, remote_route=compiled, remote_packet=packet)
    pins, _ = probe.inputs(packet, compiled)
    pins += checked["pins"] + manifest["pins"] + outer["pins"]
    unchanged(pins)
    reports = list((route / "link/report").glob("**/" + direct.TIMING))
    if len(reports) != 1:
        raise ValueError("one final external-port routed timing report required")
    roots = dict(packet=str(packet), compiled=str(compiled), bd=str(bd), route=str(route),
                 continuation=str(continuation))
    originals = {member: Path(roots[member.split("/", 1)[0]]) / member.split("/", 1)[1]
                 for member in members()}
    originals["route/" + direct.TIMING] = reports[0]
    for name, row in zip(config.KERNELS, result["compiled_inputs"]):
        originals[f"compiled/hls/{name}/{name}_csynth.xml"] = Path(row["hls"]["report"]["path"])
    output.mkdir(parents=True, exist_ok=False)
    files = []
    for member, source in sorted(originals.items()):
        before = identity(source)
        target = output / member
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if identity(source) != before or sha256_file(target) != before["sha256"]:
            raise ValueError("external-port evidence changed during sealing")
        files.append(dict(member=member, source=before, sha256=before["sha256"]))
    receipt = dict(schema=SCHEMA, status=STATUS, profile=route_inputs.PROFILE,
        source_modified=False, physical_interconnect_changed=True, roots=roots,
        host=socket.gethostname(), unit=unit, invocation=invocation, service=state,
        files=files, **dict.fromkeys(config.FLAGS, False))
    from .replay import validate
    validate(output, receipt)
    unchanged(pins)
    if route_inputs.service_state(unit) != state:
        raise ValueError("external-port producer changed during sealing")
    atomic_write_json(output / "receipt.json", receipt)
    return identity(output / "receipt.json")


def verify(root, digest):
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or sha256_file(root / "receipt.json") != digest:
        raise ValueError("external-port receipt differs from trusted SSH digest")
    receipt = records.read(root, "receipt.json")
    route_inputs.service_identity(receipt["unit"], receipt["invocation"])
    if receipt.get("schema") != SCHEMA or receipt.get("status") != STATUS or \
            receipt.get("profile") != route_inputs.PROFILE or receipt.get("source_modified") is not False or \
            receipt.get("physical_interconnect_changed") is not True or any(
                receipt.get(flag) is not False for flag in config.FLAGS) or \
            not route_inputs.route_finished(receipt["service"], receipt["invocation"]):
        raise ValueError("terminal external-port receipt with separate physical profile required")
    seen, sources = set(), set()
    for row in receipt["files"]:
        member, source = Path(row["member"]), Path(row["source"]["path"])
        path = root / member
        if str(member) not in members() or str(member) in seen or str(source) in sources or \
                not source.is_absolute() or ".." in source.parts or path.is_symlink() or \
                not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("unsafe or duplicate external-port return member")
        if sha256_file(path) != row["sha256"] or row["source"]["sha256"] != row["sha256"]:
            raise ValueError("external-port returned evidence changed")
        seen.add(str(member))
        sources.add(str(source))
    actual = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file() or path.is_symlink()}
    if seen != members() or actual != seen | {"receipt.json"}:
        raise ValueError("external-port return scope is incomplete or extra")
    preparation.verify(root / "packet")
    from .replay import validate
    validate(root, receipt)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("packet", "continuation", "output"):
        parser.add_argument("--" + option, type=Path, required=True)
    for option in ("unit", "invocation"):
        parser.add_argument("--" + option, required=True)
    print(seal(**vars(parser.parse_args()))["sha256"], flush=True)
