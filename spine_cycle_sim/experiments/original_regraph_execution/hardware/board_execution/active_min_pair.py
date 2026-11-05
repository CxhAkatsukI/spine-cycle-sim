"""Measure public A4 and integrated sharded-K4 active-min once on one U55C."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution import runtime
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import (
    replacement_return, tail_topology,
)
from spine_cycle_sim.experiments.sharded_k4_stages.board import require_idle_board
from .. import artifact
from ..source_build.snapshot import unchanged
from ..source_retention import clocks, derated_route, matched_hbm, repackage_hbm, weighted_tail_link
from ..source_retention.follow import unchanged as verify_return_pins
from ..source_retention.runtime import check_memory, execute, lease, save
from . import active_min, active_min_candidate, admission, pair_resources


RETURN_ARGUMENTS = ("SHA256", "CAPSULE", "XPFM", "PREDECESSOR")
ROUTE_MODES = {"cc": "destination", "weighted_sssp": "weighted"}


def candidate_route(route, algorithm):
    paths = [route / name for name in ("manifest.json", "execution/manifest.json", "execution/execution.json")]
    pins = [artifact.identity(path) for path in paths]
    plan, executed, result = [json.loads(path.read_text()) for path in paths]
    image = artifact.identity(route / "candidate.hw.xclbin")
    mode = ROUTE_MODES[algorithm]
    resources = result["resources"]
    if (plan["mode"] != mode or plan["clock_mhz"] != 150 or plan["board_tested"] is not False
            or result["status"] != "LINK_PASS_AWAITING_TIMING_AND_BOARD" or result["xclbin"] != image
            or result["kind"] != "LINK" or result["board_tested"] is not False
            or resources["exit_code"] != 0 or resources["stop_reason"] != "process_exit"
            or resources["cleanup_snapshot_error"] is not None or executed["command"] != plan["command"]
            or any(pin not in executed["pins"] for pin in [pins[0], *plan["pins"]])):
        raise ValueError("candidate needs the exact completed active-min adapter repair link")
    pins.extend([image, *executed["pins"]])
    unchanged(pins)
    return image, pins


def returned_route(route, algorithm, parameters, output):
    digest, capsule, platform, predecessor = parameters
    image, pins = replacement_return.active_min(route, Path(capsule), Path(platform), digest,
                                               Path(predecessor), output, mode=ROUTE_MODES[algorithm])
    proof = artifact.identity(output / "summary.json")
    return image, [*pins, proof], {"directory": str(route), "parameters": list(parameters), "proof": proof}


def lower_clock_options(args):
    options = getattr(args, "derated_hbm", None)
    if options is None:
        return None
    if (args.algorithm != "weighted_sssp" or (args.device, args.bdf) != (0, "0000:82:00.1")
            or not 1 <= getattr(args, "board_wait_seconds", 0) <= 21600
            or getattr(args, "retained_reference", None) or getattr(args, "returned_reference", None)
            or not (getattr(args, "returned_candidate", None) or getattr(args, "pending_return_candidate", None))):
        raise ValueError("lower-clock SSSP requires a returned candidate, fresh public control and bounded card 0 lease")
    target, verifier = options
    target = int(target)
    matched_hbm.validate_profile([150, 500, target, 0], target)
    return target, Path(verifier).resolve(strict=True)


def derated_candidate(args, output, target):
    digest, capsule, platform, predecessor = args.returned_candidate
    transfer = artifact.identity(args.candidate_route.parent / "transfer.json")
    if json.loads(Path(transfer["path"]).read_text())["receipt_sha256"] != digest:
        raise ValueError("sealed remote return digest differs from the collector")
    inputs = SimpleNamespace(returned=args.candidate_route, capsule=Path(capsule), platform=Path(platform),
                             predecessor=Path(predecessor), algorithm=args.algorithm, hbm_mhz=target)
    _, route = derated_route.admit(inputs, output, transfer)
    pins = [transfer, *route["source_pins"], route["image"], route["link_log"],
            route["nominal_timing_report"], route["predecessor"]]
    verify_return_pins(pins)
    return route, [{key: pin[key] for key in ("path", "sha256")} for pin in pins]


def repackage_reference(reference, target, verifier, output):
    verifier_pin = artifact.identity(verifier)
    repackage_hbm.run(reference["path"], verifier, target, output)
    receipt = artifact.identity(output / "package.json")
    packed = json.loads(Path(receipt["path"]).read_text())
    binary = artifact.identity(output / "control.xclbin")
    observations = (packed["original"]["binary"], packed["derived"]["binary"], packed["verifier"])
    if (packed["status"] != "OFFLINE_VERIFIED_NOT_BOARD_QUALIFIED"
            or any(any(observed.get(key) != value for key, value in pin.items())
                   for observed, pin in zip(observations, (reference, binary, verifier_pin)))
            or packed["requested_hbm_mhz"] != target):
        raise ValueError("clock-only public control receipt differs")
    return binary, receipt, verifier_pin


def replay_returned_route(route, algorithm, record, evidence_directory):
    if record["directory"] != str(route):
        raise ValueError("returned route differs from the exact R board receipt")
    digest, capsule, platform, predecessor = record["parameters"]
    _, parent, pins = replacement_return.verify(route, Path(capsule), Path(platform), digest)
    proof = artifact.identity(evidence_directory / "candidate_admission/summary.json")
    image = artifact.identity(route / "route/candidate.hw.xclbin")
    pins.append(artifact.identity(Path(predecessor)))
    checked = json.loads(Path(proof["path"]).read_text())
    timing = artifact.identity(route / "route/timing.rpt")
    topology_profile = tail_topology.PROFILE if "weighted_tail" in parent else None
    if (proof != record["proof"] or parent.get("mode") != ROUTE_MODES[algorithm]
            or checked.get("status") != "ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD"
            or checked.get("topology_profile") != topology_profile
            or checked.get("candidate") != image
            or checked["timing"]["report"] != timing):
        raise ValueError("returned candidate link, mode or topology admission changed")
    original_pins = checked["pins"]
    if original_pins != pins:
        # Tool source pins depend on the worktree. Artifact pins must still match exactly.
        suffix = tuple(replacement_return.__package__.split("."))

        def artifacts(rows):
            return [row for row in rows if Path(row["path"]).parent.parts[-len(suffix):] != suffix]

        if artifacts(original_pins) != artifacts(pins):
            raise ValueError("returned candidate artifact pins changed")
        unchanged(original_pins)
        with TemporaryDirectory(prefix="replay-active-min-") as workspace:
            replayed_image, replayed_pins = replacement_return.active_min(
                route, Path(capsule), Path(platform), digest, Path(predecessor),
                Path(workspace) / "topology", mode=ROUTE_MODES[algorithm])
            if (replayed_image, replayed_pins) != (image, pins):
                raise ValueError("returned candidate topology or replay pins changed")
        pins = list({pin["path"]: pin for pin in [*original_pins, *pins]}.values())
    pins += [image, proof, timing]
    unchanged(pins)
    return image, pins


def xrt_identity(environment):
    return {pin["path"]: pin["sha256"] for pin in environment["pins"]
            if Path(pin["path"]).name.startswith(("libxrt", "libxilinxopencl", "xbutil"))}


def paired_loader(reference, candidate):
    libraries = []
    for host in (reference, candidate):
        process = subprocess.run(["ldd", str(host)], check=True, capture_output=True, text=True, timeout=15)
        if process.stderr.strip():
            raise ValueError("unexpected loader diagnostic before board admission")
        libraries.append(xrt_identity({"pins": [artifact.identity(path)
                                               for path in runtime.library_paths(process.stdout)]}))
    if libraries[0] != libraries[1]:
        raise ValueError("paired board hosts resolve different XRT libraries before board admission")
    return libraries[0]


def input_paths(args):
    return (args.reference_host, args.candidate_host,
            *(args.inputs / f"{name}.u32le" for name in active_min.INPUTS + active_min.STATE[args.algorithm]))


def retained_reference(receipt, digest, args, image, offline, expected):
    pin = artifact.identity(receipt)
    if pin["sha256"] != digest:
        raise ValueError("retained reference pair digest differs")
    previous = json.loads(receipt.read_text())
    if (previous["status"] not in ("PAIRED_ACTIVE_MIN_R_GATE_PASS", "PAIRED_ACTIVE_MIN_R_GATE_FAILED_RETAINED")
            or previous["attempts"] != ["reference", "candidate"]
            or previous["requested_runs_per_arm"] != 1
            or previous["boundary"] != active_min.BOUNDARY
            or (previous["algorithm"], previous["bdf"]) != (args.algorithm, args.bdf)):
        raise ValueError("retained reference needs a complete original single-pass pair")
    reference_host, _, *fixtures = input_paths(args)
    fixed_inputs = [artifact.identity(item) for item in (reference_host, *fixtures)]
    if any(item not in previous["pins"] for item in fixed_inputs):
        raise ValueError("retained reference host or fixture differs")
    row = previous["arms"]["reference"]
    clock = clocks.replay(row["clock_evidence"])
    if (any(clock["binary"].get(key) != image[key] for key in ("path", "sha256"))
            or clock["bdf"] != args.bdf):
        raise ValueError("retained reference image or device differs")
    analysis = active_min.inspect(receipt.parent / "reference", offline, expected, args.inputs, args.bdf)
    if analysis != row["analysis"]:
        raise ValueError("retained reference raw analysis differs")
    unchanged([pin, *analysis["output_pins"]])
    return row, pin


def run(args):
    if (args.algorithm not in active_min.ALGORITHMS or type(args.device) is not int or args.device not in (0, 1)
            or not re.fullmatch(r"[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]", args.bdf)):
        raise ValueError("explicit active-min algorithm, U55C index and PCI address required")
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    path = output / "results.json"
    report = {"status": "PREPARING", "algorithm": args.algorithm, "bdf": args.bdf,
              "boundary": active_min.BOUNDARY, "requested_runs_per_arm": 1,
              "attempts": [], "arms": {}, "retention_gate_pass": False, "convergence_measured": False}
    save(path, report)
    try:
        lower = lower_clock_options(args)
        group = check_memory()
        if int((group / "memory.high").read_text()) > 7 * 2**30:
            raise MemoryError("paired active-min board run requires memory.high at most 7 GiB")
        for host in (args.reference_host, args.candidate_host):
            runtime.require_clean_environment(host, output)
        if any(name.startswith(("ORIGINAL_R_", "GRASU_", "GRASU_REGRAPH_"))
               or name == "XCL_DEVICE_INDEX" for name in os.environ):
            raise ValueError("inherited board or candidate runtime override is forbidden")
        returned = getattr(args, "returned_candidate", None)
        tail_host_pins = weighted_tail_link.check_bound_host(
            returned[1] if returned else None, args.candidate_host, args.algorithm)
        if lower:
            if tail_host_pins:
                raise ValueError("weighted tail requires the nominal clock profile")
            target, verifier = lower
            report.update(target=target, matrix_admitted=False)
            route, pins = derated_candidate(args, output, target)
            report["derated_route"] = route
            if not route["vendor_hbm_mhz"]:
                report["status"] = "NO_COMPATIBLE_DERATING_NO_BOARD_RUN"
                return report
            image = route["image"]
        elif returned:
            image, pins, report["returned_candidate"] = returned_route(
                args.candidate_route, args.algorithm, returned, output / "candidate_admission")
            pins.extend(tail_host_pins)
        else:
            image, pins = candidate_route(args.candidate_route, args.algorithm)
        report["preflight_xrt_libraries"] = paired_loader(args.reference_host, args.candidate_host)
        returned_reference = getattr(args, "returned_reference", None)
        if returned_reference:
            if args.algorithm != "cc":
                raise ValueError("returned public A4 reference is CC only")
            digest, capsule = returned_reference
            checked = admission.review_returned_cc(args.reference_route, Path(capsule), digest,
                                                   output / "reference_admission")
        else:
            checked = admission.review(args.reference_route, output / "reference_admission",
                                       topology="a4", algorithm=args.algorithm)
        pins += checked["pins"]
        reference_image = checked["xclbin"]
        if lower:
            reference_image, receipt, verifier_pin = repackage_reference(
                reference_image, target, verifier, output / "reference_repackage")
            report["reference_package"] = receipt
            pins += [reference_image, receipt, verifier_pin]
        pins += [artifact.identity(item) for item in input_paths(args)]
        offline, expected, oracle_result = active_min.read_offline(args.reference_host, args.algorithm,
                                                                   args.inputs, output)
        pins += [expected, oracle_result]
        report["pins"] = pins
        unchanged(pins)
        commands = {
            "reference": [args.reference_host, "board", args.algorithm, args.inputs, output / "reference",
                          reference_image["path"], args.device],
            "candidate": ["/usr/bin/env", f"XCL_DEVICE_INDEX={args.device}", f"GRASU_REGRAPH_EXPECT_BDF={args.bdf}",
                          args.candidate_host, "--active-min-once", image["path"], args.inputs,
                          expected["path"], output / "candidate"],
        }
        retained = getattr(args, "retained_reference", None)
        arms_to_run = ("reference", "candidate")
        clock_pins = {"reference": reference_image, "candidate": image}
        if retained:
            receipt, digest = retained
            row, pin = retained_reference(Path(receipt).absolute(), digest, args, checked["xclbin"], offline, expected)
            report["arms"]["reference"] = row
            report["retained_reference_pair"] = pin
            pins.extend([pin, *row["analysis"]["output_pins"]])
            arms_to_run = ("candidate",)
            del clock_pins["reference"]
        images = {arm: clocks.image(pin["path"], output, arm) for arm, pin in clock_pins.items()}

        def record(status, memory_state):
            report.update(status=status, memory_admission=memory_state)
            save(path, report)

        wait = getattr(args, "board_wait_seconds", 0)
        board = (pair_resources.admit(args.device, args.bdf, group, wait, record)
                 if wait else lease(args.device, args.bdf))
        with board as (render, fd):
            require_idle_board(render)
            for arm in arms_to_run:
                host = args.reference_host if arm == "reference" else args.candidate_host
                environment = runtime.capture(host, render, output / (arm + "_runtime"))
                if environment["device"]["bdf"] != args.bdf:
                    raise ValueError("runtime does not match leased board")
                observed = xrt_identity(environment)
                if any(observed.get(path) != digest for path, digest in report["preflight_xrt_libraries"].items()):
                    raise ValueError("XRT loader changed between preflight and board admission")
                if arm == "candidate" and xrt_identity(environment) != xrt_identity(report["arms"]["reference"]["runtime"]):
                    raise ValueError("paired board hosts resolve different XRT tool or runtime libraries")
                unchanged(pins)
                row = {"runtime": environment}
                report["arms"][arm] = row
                if lower:
                    row["prepared"] = matched_hbm.prepare(clock_pins[arm]["path"], images[arm], target,
                                                          output, arm, fd, render, args.bdf)
                report["attempts"].append(arm)
                save(path, report)
                row["execution"] = execute(commands[arm], output, arm, fd, render, args.bdf)
                row["clock_evidence"] = clocks.capture(args.bdf, images[arm], output, arm)
                if lower:
                    matched_hbm.validate_after(row["prepared"], row["clock_evidence"], target)
                if arm == "reference":
                    row["analysis"] = active_min.inspect(output / arm, offline, expected, args.inputs, args.bdf)
                else:
                    row["analysis"] = active_min_candidate.inspect(output / "candidate.stdout.txt",
                                                                    output / arm, offline, expected, args.inputs)
                runtime.unchanged(environment, render)
                unchanged(pins + row["analysis"]["output_pins"])
                save(path, report)
        reference, candidate = [report["arms"][arm] for arm in ("reference", "candidate")]
        comparison = active_min_candidate.compare(reference["analysis"], candidate["analysis"],
                                                  clocks.replay(reference["clock_evidence"]),
                                                  clocks.replay(candidate["clock_evidence"]))
        passed = comparison["retention_gate_pass"]
        status = (("PAIRED_LOWER_CLOCK_ROW_PASS" if passed else "PAIRED_LOWER_CLOCK_ROW_GATE_FAILED") if lower
                  else ("PAIRED_ACTIVE_MIN_R_GATE_PASS" if passed else "PAIRED_ACTIVE_MIN_R_GATE_FAILED_RETAINED"))
        report.update(comparison=comparison, retention_gate_pass=passed, status=status)
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        save(path, report)
    return report


def parse_arguments(argv=None, extend=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reference-route", "candidate-route", "reference-host", "candidate-host", "inputs", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--algorithm", choices=active_min.ALGORITHMS, required=True)
    parser.add_argument("--device", type=int, choices=(0, 1), required=True)
    parser.add_argument("--bdf", required=True)
    parser.add_argument("--returned-candidate", nargs=4, metavar=RETURN_ARGUMENTS,
                        help="treat --candidate-route as a verified remote return instead of a local build")
    parser.add_argument("--returned-reference", nargs=2, metavar=("SHA256", "CAPSULE"),
                        help="treat --reference-route as a verified remote public A4 CC return")
    parser.add_argument("--retained-reference", nargs=2, metavar=("PAIR_RESULTS", "SHA256"),
                        help="replay the verified reference from a frozen pair; run only the changed candidate")
    parser.add_argument("--derated-hbm", nargs=2, metavar=("MHZ", "VERIFIER"),
                        help="SSSP diagnostic only: require vendor HBM derating and clock-only public control")
    if extend is not None:
        extend(parser)
    arguments = parser.parse_args(argv)
    for name, value in vars(arguments).items():
        if isinstance(value, Path):
            setattr(arguments, name, value.absolute())
    return arguments


if __name__ == "__main__":
    outcome = run(parse_arguments())
    print(outcome["status"], flush=True)
    raise SystemExit(0 if outcome["retention_gate_pass"] else 1)
