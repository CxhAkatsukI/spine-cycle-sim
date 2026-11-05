"""Single-sample host-only retimes, consuming completed pairs without refitting G+R."""

import argparse
import json
from pathlib import Path
import subprocess
import time

from ..board_execution import memory_policy
from . import active_min_resident, correction_retime, host_correction, resident_matrix
from .follow import unchanged
from .runtime import check_memory, identity, save


MEASURED = "MEASURED_SPINE_HOST_RETIME_REUSED_GR"
INPUTS = ("qualification", "spine_host", "spine_image", "comparator", "verifier")


def ready_cases(upstream, pending):
    return [(dataset, row["result"]) for dataset, row in upstream["cases"].items()
            if dataset in pending and row.get("status") == "MEASURED_RESIDENT_PAIR"]


def pair_with_scope(pair, case):
    pair = dict(pair)
    pair["equal_propagation_rounds"] = pair["gr_rounds"] == pair["spine_rounds"]
    pair["positive_propagation_on_both"] = min(pair["gr_rounds"], pair["spine_rounds"]) > 0
    pair["meets_propagation_screen"] = not case["requires_propagation"] or pair["positive_propagation_on_both"]
    return pair


def validate_result(path, reference, args, dataset):
    result = json.loads(path.read_text())
    old, gate, _ = correction_retime.reference(reference, args.comparator)
    if (result["status"], result["case"], result["dataset"], result["reference_pair"],
            result["qualification"], result["fresh_samples"], result["gr_sample_reused"],
            result["attempts"], result["stage_gates"], result["old_pair"], result["rows"]["gr"]) != (
            MEASURED, old["case"], dataset, identity(reference), identity(args.qualification),
            dict(spine=1, gr=0), True, ["spine"], gate, old["row"]["pair"], old["row"]["rows"]["gr"]):
        raise ValueError("host retime differs from its frozen reference or qualified binary")
    pins = [*result["pins"], result["comparison_log"], *(
        pin for row in result["rows"].values() for pin in (row["stdout"], row["stderr"]))]
    unchanged(pins)
    raw_pair = json.loads(Path(result["comparison_log"]["path"]).read_text())
    if result["pair"] != pair_with_scope(raw_pair, old["case"]):
        raise ValueError("retime analysis changed")
    for row in result["rows"].values():
        correction_retime.clock_profile.validate_after(row["clock_preparation"],
            row["clock_evidence"], gate["resident_mhz"])
    if result["correction"] != correction_retime.validate_correction_log(
            Path(result["rows"]["spine"]["stdout"]["path"]).read_text()):
        raise ValueError("retime changed its correction scope")
    return dict(status=MEASURED, result=identity(path), pair=result["pair"],
                correction=result["correction"])


def run(args):
    check_memory(require_live_reserve=False)
    args.output.mkdir(parents=True, exist_ok=False)
    pins = host_correction.admit(args.qualification, args.spine_host)
    pins += [identity(__file__), identity(correction_retime.__file__),
             *(identity(getattr(args, name)) for name in INPUTS)]
    datasets = getattr(args, "datasets", active_min_resident.DATASETS)
    if not datasets or len(set(datasets)) != len(datasets) or not set(datasets) <= set(active_min_resident.DATASETS):
        raise ValueError("unique known correction datasets required")
    profile = getattr(args, "memory_profile", memory_policy.DEFAULT)
    if profile not in memory_policy.PROFILES:
        raise ValueError("unknown board memory profile")
    cases = {dataset: dict(status="WAITING_FOR_FROZEN_PAIR",
                           memory_gib=32 if dataset in ("LJ", "LJ08") else 16)
             for dataset in datasets}
    report = dict(status="PREDECLARED", cases=cases, pins=pins,
                  fresh_samples_per_case=dict(spine=1, gr=0), gr_sample_reused=True,
                  upstream=str(args.matrix), boundary=correction_retime.dual_clock_resident.BOUNDARY,
                  memory_profile=profile, requested_datasets=list(datasets),
                  complete_eight_dataset_matrix=len(datasets) == 8,
                  limitation="old-graph-only cache prepared outside resident window; single batch")
    write = lambda: save(args.output / "matrix.json", report)
    write()
    try:
        if args.reuse_pk:
            if "PK" not in cases:
                raise ValueError("PK reuse requires PK in the declared dataset selection")
            reference = args.matrix.parent / "pk/results.json"
            cases["PK"].update(validate_result(args.reuse_pk, reference, args, "PK"),
                                existing_sample_reused_without_rerun=True)
            write()
        deadline = time.monotonic() + args.wait_seconds
        while time.monotonic() < deadline:
            unchanged(pins)
            pending = {key for key, value in cases.items() if value["status"] == "WAITING_FOR_FROZEN_PAIR"}
            if not pending:
                break
            ready = ready_cases(json.loads(args.matrix.read_text()), pending)
            if not ready:
                report["status"] = "WAITING_FOR_FROZEN_PAIRS"
                write()
                time.sleep(30)
                continue
            for dataset, pin in ready:
                unchanged([pin])
                reference = Path(pin["path"])
                correction_retime.reference(reference, args.comparator)
                output = args.output / dataset.lower()
                command = [*resident_matrix.child_service(args.child_prefix, dataset,
                    cases[dataset]["memory_gib"], correction_retime.__spec__.name),
                    "--reference-pair", str(reference), "--output", str(output),
                    "--memory-gib", str(cases[dataset]["memory_gib"]),
                    "--memory-profile", profile,
                    "--board-wait-seconds", str(args.wait_seconds),
                    *(part for name in INPUTS for part in
                      ("--" + name.replace("_", "-"), str(getattr(args, name))))]
                cases[dataset].update(status="RUNNING", command=command, reference_pair=pin)
                report.update(status="RUNNING", current=dataset)
                write()
                with (args.output / (dataset.lower() + ".service.log")).open("x") as log:
                    job = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=8 * 3600 + 60)
                path = output / "results.json"
                cases[dataset].update(status="FAILED_RETAINED", service_exit=job.returncode)
                if path.is_file():
                    cases[dataset]["result"] = identity(path)
                if job.returncode == 0:
                    cases[dataset].update(validate_result(path, reference, args, dataset))
                write()
        unchanged(pins)
        report["status"] = ("MEASURED_HOST_RETIME_MATRIX_REUSED_GR" if all(
            row["status"] == MEASURED for row in cases.values()) else "RETAINED_INCOMPLETE_MATRIX")
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        write()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (*INPUTS, "matrix", "output"):
        parser.add_argument("--" + name.replace("_", "-"), type=lambda s: Path(s).resolve(), required=True)
    parser.add_argument("--reuse-pk", type=lambda s: Path(s).resolve())
    parser.add_argument("--child-prefix", required=True)
    parser.add_argument("--wait-seconds", type=int, default=21600)
    parser.add_argument("--datasets", nargs="+", choices=active_min_resident.DATASETS,
                        default=list(active_min_resident.DATASETS))
    parser.add_argument("--memory-profile", choices=memory_policy.PROFILES, default=memory_policy.DEFAULT)
    args = parser.parse_args()
    if not 1 <= args.wait_seconds <= 21600:
        raise ValueError("finite upstream and admission wait required")
    print(run(args)["status"], flush=True)
