"""Measure public A4 and integrated sharded-K4 active-min once on one U55C."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution import runtime
from spine_cycle_sim.experiments.evaluation_impact.common_g.complete_pipeline.hardware.remote import replacement_return
from spine_cycle_sim.experiments.sharded_k4_stages.board import require_idle_board
from .. import artifact
from ..source_build.snapshot import unchanged
from ..source_retention import clocks
from ..source_retention.runtime import check_memory, execute, lease, save
from . import active_min, active_min_candidate, admission, pair_resources


def candidate_route(route, algorithm):
    paths = [route / name for name in ("manifest.json", "execution/manifest.json", "execution/execution.json")]
    pins = [artifact.identity(path) for path in paths]
    plan, executed, result = [json.loads(path.read_text()) for path in paths]
    image = artifact.identity(route / "candidate.hw.xclbin")
    mode = {"cc": "destination", "weighted_sssp": "weighted"}[algorithm]
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
        group = check_memory()
        if int((group / "memory.high").read_text()) > 7 * 2**30:
            raise MemoryError("paired active-min board run requires memory.high at most 7 GiB")
        for host in (args.reference_host, args.candidate_host):
            runtime.require_clean_environment(host, output)
        if any(name.startswith(("ORIGINAL_R_", "GRASU_", "GRASU_REGRAPH_"))
               or name == "XCL_DEVICE_INDEX" for name in os.environ):
            raise ValueError("inherited board or candidate runtime override is forbidden")
        returned = getattr(args, "returned_candidate", None)
        if returned:
            digest, capsule, platform, predecessor = returned
            mode = {"cc": "destination", "weighted_sssp": "weighted"}[args.algorithm]
            image, pins = replacement_return.active_min(args.candidate_route, Path(capsule), Path(platform),
                digest, Path(predecessor), output / "candidate_admission", mode=mode)
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
        pins += [artifact.identity(item) for item in input_paths(args)]
        offline, expected, oracle_result = active_min.read_offline(args.reference_host, args.algorithm,
                                                                   args.inputs, output)
        pins += [expected, oracle_result]
        report["pins"] = pins
        unchanged(pins)
        commands = {
            "reference": [args.reference_host, "board", args.algorithm, args.inputs, output / "reference",
                          checked["xclbin"]["path"], args.device],
            "candidate": ["/usr/bin/env", f"XCL_DEVICE_INDEX={args.device}", f"GRASU_REGRAPH_EXPECT_BDF={args.bdf}",
                          args.candidate_host, "--active-min-once", image["path"], args.inputs,
                          expected["path"], output / "candidate"],
        }
        clock_pins = {"reference": checked["xclbin"], "candidate": image}
        images = {arm: clocks.image(pin["path"], output, arm) for arm, pin in clock_pins.items()}

        def record(status, memory_state):
            report.update(status=status, memory_admission=memory_state)
            save(path, report)

        wait = getattr(args, "board_wait_seconds", 0)
        board = (pair_resources.admit(args.device, args.bdf, group, wait, record)
                 if wait else lease(args.device, args.bdf))
        with board as (render, fd):
            require_idle_board(render)
            for arm, host in (("reference", args.reference_host), ("candidate", args.candidate_host)):
                environment = runtime.capture(host, render, output / (arm + "_runtime"))
                if environment["device"]["bdf"] != args.bdf:
                    raise ValueError("runtime does not match leased board")
                observed = xrt_identity(environment)
                if any(observed.get(path) != digest for path, digest in report["preflight_xrt_libraries"].items()):
                    raise ValueError("XRT loader changed between preflight and board admission")
                if arm == "candidate" and xrt_identity(environment) != xrt_identity(report["arms"]["reference"]["runtime"]):
                    raise ValueError("paired board hosts resolve different XRT tool or runtime libraries")
                unchanged(pins)
                report["attempts"].append(arm)
                save(path, report)
                row = {"runtime": environment}
                report["arms"][arm] = row
                row["execution"] = execute(commands[arm], output, arm, fd, render, args.bdf)
                row["clock_evidence"] = clocks.capture(args.bdf, images[arm], output, arm)
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
        report.update(comparison=comparison, retention_gate_pass=comparison["retention_gate_pass"],
                      status=("PAIRED_ACTIVE_MIN_R_GATE_PASS" if comparison["retention_gate_pass"]
                              else "PAIRED_ACTIVE_MIN_R_GATE_FAILED_RETAINED"))
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
    parser.add_argument("--returned-candidate", nargs=4, metavar=("SHA256", "CAPSULE", "XPFM", "PREDECESSOR"),
                        help="treat --candidate-route as a verified remote return instead of a local build")
    parser.add_argument("--returned-reference", nargs=2, metavar=("SHA256", "CAPSULE"),
                        help="treat --reference-route as a verified remote public A4 CC return")
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
