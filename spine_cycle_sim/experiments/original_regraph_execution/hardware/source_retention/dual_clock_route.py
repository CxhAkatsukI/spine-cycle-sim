"""Retain nominal failures and qualify a vendor-derated DATA/HBM screen."""

from decimal import Decimal
import json
import re

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import replacement_return
from spine_cycle_sim.experiments.sharded_k4_stages import bitstream
from .. import artifact
from . import clock_profile, returned_route
from .runtime import identity, save


def vendor_profile(topology, log, profile):
    profile = clock_profile.validate(profile)
    encoded = {(kind, name): mhz for kind, name, mhz in topology["clock"]}
    if len(topology["clock"]) != 3 or set(encoded) != set(clock_profile.NAMES):
        raise ValueError("three exact U55C clock names required")
    patterns = (
        r"\[AUTO-FREQ-SCALING-04\].*?kernel clock ulp_ucs/aclk_kernel_00",
        r"\[AUTO-FREQ-SCALING-07\].*?system clock hbm_aclk",
    )
    achievable = []
    for pattern, requested, target, key in zip(
            patterns, (150, 450), (profile[0], profile[2]), (clock_profile.NAMES[0], clock_profile.NAMES[2])):
        matches = re.findall(pattern + r" has an original frequency equal to ([\d.]+) MHz\. "
                             r"The frequency has been automatically changed to ([\d.]+) MHz", log)
        if len(matches) != 1:
            raise ValueError("one vendor derating notice per DATA and HBM clock required")
        old, new = map(Decimal, matches[0])
        if old != requested or not target <= new < requested or encoded[key] != int(new):
            raise ValueError("requested downclock exceeds vendor limit or packaged clock disagrees")
        achievable.append(str(new))
    if encoded[clock_profile.NAMES[1]] != 500:
        raise ValueError("the unused KERNEL clock must remain unchanged")
    return dict(zip(("data_mhz", "hbm_mhz"), achievable))


def timing_failure(text, profile):
    clock_profile.validate(profile)
    lines = text.splitlines()
    summary = [i for i, line in enumerate(lines) if line.strip().startswith("WNS(ns)")]
    intra = [i for i, line in enumerate(lines) if line.strip() == "| Intra Clock Table"]
    inter = [i for i, line in enumerate(lines) if line.strip() == "| Inter Clock Table"]
    if len(summary) != 1 or len(intra) != 1 or len(inter) != 1 or intra[0] >= inter[0]:
        raise ValueError("one design summary and ordered clock tables required")
    total = lines[summary[0] + 2].split()
    if (len(total) != 12 or int(total[2]) <= 0
            or any(float(total[i]) < 0 or float(total[i + 1]) != 0 or int(total[i + 2]) != 0
                   for i in (4, 8))):
        raise ValueError("nominal failure must be setup-only, not hold or pulse width")
    targets = {"clk_kernel_00_unbuffered_net": (150, profile[0]), "hbm_aclk": (450, profile[2])}
    failures = {}
    for line in lines[intra[0]:inter[0]]:
        row = line.split()
        if len(row) != 13:
            continue
        try:
            wns, count = float(row[1]), int(row[3])
        except ValueError:
            continue
        if count or wns < 0:
            if row[0] not in targets:
                raise ValueError("setup failures outside the two vendor-derated clock domains")
            nominal, target = targets[row[0]]
            margin = wns + 1000 / target - 1000 / nominal
            if margin < 0 or row[0] in failures:
                raise ValueError("clock reduction does not cover the reported intra-clock setup failure")
            failures[row[0]] = {"nominal_wns_ns": wns, "failing_endpoints": count,
                                "period_extension_margin_ns": margin}
    if set(failures) != set(targets) or sum(r["failing_endpoints"] for r in failures.values()) != int(total[2]):
        raise ValueError("not all reported setup failures belong to the two derated intra-clock domains")
    return {"nominal_timing_pass": False, "nominal_wns_ns": float(total[0]),
            "domains": failures,
            "qualification": "vendor derating plus conservative period-extension check; not a new STA run"}


def admit(args, output):
    output.mkdir(exist_ok=False)
    transfer = json.loads((args.returned.parent / "transfer.json").read_text())
    image = args.returned / "route/candidate.hw.xclbin"
    if (transfer["status"] != "REMOTE_REPLACEMENT_LINK_VERIFIED_NOT_BOARD_EVIDENCE"
            or transfer["candidate"] != artifact.identity(image)):
        raise ValueError("verified collector and exact routed image required")
    _, parent, pins = replacement_return.verify(args.returned, args.capsule, args.platform,
                                                transfer["receipt_sha256"])
    if (parent != json.loads((args.route / "manifest.json").read_text()) or "tail_hosts" not in parent
            or parent["production"] != str(args.predecessor.parent)):
        raise ValueError("exact tail plan and production predecessor required")
    old = returned_route.tail_predecessor(bitstream.normalized_topology(
        bitstream._dump(args.predecessor, output / "predecessor")))
    new = bitstream.normalized_topology(bitstream._dump(image, output / "candidate"))
    if {**old, "clock": []} != {**new, "clock": []}:
        raise ValueError("CU budget or physical connectivity changed")
    log, timing = [args.returned / "route" / name for name in ("route.stdout.txt", "timing.rpt")]
    evidence = {"status": "DUAL_CLOCK_SCREEN_ADMITTED_NOT_NOMINAL_OR_BOARD_EVIDENCE",
                "image": identity(image), "plan": identity(args.route / "manifest.json"),
                "source_pins": pins, "transfer": identity(args.returned.parent / "transfer.json"),
                "predecessor": identity(args.predecessor), "topology": new,
                "vendor_limits": vendor_profile(new, log.read_text(), args.profile),
                "nominal_failure": timing_failure(timing.read_text(), args.profile),
                "log": identity(log), "timing": identity(timing), "profile_mhz": args.profile}
    save(output / "summary.json", evidence)
    return parent, evidence
