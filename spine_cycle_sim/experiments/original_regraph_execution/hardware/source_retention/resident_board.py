"""Run the frozen R19/Flickr resident ResPR pair once per arm, after joint G/R admission."""

import argparse
import os
from pathlib import Path

from ..board_execution import pair_resources
from . import clocks, resident_admission, resident_results
from .follow import unchanged
from .resident_admission import BDF, DEVICE, Candidate, NotAdmitted, native_host_sha256
from .runtime import check_memory, execute, identity, save
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.candidate_board import MAX_WAIT_SECONDS


SPINE_HOST_SHA256 = "3499a6a717b79ecb9c7c9716499f6bb811ff2c01d029add3966e501e86015bb1"
SPINE_IMAGE_SHA256 = "b6cb210342029a77233740e7aeffea354d19757ebb68431b0fc993bef59bd15b"
LEGACY_LOCK = Path("/data/chuxiao/builds/gr-prefetch-blocking-axis-trif-20261024/board-device-one.lock")
CASES = {
    "R19": (524288, 15672181, 8, False, "0c984e8c9cfff56d81732451046c2c65701b79efcea968b22bb9c241011b088a"),
    "Flickr": (2552, 8192, 16, True, "b370b2ede9d09ff7ac410fd1f1e487057dffc6468146f11ab9373362ef0d3f8b"),
}


def frozen_case(dataset, graph, graph_pin):
    vertices, edges, updates, requires_propagation, sha = CASES[dataset]
    with graph.open() as stream:
        dimensions = tuple(map(int, stream.readline().split()))
    if graph_pin["sha256"] != sha or dimensions != (vertices, edges, updates):
        raise ValueError(f"{dataset} graph identity or dimensions differ")
    return dict(dataset=dataset, graph=str(graph), algorithm="residual_pagerank", source=0,
                vertices=vertices, edges=edges, updates=updates, requires_propagation=requires_propagation)


def commands(args, image, case, output):
    # Avoid inheriting mode toggles from an interactive shell.
    env = ["/usr/bin/env"]
    for key in sorted(os.environ):
        if key.startswith(("GRASU_", "SPINE_", "XCL_")) or key == "LD_PRELOAD":
            env += ["-u", key]
    env += [f"XCL_DEVICE_INDEX={DEVICE}", "LD_LIBRARY_PATH=/opt/xilinx/xrt/lib:/usr/lib/x86_64-linux-gnu"]
    return {
        "spine": [*env, f"SPINE_EXPECT_BDF={BDF}", args.spine_host, args.spine_image,
                  "--dynamic-graph", case["graph"], "--source", str(case["source"]), "--resident-benchmark"],
        "gr": [*env, f"GRASU_REGRAPH_EXPECT_BDF={BDF}", "GRASU_UPDATE_REPEATS=1",
               "GRASU_SHARDED_PREMIGRATE_INPUTS=1", "GRASU_SHARDED_METADATA_REPLICAS=4",
               "GRASU_SHARDED_EVENT_TRACE=0", args.gr_host, image, case["graph"], output / "gr-ranks.txt"],
    }


def measure(args, case, image, expected, gate, pins, evidence, write, fd, node):
    output = args.output / case["dataset"]
    output.mkdir()
    argv = commands(args, image, case, output)
    rows = evidence["rows"]
    for arm in ("spine", "gr"):
        unchanged(pins)
        evidence["attempts"].append({"arm": arm, "argv": list(map(str, argv[arm]))})
        write()
        rows[arm] = execute(argv[arm], output, arm, fd, node, BDF)
        rows[arm]["clock_evidence"] = clocks.capture(BDF, expected[arm], output, arm)
        rows[arm]["clock"] = clocks.replay(rows[arm]["clock_evidence"])
        write()
    if rows["gr"]["clock"]["driver_reported_mhz"] != gate["resident_mhz"]:
        raise NotAdmitted("paired G+R clocks differ from its independent stage gates")
    rows["gr"]["ranks"] = identity(output / "gr-ranks.txt")
    evidence["pair"] = resident_results.analyze(case, rows, args.comparator, output, BDF)
    evidence["comparison_log"] = identity(output / "pair.json")
    evidence["status"] = ("MEASURED" if evidence["pair"]["meets_propagation_screen"]
                          else "RETAINED_WITHOUT_REQUIRED_PROPAGATION")
    write()


