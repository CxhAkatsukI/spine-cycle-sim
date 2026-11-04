"""Seal and return the remote public A4 CC build for independent local replay."""

import argparse
import json
from pathlib import Path
import shutil
import socket
import subprocess
import time

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import (
    capsule, delivery, terminal_link,
)
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote.replacement_capsule import inventory
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote.transport import Remote
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import route_finished
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware import memory_profiles
from .. import artifact
from . import configuration, portable_execution, portable_inputs, snapshot

SCHEMA = "remote-public-a4-cc-return-v1"
MODULE = "spine_cycle_sim.experiments.original_regraph_execution.hardware.source_build.portable_return"
BINARY = configuration.binary_name("a4", algorithm="cc")
NAMES = tuple(configuration.kernels("a4"))
STATUS = "REMOTE_A4_CC_RETURN_VERIFIED_NOT_BOARD_EVIDENCE"


def record(directory, name):
    return json.loads((directory / name).read_text())


def members(result, remote_attempt):
    expected = {"results.json", "manifest.json", "environment.json", "preflight/results.json", BINARY}
    expected.update(f"preflight/{label}.{suffix}" for label in delivery.LABELS
                    for suffix in ("stdout.txt", "stderr.txt", "resources.json"))
    for name in (*("compile_" + name for name in NAMES), "route"):
        expected.update(f"{name}.{suffix}" for suffix in ("stdout.txt", "stderr.txt", "resources.json"))
    if [row["abi"]["kernel"] for row in result["xos"]] != list(NAMES):
        raise ValueError("incomplete public A4 CC XO records")
    for name, row in zip(NAMES, result["xos"]):
        xo = Path(row["abi"]["xo"]["path"]).relative_to(remote_attempt)
        hls = Path(row["hls"]["report"]["path"]).relative_to(remote_attempt)
        if (xo != Path(f"xo/{name}.hw.xo") or ".." in hls.parts
                or not hls.is_relative_to(Path("compile") / name) or hls.name != f"{name}_csynth.xml"):
            raise ValueError("unexpected public A4 CC XO or HLS report location")
        expected.update((str(xo), str(hls)))
    return expected


def completed(result, manifest, preflight):
    policy = memory_profiles.select(capsule.POLICY, memory_profiles.SEELE)
    if (result["status"] != portable_execution.STATUS or result["errors"] or result["host"] != "seele"
            or result["board_programmed"] is not False or manifest["clock_mhz"] != 150
            or (manifest["configuration"], manifest["algorithm"]) != ("a4", "cc")
            or [row["id"] for row in result["steps"]] != ["compile_" + name for name in NAMES] + ["route"]):
        raise ValueError("complete remote public A4 CC source build required")
    route = result["steps"][-1]
    delivery.completed({**result, "status": delivery.PASS, "route": route, **dict.fromkeys(capsule.FLAGS, False)},
                       {**manifest, "policy": policy, "memory_profile": memory_profiles.SEELE,
                        **dict.fromkeys(capsule.FLAGS, False)}, preflight)
    for step in result["steps"]:
        memory_profiles.route_evidence(result, policy, step)
        if step["exit_code"] != 0 or step["stop_reason"] != "process_exit" or step["cleanup_snapshot_error"]:
            raise ValueError("public A4 CC build step did not finish cleanly")


def seal(remote_capsule, attempt, output, unit, invocation, digest):
    if socket.gethostname() != "seele":
        raise ValueError("terminal seele invocation required")
    state = terminal_link.capture(unit, invocation, attempt)
    result, manifest, preflight = [record(attempt, name) for name in (
        "results.json", "manifest.json", "preflight/results.json")]
    completed(result, manifest, preflight)
    capsule_pin = artifact.identity(remote_capsule / "capsule.json")
    if (result["capsule"] != capsule_pin or capsule_pin["sha256"] != digest
            or result["manifest"] != artifact.identity(attempt / "manifest.json")
            or result["xclbin"] != artifact.identity(attempt / BINARY)):
        raise ValueError("terminal build pins differ from requested source or output")
    snapshot.unchanged(result["pins"])
    reports = list((attempt / "link/reports").glob("**/impl_1_hw_bb_locked_timing_summary_routed.rpt"))
    if len(reports) != 1:
        raise ValueError("one routed timing report required")
    files = {name: attempt / name for name in members(result, attempt)}
    files["timing/impl_1_hw_bb_locked_timing_summary_routed.rpt"] = reports[0]
    output.mkdir(parents=True, exist_ok=False)
    pins = {name: artifact.identity(source) for name, source in files.items()}
    for name, source in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    if (inventory(output) != {name: pin["sha256"] for name, pin in pins.items()}
            or terminal_link.capture(unit, invocation, attempt) != state):
        raise ValueError("remote service or output changed during seal")
    snapshot.unchanged([*pins.values(), *result["pins"]])
    atomic_write_json(output / "receipt.json", {"schema": SCHEMA, "files": pins, "capsule": capsule_pin,
                      "unit": unit, "invocation": invocation, "service": state, "remote_attempt": str(attempt)})
    return artifact.identity(output / "receipt.json")["sha256"]


