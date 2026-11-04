"""Admit the sealed ResPR tail image without treating a link as board evidence."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import replacement_return
from spine_cycle_sim.experiments.sharded_k4_stages import bitstream
from .. import artifact
from .runtime import identity, save


STATUS = "RETURNED_RESPR_ROUTE_ADMITTED_NOT_BOARD_EVIDENCE"


def comparable_topology(topology):
    # XRT's integer field can truncate a nominal 150-MHz clock to 149.
    data = [row for row in topology["clock"] if row[:2] == ("DATA", "DATA_CLK")]
    if len(data) != 1 or data[0][2] not in (149, 150):
        raise ValueError("returned route requires a nominal 150-MHz DATA_CLK")
    return {**topology, "clock": [row for row in topology["clock"] if row != data[0]]}


def admit(route, returned, capsule, platform, predecessor, output):
    plan_path = route / "manifest.json"
    plan = artifact.identity(plan_path)
    local_capsule = json.loads((capsule / "capsule.json").read_text())
    transfer_path = returned.parent / "transfer.json"
    transfer_pin = identity(transfer_path)
    transfer = json.loads(transfer_path.read_text())
    candidate = returned / "route/candidate.hw.xclbin"
    image = artifact.identity(candidate)
    if (local_capsule["parent"] != plan
            or transfer["status"] != "REMOTE_REPLACEMENT_LINK_VERIFIED_NOT_BOARD_EVIDENCE"
            or transfer["candidate"] != image):
        raise ValueError("returned candidate does not match the local plan and completed collector")
    _, parent, pins = replacement_return.verify(returned, capsule, platform, transfer["receipt_sha256"])
    if (parent != json.loads(plan_path.read_text()) or "tail_hosts" not in parent
            or plan not in pins or Path(parent["production"]) != predecessor.parent):
        raise ValueError("exact ResPR tail plan and frozen predecessor required")
    original_pin = identity(predecessor)
    output.mkdir()
    old = bitstream.normalized_topology(bitstream._dump(predecessor, output / "predecessor"))
    new = bitstream.normalized_topology(bitstream._dump(candidate, output / "candidate"))
    if comparable_topology(old) != comparable_topology(new):
        raise ValueError("returned candidate changes the clock, CU budget or connectivity")
    timing = bitstream.parse_routed_timing(returned / "route/timing.rpt")
    evidence = {"status": STATUS, "plan": plan, "image": image, "transfer": transfer_pin,
                "remote_receipt": identity(returned / "receipt.json"), "predecessor": original_pin,
                "timing": timing, "topology": new, "predecessor_topology": old, "verified_source_pins": pins}
    proof = output / "summary.json"
    save(proof, evidence)
    return Path(image["path"]), image, identity(proof)


def replay(route, screen, proof):
    evidence = json.loads(Path(proof["path"]).read_text())
    image = evidence["image"]
    if (evidence["status"] != STATUS or evidence["plan"] != artifact.identity(route / "manifest.json")
            or image not in screen["pins"]):
        raise ValueError("R did not screen this exact returned route")
    pins = [proof, image, evidence["transfer"], evidence["remote_receipt"],
            evidence["predecessor"], evidence["timing"]["report"]]
    return Path(image["path"]), image, pins