def run(args):
    if not 0 <= args.wait_seconds <= MAX_WAIT_SECONDS:
        raise ValueError("waiting is limited to twelve hours")
    group = check_memory()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREDECLARED", "bdf": BDF, "device": DEVICE, "affinity": "124,125",
              "repetitions_per_arm": 1, "warmups": 0, "full_evaluation_started": False,
              "board_launch_attempted": False, "cases": []}

    def write():
        save(args.output / "results.json", report)

    write()
    try:
        paths = ("spine_host", "spine_image", "comparator", "r19", "flickr")
        pins = {name: identity(getattr(args, name)) for name in paths}
        pins.update(runner=identity(__file__), admission=identity(resident_admission.__file__),
                    analysis=identity(resident_results.__file__), resource_policy=identity(pair_resources.__file__))
        expected_hashes = {"spine_host": SPINE_HOST_SHA256,
                           "spine_image": SPINE_IMAGE_SHA256, "comparator": resident_results.COMPARATOR_SHA256}
        if any(pins[name]["sha256"] != digest for name, digest in expected_hashes.items()):
            raise ValueError("frozen host, Spine image or comparator changed")
        report["cases"] = [
            {"case": frozen_case(dataset, getattr(args, dataset.lower()), pins[dataset.lower()]),
             "status": "PREDECLARED", "attempts": [], "rows": {}} for dataset in CASES
        ]
        declarations = [(args.route, args.r_report, args.g_report, args.gr_host)]
        if args.alternate:
            declarations.append(tuple(path.resolve() for path in args.alternate))
        candidates = [Candidate(route, r, g, identity(host)) for route, r, g, host in declarations]
        if any(c.host_pin["sha256"] != native_host_sha256(c.route) for c in candidates):
            raise ValueError("the declared G+R host does not match its route")
        receipts = {str(c.route): {"r_report": str(c.r_path), "g_report": str(c.g_path),
                                  "host": c.host_pin} for c in candidates}
        report.update(status="WAITING_FOR_G_AND_R", pins=pins, candidates=receipts)
        write()

        def candidate_status(candidate, state):
            receipt = receipts[str(candidate.route)]
            if any(receipt.get(key) != value for key, value in state.items()):
                receipt.update(state)
                write()

        selected, image, gate = resident_admission.wait_for_candidates(
            candidates, args.wait_seconds, candidate_status)
        report["selected_route"] = str(selected.route)
        pins["gr_host"] = selected.host_pin
        args.gr_host = Path(selected.host_pin["path"])
        report["stage_gates"] = gate
        pinned = [*pins.values(), *gate["pins"]]
        unchanged(pinned)
        expected = {arm: clocks.image(path, args.output, arm)
                    for arm, path in (("gr", image), ("spine", args.spine_image))}
        def board_status(status, memory):
            report.update(status=status, board_memory=memory)
            write()

        with pair_resources.admit(DEVICE, BDF, group, args.board_wait_seconds, board_status,
                                  legacy_lock=LEGACY_LOCK) as (node, fd):
            report.update(status="RUNNING_PAIRED_SCREEN", board_launch_attempted=True)
            write()
            for evidence in report["cases"]:
                try:
                    measure(args, evidence["case"], image, expected, gate, pinned, evidence, write, fd, node)
                except (ValueError, KeyError) as error:
                    evidence.update(status="RETAINED_NOT_ADMITTED", error=repr(error))
                    write()
        unchanged(pinned)
        report["status"] = ("PAIRED_SCREEN_MEASURED" if all(row["status"] == "MEASURED" for row in report["cases"])
                            else "PAIRED_SCREEN_NEEDS_REVIEW")
    except NotAdmitted as error:
        report.update(status="NOT_ADMITTED", error=str(error))
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events_final"] = (group / "memory.events").read_text()
        write()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("route", "r-report", "g-report", "gr-host", "spine-host", "spine-image",
                 "comparator", "r19", "flickr", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--board-wait-seconds", type=int, default=21600)
    parser.add_argument("--alternate", type=Path, nargs=4, metavar=("ROUTE", "R_REPORT", "G_REPORT", "GR_HOST"))
    args = parser.parse_args()
    for name, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    print(run(args)["status"], flush=True)
