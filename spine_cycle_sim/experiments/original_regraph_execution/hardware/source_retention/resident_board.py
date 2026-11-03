"""Run the frozen R19/Flickr resident ResPR pair once per arm, after joint G/R admission."""

import argparse
import fcntl
import os
from pathlib import Path

from . import clocks, resident_admission, resident_results
from .follow import unchanged
from .resident_admission import BDF, DEVICE, NotAdmitted, native_host_sha256
from .runtime import check_memory, execute, identity, lease, save
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
        paths = ("gr_host", "spine_host", "spine_image", "comparator", "r19", "flickr")
        pins = {name: identity(getattr(args, name)) for name in paths}
        pins.update(runner=identity(__file__), admission=identity(resident_admission.__file__),
                    analysis=identity(resident_results.__file__))
        expected_hashes = {"gr_host": native_host_sha256(args.route), "spine_host": SPINE_HOST_SHA256,
                           "spine_image": SPINE_IMAGE_SHA256, "comparator": resident_results.COMPARATOR_SHA256}
        if any(pins[name]["sha256"] != digest for name, digest in expected_hashes.items()):
            raise ValueError("frozen host, Spine image or comparator changed")
        report["cases"] = [
            {"case": frozen_case(dataset, getattr(args, dataset.lower()), pins[dataset.lower()]),
             "status": "PREDECLARED", "attempts": [], "rows": {}} for dataset in CASES
        ]
        report.update(status="WAITING_FOR_G_AND_R", pins=pins)
        write()
        image, gate = resident_admission.wait_for_gate(args.route, args.r_report, args.g_report,
                                                       pins["gr_host"], args.wait_seconds)
        report["stage_gates"] = gate
        pinned = [*pins.values(), *gate["pins"]]
        unchanged(pinned)
        expected = {arm: clocks.image(path, args.output, arm)
                    for arm, path in (("gr", image), ("spine", args.spine_image))}
        # Interlock with both the earlier paired matrix and the stage controls.
        with LEGACY_LOCK.open("rb") as legacy:
            fcntl.flock(legacy, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with lease(DEVICE, BDF) as (node, fd):
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
    args = parser.parse_args()
    for name, value in vars(args).items():
        if isinstance(value, Path):
            setattr(args, name, value.resolve())
    print(run(args)["status"], flush=True)
