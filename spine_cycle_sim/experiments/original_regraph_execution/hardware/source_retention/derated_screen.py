"""Replay one same-clock public A4 observation and run only the changed candidate."""

import argparse
import json
from pathlib import Path
import time

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import service_state
from spine_cycle_sim.experiments.sharded_k4_stages.row_line.directory_tile.hardware.tail_publication import host_pair
from ..board_execution import active_min, active_min_candidate, active_min_follow, active_min_pair, pair_resources
from . import analysis, clocks, derated_route, matched_hbm, runtime
from .follow import unchanged


PROFILES = {"cc": ("au903k", 430), "respr": ("skewed_sources", 445), "weighted_sssp": ("au903k", 445)}


def read_pin(pin):
    unchanged([pin])
    return json.loads(Path(pin["path"]).read_text())


def fixture_directory(pins, names):
    unchanged(pins)
    paths = [Path(pin["path"]) for pin in pins]
    if len({path.parent for path in paths}) != 1 or len(set(paths)) != len(paths):
        raise ValueError("one frozen fixture directory and unique input files required")
    if not {f"{name}.u32le" for name in names} <= {path.name for path in paths}:
        raise ValueError("fixture inputs missing")
    return paths[0].parent


def reference_observation(args, reference, report, parent):
    if (reference["case"], reference["bdf"], reference["device"], reference["repetitions"]) != (
            report["case"], args.bdf, args.device, 1):
        raise ValueError("reference used a different fixture, board, or repeat count")
    if args.algorithm == "cc":
        if (reference["status"] not in ("PAIRED_LOWER_CLOCK_ROW_PASS", "PAIRED_LOWER_CLOCK_ROW_GATE_FAILED")
                or reference["algorithm"] != "cc" or reference["boundary"] != active_min.BOUNDARY
                or reference["target"] != args.hbm_mhz or reference["attempts"] != ["reference", "candidate"]):
            raise ValueError("one complete equal-clock CC pair required")
        row, package = reference["arms"]["reference"], reference["reference_package"]
        fixture_pin = reference["fixture"]
        pins = reference["inputs"]
        if read_pin(fixture_pin)["input_pins"] != pins:
            raise ValueError("CC fixture differs from the pinned input manifest")
        fixture = fixture_directory(pins, active_min.INPUTS + active_min.STATE["cc"])
        control, candidate = reference["reference_host"], reference["candidate_host"]
        unchanged([control, candidate])
        if active_min_pair.paired_loader(control["path"], candidate["path"]) != reference["preflight_xrt_libraries"]:
            raise ValueError("XRT library resolution changed")
        report["candidate_host"] = candidate
        offline, expected, _ = active_min.read_offline(control["path"], "cc", fixture, args.output)
        measured = active_min.inspect(args.reference.parent / "reference", offline, expected, fixture, args.bdf)
        if measured != row["analysis"]:
            raise ValueError("CC public output replay differs")
        context = (offline, expected)
    else:
        if (reference["status"] != "ONE_REFERENCE_ARM_RETAINED_NOT_PAIRED"
                or (reference["stage"], reference["arm"]) != ("R", "reference")):
            raise ValueError("one public ResPR reference run required")
        row, package = reference, reference["package"]
        pins = reference["input_pins"]
        fixture = fixture_directory(pins, active_min.INPUTS)
        if fixture.name != report["case"] or len(pins) != len(active_min.INPUTS):
            raise ValueError("ResPR fixture differs from the public control")
        host_manifest = parent["tail_hosts"]
        unchanged([host_manifest, reference["host"]])
        hosts = host_pair(Path(host_manifest["path"]))
        if hosts["reference"]["sha256"] != reference["host"]["sha256"]:
            raise ValueError("tail-publication host build differs from the original control")
        report["candidate_host"] = hosts["candidate"]
        measured = analysis.profiled_runs(dict(stage="R", arm="reference", repetitions=1,
                                               result_json=reference["result"],
                                               result_directory=str(Path(reference["result"]["path"]).parent),
                                               clock_evidence=row["clock_after"], **row["run"]))
        context = None
    matched_hbm.validate_after(row["prepared"], row["clock_after"], args.hbm_mhz)
    observed = clocks.replay(row["clock_after"])
    packed = read_pin(package)
    if (observed["bdf"] != args.bdf or observed["binary"] != packed["derived"]["binary"]
            or packed["status"] != "OFFLINE_VERIFIED_NOT_BOARD_QUALIFIED"
            or packed["requested_hbm_mhz"] != args.hbm_mhz):
        raise ValueError("reference was not measured on the pinned public same-clock image")
    report.update(input_pins=pins, reference_clock=row["clock_after"], reference_observation=measured)
    return fixture, measured, observed, context