def verify(root, digest, local_capsule):
    pin = artifact.identity(root / "receipt.json")
    receipt = record(root, "receipt.json")
    result = record(root, "results.json")
    attempt = Path(receipt["remote_attempt"])
    observed = inventory(root)
    del observed["receipt.json"]
    files = receipt["files"]
    if (pin["sha256"] != digest or receipt["schema"] != SCHEMA
            or not terminal_link.terminal(receipt["service"], receipt["unit"], receipt["invocation"], attempt)
            or set(files) != members(result, attempt) | {"timing/impl_1_hw_bb_locked_timing_summary_routed.rpt"}
            or observed != {name: file["sha256"] for name, file in files.items()}
            or any(path.is_symlink() for path in root.rglob("*"))):
        raise ValueError("returned public A4 CC receipt or payload differs")
    local = artifact.identity(local_capsule / "capsule.json")
    portable_inputs.verify(local_capsule, configuration.PLATFORM, configuration.COMPILER.parents[3], local["sha256"])
    manifest = record(root, "manifest.json")
    preflight = record(root, "preflight/results.json")
    completed(result, manifest, preflight)
    if (local["sha256"] != receipt["capsule"]["sha256"] or result["capsule"] != receipt["capsule"]
            or result["manifest"] != files["manifest.json"] or result["xclbin"] != files[BINARY]):
        raise ValueError("public A4 CC link differs from the locally submitted source")
    source = Path(receipt["capsule"]["path"]).parent / "source"
    environment = record(root, "environment.json")
    compiler = Path(environment["tools"]["v++"]["invocation"])
    platform = Path(manifest["commands"]["link"][manifest["commands"]["link"].index("--platform") + 1])
    if manifest["commands"] != portable_inputs.commands(
            source, attempt, compiler, platform, timing_profile=manifest.get("timing_profile")):
        raise ValueError("remote public A4 CC command changed")
    for row in result["xos"]:
        for evidence in (row["abi"]["xo"], row["hls"]["report"]):
            if files[str(Path(evidence["path"]).relative_to(attempt))] != evidence:
                raise ValueError("public A4 CC compilation output differs")
    return receipt, result, [pin, local, *[artifact.identity(root / name) for name in files]]


def collect(remote, local_capsule, output, wait_seconds):
    if not 1 <= wait_seconds <= 48 * 3600:
        raise ValueError("positive return wait bounded to 48 hours required")
    output.mkdir(parents=True, exist_ok=False)
    path = output / "transfer.json"
    report = {"status": "WAITING_FOR_PINNED_REMOTE_LINK"}
    atomic_write_json(path, report)
    try:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                report["service"] = remote.state()
            except (ConnectionError, subprocess.TimeoutExpired) as error:
                report["transport_error"] = repr(error)
            else:
                report.pop("transport_error", None)
                if terminal_link.unloaded(report["service"]) or route_finished(report["service"], remote.invocation):
                    break
            atomic_write_json(path, report)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("public A4 CC link did not finish in its return window")
            time.sleep(min(60, remaining))
        digest = artifact.identity(local_capsule / "capsule.json")["sha256"]
        receipt_digest = remote.command(["systemd-run", "--user", "--wait", "--pipe", "--quiet", "--collect",
            "--property=MemoryMax=4G", "--property=MemoryHigh=3G", "--property=MemorySwapMax=0",
            "--property=OOMPolicy=kill", "--property=RuntimeMaxSec=1800", "env", f"PYTHONPATH={remote.runner}",
            "python3", "-m", MODULE, "seal", "--capsule", remote.capsule, "--attempt", remote.attempt,
            "--output", remote.returned, "--unit", remote.unit, "--invocation", remote.invocation,
            "--digest", digest], timeout=1860).strip()
        returned = output / "returned"
        remote.transfer(returned)
        receipt, _, pins = verify(returned, receipt_digest, local_capsule)
        if (receipt["unit"], receipt["invocation"], receipt["remote_attempt"], receipt["capsule"]["path"]) != (
                remote.unit, remote.invocation, str(remote.attempt), str(remote.capsule / "capsule.json")):
            raise ValueError("remote public control receipt belongs to another invocation")
        report.update(status=STATUS, receipt_sha256=receipt_digest, pins=pins)
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        atomic_write_json(path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("seal", "collect"):
        child = commands.add_parser(name)
        for field in ("unit", "invocation"):
            child.add_argument("--" + field, required=True)
        for field in ("capsule", "attempt", "output"):
            child.add_argument("--" + field, type=Path, required=True)
        if name == "seal":
            child.add_argument("--digest", required=True)
        else:
            for field in ("runner", "returned", "local-capsule"):
                child.add_argument("--" + field, type=Path, required=True)
            child.add_argument("--target", required=True)
            child.add_argument("--port", type=int, required=True)
            child.add_argument("--wait-seconds", type=int, default=48 * 3600)
    args = parser.parse_args()
    if args.command == "seal":
        print(seal(args.capsule, args.attempt, args.output, args.unit, args.invocation, args.digest))
    else:
        remote = Remote(args.target, args.port, args.runner, args.capsule, args.attempt, args.returned,
                        args.unit, args.invocation)
        print(collect(remote, args.local_capsule, args.output, args.wait_seconds)["status"])


if __name__ == "__main__":
    main()
