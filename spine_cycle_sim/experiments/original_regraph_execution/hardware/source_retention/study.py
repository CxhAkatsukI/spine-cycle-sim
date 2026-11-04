"""Run the predeclared G/AU and R/common-single-superstep FPGA matrix."""

import argparse
import json
from pathlib import Path

from ..board_execution import pair_resources
from .runtime import check_memory, execute, identity, lease, save
from .preflight import duplicate_edges
from . import clocks, matched_hbm


def run(args):
    single = getattr(args, "r_single_run", False)
    strict_clocks = getattr(args, "strict_nominal_clocks", False)
    if strict_clocks and not single:
        raise ValueError("nominal clock screening requires a single-run R comparison")
    if single and args.stages != ["R"]:
        raise ValueError("single-run screening is R-only; retain independent G evidence separately")
    output = args.output.resolve()
    output.mkdir(exist_ok=False)
    wait = getattr(args, "board_wait_seconds", 0)
    group = check_memory(require_live_reserve=not wait)
    report = {"status": "PREDECLARED", "publication_match": False, "rows": [], "errors": [],
              "matrix": {"g_batches": [1024, 131072], "g_partition_vertices": [524288, 65536],
                         "r_inputs": ["boundary_ring", "skewed_sources", "amazon"],
                         "stages": args.stages,
                         "repetitions": "one measured resident run per R arm" if single else
                                        "cold then three restored warm runs per arm"},
              "boundary": "resident first-CU-start to last-CU-end; host gaps inside retained; initial DMA/restore/readback outside",
              "gate": "at most 15% slowdown per disclosed matched row; improvements allowed; no claim of publication reproduction",
              "bdf": args.bdf, "device": args.device, "affinity": "124,125",
              "nominal_clock_validation": strict_clocks, "board_attempts": [],
              "pins": {name: identity(getattr(args, name)) for name in
                       ("g_host", "g_input", "g_reference", "g_current", "r_host", "r_candidate", "r_reference", "r_current")},
              "input_pins": {case: [identity(p) for p in sorted((args.r_inputs / case).glob("*.u32le"))]
                             for case in ("boundary_ring", "skewed_sources", "amazon")},
              "cgroup": {name: (group / name).read_text().strip() for name in
                         ("memory.max", "memory.high", "memory.swap.max", "memory.events")},
              "r_profile": {"binding": "csr_degree", "damping": "108/128", "base": 0, "dangling": 0,
                            "threshold": 0, "old_rank": 0, "old_residual": 0, "rounds": 1,
                            "candidate": "existing routed ResPR correction mode; residual equals gather sum"}}
    save(output / "results.json", report)

    def admission_state(status, memory):
        report.update(status=status, admission_memory=memory)
        save(output / "results.json", report)

    try:
        board = (pair_resources.admit(args.device, args.bdf, group, wait, admission_state)
                 if wait else lease(args.device, args.bdf))
        with board as (node, fd):
            images = {arm: clocks.image(getattr(args, "r_" + arm), output, "r_" + arm)
                      for arm in ("reference", "current")} if "R" in args.stages else {}
            report["r_image_metadata"] = images
            save(output / "results.json", report)
            for batch in ((1024, 131072) if "G" in args.stages else ()):
                selected = output / f"au_{batch}.graph"
                with args.g_input.open() as source, selected.open("x") as target:
                    vertices, initial, count = map(int, source.readline().split())
                    if count < batch:
                        raise ValueError("frozen AU input too short")
                    target.write(f"{vertices} {initial} {batch}\n")
                    for _ in range(initial + batch):
                        line = source.readline()
                        if not line:
                            raise ValueError("truncated frozen AU input")
                        target.write(line)
                for partition in (524288, 65536):
                    for arm in ("reference", "current"):
                        name = f"g_{batch}_{partition}_{arm}"
                        report.update(status="RUNNING_" + name)
                        save(output / "results.json", report)
                        command = [args.g_host, getattr(args, "g_" + arm), selected, partition,
                                   int(arm == "current"), 1, args.device, 0]
                        row = execute(command, output, name, fd, node, args.bdf)
                        report["rows"].append({"stage": "G", "batch": batch, "partition": partition,
                                               "arm": arm, "input": identity(selected), **row})
                        save(output / "results.json", report)
                        print(name + " PASS", flush=True)
            for case in (("boundary_ring", "skewed_sources", "amazon") if "R" in args.stages else ()):
                duplicates = duplicate_edges(args.r_inputs / case)
                if duplicates:
                    report["rows"].append({"stage": "R", "case": case, "arm": "current",
                                           "status": "UNSUPPORTED_DUPLICATE_EDGES",
                                           "duplicate_edges": duplicates, "input_unchanged": True})
                    save(output / "results.json", report)
                    print(f"r_{case} UNSUPPORTED ({duplicates} duplicate edges)", flush=True)
                    continue
                for arm in ("reference", "current"):
                    name = f"r_{case}_{arm}"
                    report.update(status="RUNNING_" + name)
                    save(output / "results.json", report)
                    if arm == "reference":
                        destination = output / name
                        command = ([args.r_host, "board"] if single else [args.r_host]) + [
                            args.r_inputs / case, "a4", "csr_degree", destination, args.r_reference, args.device]
                    else:
                        destination = None
                        command = [args.r_candidate, args.r_current, args.r_inputs / case, args.device]
                        if single:
                            command.append(1)
                    preparation = None
                    if strict_clocks:
                        preparation = matched_hbm.prepare(getattr(args, "r_" + arm), images[arm], 450, output,
                                                          name, fd, node, args.bdf, nominal=True)
                    report["board_attempts"].append(name)
                    save(output / "results.json", report)
                    row = execute(command, output, name, fd, node, args.bdf)
                    row["clock_evidence"] = clocks.capture(args.bdf, images[arm], output, name)
                    if preparation:
                        row["clock_preparation"] = preparation
                        matched_hbm.validate_after(preparation, row["clock_evidence"], 450, nominal=True)
                    if single:
                        row["repetitions"] = 1
                        if arm == "reference":
                            row["result_json"] = identity(destination / "result.json")
                    report["rows"].append({"stage": "R", "case": case, "arm": arm,
                                           "result_directory": str(destination) if destination else None, **row})
                    save(output / "results.json", report)
                    print(name + " PASS", flush=True)
            pins = list(report["pins"].values()) + [pin for group in report["input_pins"].values() for pin in group]
            if any(identity(pin["path"]) != pin for pin in pins):
                raise ValueError("execution host, image or frozen input changed during campaign")
        report["status"] = "BOARD_EXECUTION_PASS_PENDING_ANALYSIS"
    except BaseException as error:
        report.update(status="FAILED_RETAINED")
        report["errors"].append(repr(error))
        raise
    finally:
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events_final"] = (group / "memory.events").read_text()
        save(output / "results.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("g-host", "g-input", "g-reference", "g-current", "r-host", "r-candidate",
                 "r-reference", "r-current", "r-inputs", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--device", type=int, choices=(0, 1), default=1)
    parser.add_argument("--bdf", default="0000:c1:00.1")
    parser.add_argument("--stages", nargs="+", choices=("G", "R"), default=["G", "R"])
    parser.add_argument("--r-single-run", action="store_true",
                        help="use the single-run original_r_control host and RUNS=1 candidate; R-only")
    run(parser.parse_args())