def recover_sssp_reference(args, reference, report, route):
    """Recover an already measured control only after the known pre-kernel path collision."""
    root = args.reference.parent
    stdout, stderr = root / "candidate.stdout.txt", root / "candidate.stderr.txt"
    if (reference["status"] != "FAILED_RETAINED" or reference["requested_runs_per_arm"] != 1
            or (reference["algorithm"], reference["bdf"], reference["target"], reference["boundary"])
            != (args.algorithm, args.bdf, args.hbm_mhz, active_min.BOUNDARY)
            or reference["attempts"] != ["reference", "candidate"]
            or not same_return(reference["derated_route"], route)
            or reference["error"] != f"RuntimeError('candidate failed (1): {stderr}')"
            or stdout.read_bytes()
            or stderr.read_text().strip() != "ERROR: fresh active-min output directory required"
            or "execution" in reference["arms"]["candidate"] or "analysis" in reference["arms"]["candidate"]):
        raise ValueError("expected the exact unmeasured SSSP candidate directory collision")
    pins = reference["pins"]
    unchanged(pins)
    if not args.sssp_hosts:
        raise ValueError("exact public and integrated SSSP hosts required")
    reference_host, candidate_host = [runtime.identity(host) for host in args.sssp_hosts]
    if any({key: pin[key] for key in ("path", "sha256")} not in pins for pin in (reference_host, candidate_host)):
        raise ValueError("SSSP recovery hosts differ from the initial attempt")
    input_pins = [pin for pin in pins if Path(pin["path"]).name in
                  {f"{name}.u32le" for name in active_min.INPUTS + active_min.STATE[args.algorithm]}
                  and Path(pin["path"]).parent.name == "inputs"]
    fixture = fixture_directory(input_pins, active_min.INPUTS + active_min.STATE[args.algorithm])
    loaders = active_min_pair.paired_loader(reference_host["path"], candidate_host["path"])
    if loaders != reference["preflight_xrt_libraries"]:
        raise ValueError("SSSP XRT loader differs from the measured reference")
    if args.replacement_sssp_host:
        path, digest = args.replacement_sssp_host
        replacement = runtime.identity(Path(path))
        if replacement["sha256"] != digest or digest == candidate_host["sha256"]:
            raise ValueError("replacement requires a pinned, distinct host build")
        if active_min_pair.paired_loader(reference_host["path"], replacement["path"]) != loaders:
            raise ValueError("replacement host must use the same XRT loader")
        report["superseded_candidate_host"] = candidate_host
        candidate_host = replacement
    offline, oracle, _ = active_min.read_offline(reference_host["path"], args.algorithm, fixture, args.output)
    row = reference["arms"]["reference"]
    if row["execution"]["command"][-7:] != [reference_host["path"], "board", args.algorithm, str(fixture),
                                             str(root / "reference"),
                                             row["clock_evidence"]["expected"]["binary"]["path"], str(args.device)]:
        raise ValueError("public SSSP control command differs")
    measured = active_min.inspect(root / "reference", offline, oracle, fixture, args.bdf)
    if measured != row["analysis"]:
        raise ValueError("SSSP public output replay differs")
    observed = clocks.replay(row["clock_evidence"])
    matched_hbm.validate_after(row["prepared"], row["clock_evidence"], args.hbm_mhz)
    package = reference["reference_package"]
    packed = read_pin(package)
    if (package not in pins or observed["binary"] != packed["derived"]["binary"]
            or observed["bdf"] != args.bdf or packed["status"] != "OFFLINE_VERIFIED_NOT_BOARD_QUALIFIED"
            or packed["requested_hbm_mhz"] != args.hbm_mhz):
        raise ValueError("SSSP public same-clock image differs")
    report.update(input_pins=input_pins, reference_clock=row["clock_evidence"],
                  reference_observation=measured, candidate_host=candidate_host,
                  recovery_pins=[*pins, *measured["output_pins"], runtime.identity(stdout), runtime.identity(stderr)])
    return fixture, measured, observed, (offline, oracle)


def same_return(previous, current):
    def portable_route(route):
        sources = []
        prefix = "/spine_cycle_sim/experiments/evaluation_impact/common_g/complete_pipeline/hardware/remote/"
        for pin in route["source_pins"]:
            path = pin["path"]
            if prefix in path:
                path = prefix + path.rsplit(prefix, 1)[1]
            sources.append({**pin, "path": path})
        return json.loads(json.dumps({**route, "source_pins": sources}))

    unchanged(previous["source_pins"])
    return portable_route(previous) == portable_route(current)


def wait_for_return(args, report, save):
    active_min_follow.exact_service(args.unit, args.invocation)
    observed = False
    deadline = time.monotonic() + args.wait_seconds
    while True:
        state = service_state(args.unit)
        observed |= state["LoadState"] == "loaded" and state["InvocationID"] == args.invocation
        report.update(status="WAITING_FOR_EXACT_RETURN", service_state=state)
        save()
        pin = active_min_follow.returned_ready("candidate", args.returned, None, state, args.invocation, observed)
        if pin:
            return pin
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("candidate return did not finish in time")
        time.sleep(min(30, remaining))


