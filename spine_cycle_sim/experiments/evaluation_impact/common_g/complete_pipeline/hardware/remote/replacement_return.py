"""Retrieve a frozen replacement link without asserting board correctness or retention."""

import argparse
from pathlib import Path
import subprocess
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.sharded_k4_stages import bitstream
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from ....continuous_board.execution.supervisor import route_finished
from ....search_pipeline.synthesis import unchanged
from . import admission, delivery, tail_topology, terminal_link
from .transport import Remote


def verify(returned, local_capsule, platform, receipt_sha256):
    receipt, packet, parent = delivery.verify(returned, receipt_sha256, replacement_platform=platform)
    if sha256_file(returned / "capsule/capsule.json") != sha256_file(local_capsule / "capsule.json"):
        raise ValueError("returned relocation differs from the locally exported capsule")
    manifest, pins = admission.verify_link(returned, receipt, packet, parent)
    if manifest.get("timing_profile") != packet.get("timing_profile"):
        raise ValueError("returned timing strategy differs from the pinned replacement capsule")
    pins.append(identity(local_capsule / "capsule.json"))
    unchanged(pins)
    return receipt, parent, pins


def collect(remote, remote_platform, local_capsule, local_platform, output, *, wait_seconds=0):
    if type(wait_seconds) is not int or not 0 <= wait_seconds <= 36 * 3600:
        raise ValueError("replacement link wait must be bounded to 36 hours")
    output.mkdir(parents=True, exist_ok=False)
    summary = output / "transfer.json"
    report = {"status": "COLLECTING_NOT_BOARD_EVIDENCE"}
    atomic_write_json(summary, report)
    try:
        if wait_seconds:
            deadline = time.monotonic() + wait_seconds
            while True:
                report["status"] = "WAITING_FOR_PINNED_REMOTE_LINK"
                try:
                    report["service"] = remote.state()
                except (ConnectionError, subprocess.TimeoutExpired) as error:
                    report["transport_error"] = repr(error)
                else:
                    report.pop("transport_error", None)
                    if terminal_link.unloaded(report["service"]) or route_finished(report["service"], remote.invocation):
                        break
                atomic_write_json(summary, report)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("replacement link did not finish within the return window")
                time.sleep(min(60, remaining))
        report["status"] = "COLLECTING_NOT_BOARD_EVIDENCE"
        digest = remote.seal(replacement_platform=remote_platform)
        report["receipt_sha256"] = digest
        atomic_write_json(summary, report)
        returned = output / "returned"
        remote.transfer(returned)
        receipt, parent, _ = verify(returned, local_capsule, local_platform, digest)
        if (receipt["unit"], receipt["invocation"], receipt["remote_attempt"], receipt["remote_capsule"]) != (
                remote.unit, remote.invocation, str(remote.attempt), str(remote.capsule)):
            raise ValueError("returned service or route identity differs from the requested run")
        report.update(status="REMOTE_REPLACEMENT_LINK_VERIFIED_NOT_BOARD_EVIDENCE", mode=parent.get("mode"),
                      candidate=identity(returned / "route/candidate.hw.xclbin"))
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        atomic_write_json(summary, report)
    return report


def active_min(returned, local_capsule, platform, receipt_sha256, predecessor, output, *, mode):
    _, parent, pins = verify(returned, local_capsule, platform, receipt_sha256)
    if parent.get("mode") != mode or mode not in ("destination", "weighted"):
        raise ValueError("returned replacement has a different active-min ABI")
    candidate = returned / "route/candidate.hw.xclbin"
    pins.append(identity(predecessor))
    output.mkdir(parents=True, exist_ok=False)
    original = bitstream.normalized_topology(bitstream._dump(predecessor, output / "predecessor"))
    topology = bitstream.normalized_topology(bitstream._dump(candidate, output / "candidate"))
    profile = None
    if "weighted_tail" in parent:
        if mode != "weighted":
            raise ValueError("tail publication is supported only for the weighted link")
        tail_topology.verify(original, topology)
        profile = tail_topology.PROFILE
    elif original != topology:
        raise ValueError("replacement changes the loaded clock, CU budget or connectivity")
    if ("DATA", "DATA_CLK", 150) not in topology["clock"]:
        raise ValueError("replacement lacks the nominal 150 MHz data clock")
    timing = bitstream.parse_routed_timing(returned / "route/timing.rpt")
    unchanged(pins)
    image = identity(candidate)
    report = {"status": "ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD",
              "timing": timing, "candidate": image, "pins": pins}
    if profile:
        report["topology_profile"] = profile
    atomic_write_json(output / "summary.json", report)
    return image, pins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("target", "unit", "invocation"):
        parser.add_argument("--" + name, required=True)
    for name in ("remote-runner", "remote-capsule", "remote-attempt", "remote-returned", "remote-platform",
                 "local-capsule", "local-platform", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--wait-seconds", type=int, default=0)
    args = parser.parse_args()
    remote = Remote(args.target, args.port, args.remote_runner, args.remote_capsule, args.remote_attempt,
                    args.remote_returned, args.unit, args.invocation)
    print(collect(remote, args.remote_platform, args.local_capsule.resolve(), args.local_platform.resolve(),
                  args.output.resolve(), wait_seconds=args.wait_seconds)["status"], flush=True)


if __name__ == "__main__":
    main()
