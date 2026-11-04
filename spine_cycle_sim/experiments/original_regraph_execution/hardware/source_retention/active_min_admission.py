"""Replay independent CC/SSSP G and R hardware gates before a resident comparison."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board import active_min_candidate as g_control
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.native_profile import update_only_profile
from .. import artifact
from ..board_execution import active_min, active_min_candidate as r_candidate, active_min_pair
from . import clocks
from .follow import unchanged
from .runtime import identity, save


R_BDF = "0000:82:00.1"
AMAZON_GEOMETRY = (735324, 5158388, 48)
AU_SLICE_GEOMETRY = (156289, 903774, 12)


def checked(pin):
    path = Path(pin["path"])
    if identity(path) != pin:
        raise ValueError("hardware evidence changed: " + str(path))
    return path


def read_report(path, status, algorithm):
    pin = identity(path)
    report = json.loads(checked(pin).read_text())
    if (report.get("status"), report.get("algorithm")) != (status, algorithm):
        raise ValueError(f"{algorithm} hardware stage not admitted: {path} ({report.get('status')})")
    return report, pin


def replay_r(path, algorithm, inputs, host, image, *, geometry=AMAZON_GEOMETRY):
    report, pin = read_report(path, "PAIRED_ACTIVE_MIN_R_GATE_PASS", algorithm)
    retained = report.get("retained_reference_pair")
    attempts = ["candidate"] if retained else ["reference", "candidate"]
    if (report["bdf"] != R_BDF or report["boundary"] != active_min.BOUNDARY
            or report["requested_runs_per_arm"] != 1 or report["attempts"] != attempts
            or report["convergence_measured"] is not False or report["retention_gate_pass"] is not True
            or set(report["arms"]) != {"reference", "candidate"}):
        raise ValueError("expected one same-card R superstep per arm, not a convergence measurement")
    directory = path.parent
    offline = json.loads((directory / "offline/result.json").read_text())
    expected = artifact.identity(directory / "offline/expected.u32le")
    pins = [artifact.identity(Path(host["path"])), artifact.identity(Path(image["path"])),
            expected, artifact.identity(directory / "offline/result.json")]
    pins += [artifact.identity(inputs / f"{name}.u32le") for name in active_min.INPUTS + active_min.STATE[algorithm]]
    if (any(item not in report["pins"] for item in pins) or
            offline.get("status") != "A4_ACTIVE_MIN_OFFLINE_PASS_NOT_FPGA" or
            (offline.get("algorithm"), offline.get("vertices"), offline.get("logical_edges"), offline.get("tasks"))
            != (algorithm, *geometry)):
        raise ValueError("R fixture, oracle, candidate host or bitstream does not match the pinned run")
    unchanged(report["pins"])
    ref, current = (report["arms"][arm] for arm in ("reference", "candidate"))
    for row in (ref, current):
        for stream in ("stdout", "stderr"):
            checked(row["execution"][stream])
    if current["execution"]["command"][-6:] != [host["path"], "--active-min-once", image["path"],
                                                 str(inputs), expected["path"], str(directory / "candidate")]:
        raise ValueError("R candidate command differs from the final host, image or frozen fixture")
    ref_clock, current_clock = (clocks.replay(row["clock_evidence"]) for row in (ref, current))
    checked(ref_clock["binary"])
    if (current_clock["binary"] != image or ref_clock["bdf"] != R_BDF or current_clock["bdf"] != R_BDF):
        raise ValueError("R clock evidence does not bind the repaired image on the leased card")
    if retained:
        receipt = checked(retained)
        reference_host = Path(ref["execution"]["command"][-7])
        args = argparse.Namespace(reference_host=reference_host, candidate_host=Path(host["path"]),
                                  algorithm=algorithm, inputs=inputs, bdf=R_BDF)
        original, original_pin = active_min_pair.retained_reference(
            receipt, retained["sha256"], args, ref_clock["binary"], offline, expected)
        if original != ref or original_pin not in report["pins"]:
            raise ValueError("retained R arm differs from the pinned original")
        observed_ref = original["analysis"]
    else:
        observed_ref = active_min.inspect(directory / "reference", offline, expected, inputs, R_BDF)
    observed_current = r_candidate.inspect(checked(current["execution"]["stdout"]), directory / "candidate",
                                          offline, expected, inputs)
    decision = r_candidate.compare(observed_ref, observed_current, ref_clock, current_clock)
    if (ref["analysis"] != observed_ref or current["analysis"] != observed_current
            or decision != report["comparison"] or not decision["retention_gate_pass"]):
        raise ValueError("R raw event/oracle replay does not pass the 15 percent gate")
    return {"report": pin, "comparison": decision, "candidate_clock": current_clock}


def replay_g(path, reference_path, algorithm, host, image):
    report, pin = read_report(path, "G_GATE_PASS_FOR_ACTIVE_MIN_IMAGE", algorithm)
    reference = identity(reference_path)
    graph, config, ref_clock, ref_runs, _, _ = g_control.reference_arm(reference_path)
    bdf = ref_clock["bdf"]
    if (report["bdf"] != bdf or report["device"] != g_control.BOARDS[bdf]
            or report["repetitions"] != 1 or report["board_launch_attempted"] is not True
            or report["image"] != artifact.identity(Path(image["path"]))
            or any(item not in report["pins"] for item in (host, reference, graph))):
        raise ValueError("expected one independent G run on the exact repaired image and host")
    unchanged(report["pins"])
    row = report["row"]
    checked(row["stderr"])
    if row["command"][-5:] != [host["path"], "--update-only", image["path"], graph["path"], row["oracle"]["path"]]:
        raise ValueError("G candidate command differs from the final host, image or frozen batch")
    profile = update_only_profile(checked(row["stdout"]).read_text(), checked(row["oracle"]).read_text(),
                                  bdf=bdf, reference=config, algorithm=algorithm)
    clock = clocks.replay(row["clock_evidence"])
    if bdf == g_control.QUALIFIED_BDF:
        g_control.matched_hbm.validate_after(report["clock_preparation"], row["clock_evidence"],
                                             450, nominal=True)
    decision = g_control.compare(ref_runs, profile, ref_clock, clock)
    if (clock["binary"] != image or profile != report["profile"] or decision != report["comparison"]
            or not decision["retention_gate_pass"] or profile["config"]["static_edges"] != "390847"):
        raise ValueError("G raw event/PMA replay does not pass the 15 percent gate")
    return {"report": pin, "reference": reference, "comparison": decision, "candidate_clock": clock}


def admit(algorithm, route, host_path, r_path, inputs, g_path, reference):
    host = identity(host_path)
    if host["sha256"] != g_control.HOST_SHA256[algorithm]:
        raise ValueError("expected the exact CC/SSSP native host used for the G/R screens")
    r_receipt, r_pin = read_report(r_path, "PAIRED_ACTIVE_MIN_R_GATE_PASS", algorithm)
    returned = r_receipt.get("returned_candidate")
    if returned:
        route_image, pins = active_min_pair.replay_returned_route(route, algorithm, returned, r_path.parent)
        if returned["proof"] not in r_receipt["pins"]:
            raise ValueError("returned route admission was not pinned before the R board runs")
    else:
        route_image, pins = active_min_pair.candidate_route(route, algorithm)
    image = identity(route_image["path"])
    r = replay_r(r_path, algorithm, inputs, host, image)
    if r["report"] != r_pin:
        raise ValueError("R board receipt changed during route admission")
    g = replay_g(g_path, reference, algorithm, host, image)
    frequency = r["candidate_clock"]["driver_reported_mhz"]
    if frequency != g["candidate_clock"]["driver_reported_mhz"]:
        raise ValueError("the screened candidate clocks differ between G and R")
    unchanged([*pins, host, r["report"], g["report"], g["reference"]])
    return {"status": "BASELINE_STAGES_ADMITTED_NOT_CONVERGENCE", "algorithm": algorithm,
            "image": image, "host": host, "resident_mhz": frequency, "r": r, "g": g}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--algorithm", choices=active_min.ALGORITHMS, required=True)
    for name in ("route", "host", "r-report", "r-inputs", "g-report", "g-reference", "output"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = admit(args.algorithm, args.route, args.host, args.r_report, args.r_inputs,
                   args.g_report, args.g_reference)
    save(args.output, result)
    print(result["status"], flush=True)


if __name__ == "__main__":
    main()
