"""One R sample per arm at a shared, explicitly derated clock profile."""

import argparse
import json
from pathlib import Path

from . import analysis, clock_profile, dual_clock_route, follow, repackage_hbm, study
from .runtime import check_memory, identity, save


def run(args):
    clock_profile.validate(args.profile)
    args.output.mkdir(exist_ok=False)
    report = {"status": "PREPARING", "board_requested": False, "publication_match": False,
              "profile_mhz": args.profile, "nominal_timing_pass": False, "errors": []}
    write = lambda: save(args.output / "results.json", report)
    write()
    try:
        check_memory(require_live_reserve=False)
        parent, admission = dual_clock_route.admit(args, args.output / "route-admission")
        control, pins = follow.control(args.before, args.route, args.output / "board-once")
        pins += follow.matched_hosts(control, parent, args.hosts)
        pins += [admission["image"], identity(args.output / "route-admission/summary.json"),
                 identity(Path(__file__)), identity(args.verifier)]
        report["pins"] = pins
        write()
        originals = {"reference": control.r_reference, "current": Path(admission["image"]["path"])}
        for arm, source in originals.items():
            destination = args.output / (arm + "-clock-copy")
            repackage_hbm.run(source, args.verifier, args.profile[2], destination, profile=args.profile)
            setattr(control, "r_" + arm, destination / "control.xclbin")
        control.device, control.bdf = args.device, args.bdf
        control.board_wait_seconds = 21600
        control.matched_clock_profile = args.profile
        follow.unchanged(pins)
        report.update(status="SCREENING_R_ONCE", board_requested=True)
        write()
        measured = study.run(control)
        pairs = []
        for case in ("skewed_sources", "amazon"):
            rows = {r["arm"]: r for r in measured["rows"] if r["case"] == case}
            for row in rows.values():
                clock_profile.check(row["clock_evidence"], args.profile)
            pairs.append({"case": case, **analysis.summarize(
                analysis.profiled_runs(rows["reference"]), analysis.profiled_runs(rows["current"]), repetitions=1)})
        follow.unchanged(pins)
        passed = all(p["at_most_15_percent_slower"] for p in pairs)
        report.update(status="DERATED_R_GATE_PASS" if passed else "DERATED_R_GATE_FAILED_RETAINED",
                      supported_r_gate_pass=passed, pairs=pairs,
                      measurement=identity(control.output / "results.json"),
                      coverage="two declared supported R inputs; duplicate-edge fixture retained as unsupported")
    except BaseException as error:
        report.update(status="FAILED_RETAINED")
        report["errors"].append(repr(error))
        raise
    finally:
        write()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("before", "route", "returned", "capsule", "platform", "predecessor", "hosts", "verifier", "output"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    parser.add_argument("--profile", type=int, nargs=4, required=True)
    parser.add_argument("--device", type=int, choices=(0, 1), default=0)
    parser.add_argument("--bdf", default="0000:82:00.1")
    print(run(parser.parse_args())["status"], flush=True)
