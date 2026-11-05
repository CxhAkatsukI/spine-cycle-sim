"""Sequential, single-pass eight-dataset queue for the explicit downclock profile."""

import argparse
from pathlib import Path

from . import active_min_resident, dual_clock_resident, resident_matrix
from .follow import unchanged
from .runtime import check_memory, identity, save


INPUTS = ("previous", "r_report", "g_report", "route", "spine_host", "spine_image",
          "comparator", "verifier")


def run(args):
    check_memory(require_live_reserve=False)
    args.output.mkdir(parents=True, exist_ok=False)
    gate = dual_clock_resident.admit(args.r_report, args.g_report, args.route)
    cases = {}
    pins = [identity(__file__), identity(dual_clock_resident.__file__), *gate["pins"]]
    for dataset in active_min_resident.DATASETS:
        case, budget, inputs = dual_clock_resident.declaration(args.previous, dataset)
        cases[dataset] = dict(case=case, memory_gib=budget, status="PREDECLARED")
        pins.extend(inputs)
    pins.extend(identity(getattr(args, key)) for key in INPUTS if key not in ("previous", "route"))
    report = dict(status="PREDECLARED", algorithm="residual_pagerank", stage_gates=gate,
        boundary=dual_clock_resident.BOUNDARY, repetitions_per_arm=1, warmups=0,
        nominal_timing_pass=False, cases=cases, pins=pins)
    write = lambda: save(args.output / "matrix.json", report)
    write()
    try:
        for dataset, declaration in cases.items():
            unchanged(pins)
            output = args.output / dataset.lower()
            command = [*resident_matrix.child_service(args.child_prefix, dataset,
                declaration["memory_gib"], dual_clock_resident.__spec__.name),
                "--dataset", dataset, "--output", str(output),
                "--board-wait-seconds", str(args.board_wait_seconds),
                *(part for key in INPUTS for part in
                  ("--" + key.replace("_", "-"), str(getattr(args, key))))]
            declaration.update(status="RUNNING", command=command)
            report.update(status="RUNNING", current=dataset)
            write()
            declaration.update(resident_matrix.run_child(command,
                args.output / (dataset.lower() + ".service.log"), output, dataset,
                gate, dual_clock_resident.BOUNDARY))
            write()
        unchanged(pins)
        report["status"] = ("MEASURED_RESPR_MATRIX" if all(
            case["status"] == resident_matrix.MEASURED for case in cases.values())
            else "RETAINED_INCOMPLETE_MATRIX")
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        write()
    return report


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    for name in (*INPUTS, "output"):
        result.add_argument("--" + name.replace("_", "-"),
                            type=lambda s: Path(s).resolve(), required=True)
    result.add_argument("--child-prefix", required=True)
    result.add_argument("--board-wait-seconds", type=int, default=21600)
    return result


if __name__ == "__main__":
    args = parser().parse_args()
    if not 1 <= args.board_wait_seconds <= 21600:
        raise ValueError("finite board admission wait required")
    print(run(args)["status"], flush=True)
