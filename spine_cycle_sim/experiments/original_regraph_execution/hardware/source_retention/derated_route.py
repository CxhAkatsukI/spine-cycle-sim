"""Admit only vendor HBM derating; keep nominal timing admission separate."""

from decimal import Decimal
import json
import re

from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import replacement_return
from spine_cycle_sim.experiments.sharded_k4_stages import bitstream
from .. import artifact
from . import matched_hbm, returned_route, runtime


HBM = ("SYSTEM", "hbm_aclk")
DATA = ("DATA", "DATA_CLK")
NOMINAL = {HBM: 450, DATA: 150, ("KERNEL", "KERNEL_CLK"): 500}


def compatible_profile(original, candidate, log, target):
    matched_hbm.validate_profile([150, 500, target, 0], target)
    old = {(kind, name): mhz for kind, name, mhz in original["clock"]}
    new = {(kind, name): mhz for kind, name, mhz in candidate["clock"]}
    if (len(original["clock"]) != 3 or set(old) != set(NOMINAL)
            or old[DATA] not in (149, 150) or not 0 < old[HBM] <= 450
            or {**old, HBM: 450, DATA: 150} != NOMINAL or len(candidate["clock"]) != 3
            or set(new) != set(NOMINAL)
            or {**new, HBM: 450} != NOMINAL
            or {**original, "clock": []} != {**candidate, "clock": []}):
        raise ValueError("returned route changed non-HBM clocks, CU budget or connectivity")
    adjustments = re.findall(
        r"^.*\[AUTO-FREQ-SCALING-07\].*?\bclock (\w+) has an original frequency equal to "
        r"([\d.]+) MHz\. The frequency has been automatically changed to ([\d.]+) MHz", log, re.M)
    if len(adjustments) != 1 or adjustments[0][0] != HBM[1]:
        if not adjustments and new.get(HBM) == 450:
            return None
        raise ValueError("one vendor HBM-only derating notice required")
    _, requested, achievable = adjustments[0]
    requested, achievable = Decimal(requested), Decimal(achievable)
    if requested != 450 or int(achievable) != new.get(HBM) or not 0 < achievable < 450:
        raise ValueError("Vitis derating notice disagrees with packaged HBM clock")
    return str(achievable) if target <= achievable < target + 5 else None


def check_timing(text, target):
    lines = text.splitlines()
    headings = [i for i, line in enumerate(lines) if line.strip().startswith("WNS(ns)")]
    intra = [i for i, line in enumerate(lines) if line.strip() == "| Intra Clock Table"]
    inter = [i for i, line in enumerate(lines) if line.strip() == "| Inter Clock Table"]
    if len(headings) != 1 or len(intra) != 1 or len(inter) != 1 or intra[0] >= inter[0]:
        raise ValueError("expected one Vivado design summary and intra-clock table")
    total = lines[headings[0] + 2].split()
    hbm = [line.split()[1:] for line in lines[intra[0]:inter[0]] if line.split()[:1] == [HBM[1]]]
    if len(total) != 12 or len(hbm) != 1 or len(hbm[0]) != 12:
        raise ValueError("expected twelve timing columns and one HBM timing row")
    if (total[:3] != hbm[0][:3] or int(total[2]) <= 0
            or any(float(total[i]) < 0 or float(total[i + 1]) != 0 or int(total[i + 2]) != 0
                   for i in (4, 8))
            or float(total[0]) + (1000 / target - 1000 / 450) < 0):
        raise ValueError("nominal failure is not covered by the HBM-only clock reduction")
    return dict(nominal_wns_ns=float(total[0]), nominal_failing_setup_endpoints=int(total[2]),
                nominal_whs_ns=float(total[4]), nominal_wpws_ns=float(total[8]))


def admit(args, output, transfer):
    receipt = json.loads((args.returned.parent / "transfer.json").read_text())
    image = args.returned / "route/candidate.hw.xclbin"
    if (receipt["status"] != "REMOTE_REPLACEMENT_LINK_VERIFIED_NOT_BOARD_EVIDENCE"
            or receipt["candidate"] != artifact.identity(image)):
        raise ValueError("completed collector and exact routed image required")
    _, parent, pins = replacement_return.verify(args.returned, args.capsule, args.platform,
                                                receipt["receipt_sha256"])
    modes = {"cc": "destination", "weighted_sssp": "weighted"}
    matches = ("tail_hosts" in parent if args.algorithm == "respr"
               else args.algorithm in modes and parent.get("mode") == modes[args.algorithm])
    if parent["production"] != str(args.predecessor.parent) or not matches:
        raise ValueError("candidate did not replace the expected production image and algorithm")
    log = args.returned / "route/route.stdout.txt"
    old = bitstream.normalized_topology(bitstream._dump(args.predecessor, output / "predecessor"))
    new = bitstream.normalized_topology(bitstream._dump(image, output / "candidate_topology"))
    if args.algorithm == "respr":
        old = returned_route.tail_predecessor(old)
    achievable = compatible_profile(old, new, log.read_text(), args.hbm_mhz)
    timing = args.returned / "route/timing.rpt"
    evidence = dict(image=runtime.identity(image), source_pins=pins, collector=transfer,
                    predecessor=runtime.identity(args.predecessor), topology=new,
                    link_log=runtime.identity(log), vendor_hbm_mhz=achievable,
                    nominal_timing_report=runtime.identity(timing))
    if achievable:
        evidence["nominal_failure"] = check_timing(timing.read_text(), args.hbm_mhz)
    return parent, evidence