def run(args):
    if (args.algorithm not in PROFILES or (args.device, args.bdf) != (0, "0000:82:00.1")
            or not 1 <= args.wait_seconds <= 111600 or not 1 <= args.board_wait_seconds <= 21600):
        raise ValueError("expected a declared fixture, leased device and bounded wait")
    if args.replacement_sssp_host and args.algorithm != "weighted_sssp":
        raise ValueError("replacement host is only supported for the pinned SSSP fixture")
    args.output.mkdir(parents=True, exist_ok=False)
    case, args.hbm_mhz = PROFILES[args.algorithm]
    report = dict(status="PREPARING", stage="R", algorithm=args.algorithm, case=case,
                  device=args.device, bdf=args.bdf, hbm_mhz=args.hbm_mhz, repetitions=1,
                  candidate_launch_attempted=False, reference_replayed=True,
                  convergence_measured=False, matrix_admitted=False)

    def save():
        runtime.save(args.output / "results.json", report)

    try:
        group = runtime.check_memory(require_live_reserve=False)
        if int((group / "memory.high").read_text()) > 7 * 2**30:
            raise MemoryError("board run requires memory.high at most 7 GiB")
        reference = runtime.identity(args.reference)
        if reference["sha256"] != args.reference_sha:
            raise ValueError("frozen same-clock reference digest changed")
        report["reference_receipt"] = reference
        pins = [reference, runtime.identity(args.capsule / "capsule.json"), runtime.identity(args.predecessor)]
        transfer = wait_for_return(args, report, save)
        unchanged([*pins, transfer])
        parent, route = derated_route.admit(args, args.output, transfer)
        report["route"] = route
        if not route["vendor_hbm_mhz"]:
            report["status"] = "NO_COMPATIBLE_DERATING_NO_BOARD_RUN"
            return report
        recorded = read_pin(reference)
        if args.algorithm == "weighted_sssp":
            fixture, control, control_clock, context = recover_sssp_reference(args, recorded, report, route)
            pins += report["recovery_pins"]
        else:
            fixture, control, control_clock, context = reference_observation(args, recorded, report, parent)
        binary = Path(route["image"]["path"])
        host = report["candidate_host"]["path"]
        expected = clocks.image(binary, args.output, "candidate")
        if args.algorithm != "respr":
            offline, oracle = context
            command = ["/usr/bin/env", "XCL_DEVICE_INDEX=0", f"GRASU_REGRAPH_EXPECT_BDF={args.bdf}",
                       host, "--active-min-once", binary, fixture, oracle["path"], args.output / "result"]
        else:
            command = [host, binary, fixture, args.device, 1]

        def record(phase, state):
            report.update(status=phase, memory_admission=state)
            save()

        with pair_resources.admit(args.device, args.bdf, group, args.board_wait_seconds, record) as (node, fd):
            unchanged([*pins, transfer, *report["input_pins"], route["image"], report["candidate_host"]])
            report["prepared"] = matched_hbm.prepare(binary, expected, args.hbm_mhz, args.output,
                                                      "candidate", fd, node, args.bdf)
            report.update(status="MEASURING_CANDIDATE_ONCE", candidate_launch_attempted=True)
            save()
            report["run"] = runtime.execute(command, args.output, "candidate", fd, node, args.bdf)
            after = report["clock_after"] = clocks.capture(args.bdf, expected, args.output, "candidate.after")
            matched_hbm.validate_after(report["prepared"], after, args.hbm_mhz)
        if args.algorithm != "respr":
            measured = active_min_candidate.inspect(args.output / "candidate.stdout.txt", args.output / "result",
                                                     offline, oracle, fixture)
            comparison = active_min_candidate.compare(control, measured, control_clock, clocks.replay(after))
        else:
            measured = analysis.profiled_runs(dict(stage="R", arm="current", repetitions=1,
                                                   clock_evidence=after, **report["run"]))
            comparison = analysis.summarize(control, measured, repetitions=1)
            equal_clocks = control_clock["driver_reported_mhz"] == clocks.replay(after)["driver_reported_mhz"]
            comparison.update(equal_driver_reported_clocks=equal_clocks,
                              retention_gate_pass=equal_clocks and comparison["at_most_15_percent_slower"])
        report.update(candidate_observation=measured, comparison=comparison,
                      status=("DERATED_R_ROW_PASS_NOT_MATRIX_ADMISSION" if comparison["retention_gate_pass"]
                              else "DERATED_R_ROW_GATE_FAILED_RETAINED"))
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reference", "returned", "capsule", "platform", "predecessor", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("reference-sha", "unit", "invocation"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--algorithm", choices=PROFILES, required=True)
    parser.add_argument("--sssp-hosts", type=Path, nargs=2, metavar=("PUBLIC", "INTEGRATED"))
    parser.add_argument("--replacement-sssp-host", nargs=2, metavar=("HOST", "SHA256"))
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--bdf", default="0000:82:00.1")
    parser.add_argument("--wait-seconds", type=int, default=43200)
    parser.add_argument("--board-wait-seconds", type=int, default=5400)
    print(run(parser.parse_args())["status"], flush=True)
