"""Admit a returned production link with local strict timing/topology checks."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages import bitstream
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ....production_board import route as production
from ....search_pipeline.synthesis import unchanged
from ..preparation import COUNTS
from . import capsule, delivery, timing as physical_timing


def review(returned, original, output, *, parent_directory, receipt_sha256):
    receipt, packet, parent = delivery.verify(returned, receipt_sha256)
    if identity(parent_directory / "manifest.json") != packet["parent"]:
        raise ValueError("returned link is not the requested local production packet")
    production.candidate(parent)
    route = returned / "route"
    manifest = json.loads((route / "manifest.json").read_text())
    execution = json.loads((route / "execution.json").read_text())
    preflight = json.loads((route / "preflight/results.json").read_text())
    environment = json.loads((route / "environment.json").read_text())
    delivery.completed(execution, manifest, preflight)
    if json.loads((route / "route.resources.json").read_text()) != execution["route"]:
        raise ValueError("raw route resource record differs from terminal execution")
    for row in preflight["commands"]:
        resource = json.loads((route / f"preflight/{row['label']}.resources.json").read_text())
        if resource != {key: value for key, value in row.items() if key != "label"}:
            raise ValueError("raw preflight resource record differs from its summary")
    remote_root, remote_route = Path(receipt["remote_capsule"]), Path(receipt["remote_attempt"])
    indexed = {row["member"]: row for row in receipt["files"]}
    for key, member in (("capsule", "capsule/capsule.json"), ("manifest", "route/manifest.json"),
                        ("xclbin", "route/candidate.hw.xclbin")):
        if execution.get(key) != indexed[member]["source"]:
            raise ValueError("remote terminal artifact identity changed")
    expected_command = capsule.command(packet, parent, remote_root, remote_route,
                                       environment["tools"]["v++"]["invocation"])
    config = (route / "link.cfg").read_text()
    platforms = [line.split("=", 1)[1] for line in config.splitlines() if line.startswith("platform=")]
    if len(platforms) != 1:
        raise ValueError("one remote platform required")
    expected_config = physical_timing.configure(capsule.configuration(
        (returned / "capsule/parent/link.cfg").read_text(), remote_route, Path(platforms[0])),
        manifest.get("timing_profile"))
    pins_by_path = {pin["path"]: pin["sha256"] for pin in manifest["pins"]}
    mandatory = [indexed[member]["source"] for member in (
        "capsule/capsule.json", "route/environment.json", "route/link.cfg")]
    mandatory += [{"path": str(remote_root / row["member"]), "sha256": row["sha256"]}
                  for row in packet["files"]]
    if manifest.get("command") != expected_command or execution["route"].get("command") != expected_command or \
            execution["route"].get("cwd") != str(remote_route) or config != expected_config or \
            platforms[0] not in pins_by_path or any(pins_by_path.get(pin["path"]) != pin["sha256"] for pin in mandatory) or \
            manifest.get("parent") != packet["parent"] or manifest.get("relocation") != execution["capsule"] or \
            execution.get("parent") != packet["parent"] or execution.get("host") != receipt["host"] or \
            manifest.get("clock_mhz") != 150 or \
            receipt.get("checked_remote_pin_count") != len(manifest["pins"]):
        raise ValueError("returned configuration or verified input coverage differs")
    pins = [identity(returned / "receipt.json"), identity(original), *parent["pins"], packet["parent"],
            *[identity(returned / row["member"]) for row in receipt["files"]],
            *[identity(path) for path in sorted(Path(__file__).parent.glob("*.py"))]]
    unchanged(pins)
    output.mkdir(parents=True, exist_ok=False)
    candidate = route / "candidate.hw.xclbin"
    old = bitstream.normalized_topology(bitstream._dump(original, output / "original"))
    new = bitstream.normalized_topology(bitstream._dump(candidate, output / "candidate"))
    expected_cus = {f"{name}:{name}_{index + 1}" for name, count in COUNTS.items() for index in range(count)}
    if old != new or ("DATA", "DATA_CLK", 150) not in new["clock"] or \
            {name for name, _ in new["kernels"]} != expected_cus:
        raise ValueError("returned clock, CU budget or connectivity differs")
    timing = bitstream.parse_routed_timing(route / "timing.rpt")
    unchanged(pins)
    result = {"status": "ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD", "original": identity(original),
              "candidate": identity(candidate), "clock_topology_connectivity_equal": True,
              "timing": timing, "timing_profile": manifest.get("timing_profile"),
              "topology": new, "pins": pins, "remote_receipt": identity(returned / "receipt.json"),
              "candidate_owner": parent["candidate_owner"], "link_status": delivery.PASS,
              "claim": "remote_link_provenance_and_local_strict_timing_not_board_performance"}
    atomic_write_json(output / "summary.json", result)
    return result
