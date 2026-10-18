"""Seal and verify the original nine-CU GraSU artifact; never admits a board."""

from pathlib import Path
import re
import shutil
import socket

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import route_finished, service_state
from spine_cycle_sim.experiments.evaluation_impact.common_g.search_pipeline.synthesis import unchanged
from . import configuration as config, preparation, records

SCHEMA = "original-grasu-link-return-v1"
TIMING = "impl_1_hw_bb_locked_timing_summary_routed.rpt"
ROUTE_FILES = ("results.json", "manifest.json", "environment.json", "original_grasu.hw.xclbin",
    "preflight/results.json", *[f"preflight/{label}.{suffix}" for label in records.LABELS
        for suffix in ("stdout.txt", "stderr.txt", "resources.json")],
    *[name + "." + suffix for name in (*(f"compile_{k}" for k in config.KERNELS), "link")
        for suffix in ("stdout.txt", "stderr.txt", "resources.json")])
MEMBERS = (*["route/" + name for name in ROUTE_FILES], "route/" + TIMING,
    *["route/xo/" + name + ".hw.xo" for name in config.KERNELS],
    *["route/hls/" + name + "/" + name + "_csynth.xml" for name in config.KERNELS],
    "packet/packet.json", "packet/link.cfg", *["packet/source/" + name for name in config.SOURCE_HASHES])


def seal(packet, attempt, output, *, unit, invocation):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@:-]*\.service", unit) or \
            not re.fullmatch(r"[0-9a-f]{32}", invocation):
        raise ValueError("exact original G service and invocation required")
    state = service_state(unit)
    if not route_finished(state, invocation):
        raise ValueError("original G build is still running")
    packet_pins = preparation.verify(packet)
    execution, manifest = records.completed(attempt, remote_route=attempt, remote_packet=packet)
    pins = [*manifest["pins"], *packet_pins]
    unchanged(pins)
    if execution.get("host") != socket.gethostname() or \
            execution.get("manifest") != identity(attempt / "manifest.json") or \
            execution.get("xclbin") != identity(attempt / "original_grasu.hw.xclbin"):
        raise ValueError("original G terminal artifact identities differ")
    reports = list((attempt / "link/report").glob("**/" + TIMING))
    if len(reports) != 1:
        raise ValueError("one original G final routed report required")
    originals = {**{"route/" + name: attempt / name for name in ROUTE_FILES},
        "route/" + TIMING: reports[0], **{"packet/" + str(Path(pin["path"]).relative_to(packet)): Path(pin["path"])
            for pin in packet_pins}}
    for name, row in zip(config.KERNELS, execution["xos"]):
        originals["route/xo/" + name + ".hw.xo"] = Path(row["abi"]["xo"]["path"])
        originals["route/hls/" + name + "/" + name + "_csynth.xml"] = Path(row["hls"]["report"]["path"])
        unchanged([row["abi"]["xo"], row["hls"]["report"]])
    output.mkdir(parents=True, exist_ok=False)
    files = []
    for member in MEMBERS:
        source = originals[member]
        before = identity(source)
        target = output / member
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if identity(source) != before or sha256_file(target) != before["sha256"]:
            raise ValueError("original G artifact changed during return")
        files.append({"member": member, "source": before, "sha256": before["sha256"]})
    unchanged(pins)
    if service_state(unit) != state:
        raise ValueError("original G service changed during sealing")
    receipt = {"schema": SCHEMA, "status": "SEALED_LINK_NOT_TIMING_OR_BOARD_ADMISSION",
        "host": socket.gethostname(), "remote_attempt": str(attempt), "remote_packet": str(packet),
        "unit": unit, "invocation": invocation, "service": state, "files": files,
        "checked_remote_pin_count": len(manifest["pins"]), **dict.fromkeys(config.FLAGS, False)}
    atomic_write_json(output / "receipt.json", receipt)
    return identity(output / "receipt.json")


def verify(root, digest):
    if not re.fullmatch(r"[0-9a-f]{64}", digest) or sha256_file(root / "receipt.json") != digest:
        raise ValueError("original G receipt differs from trusted SSH digest")
    receipt = records.read(root, "receipt.json")
    if receipt.get("schema") != SCHEMA or receipt.get("status") != "SEALED_LINK_NOT_TIMING_OR_BOARD_ADMISSION" or \
            any(receipt.get(flag) is not False for flag in config.FLAGS) or \
            not route_finished(receipt["service"], receipt["invocation"]):
        raise ValueError("terminal source-preserving original G receipt required")
    seen = set()
    for row in receipt["files"]:
        member = Path(row["member"])
        path = root / member
        if not member.parts or member.is_absolute() or ".." in member.parts or str(member) in seen or \
                path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("unsafe or duplicate original G return member")
        if sha256_file(path) != row["sha256"] or row["source"]["sha256"] != row["sha256"]:
            raise ValueError("original G returned artifact changed")
        seen.add(str(member))
    actual = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file() or path.is_symlink()}
    if seen != set(MEMBERS) or actual != seen | {"receipt.json"}:
        raise ValueError("original G returned scope is incomplete or extra")
    preparation.verify(root / "packet")
    return receipt
