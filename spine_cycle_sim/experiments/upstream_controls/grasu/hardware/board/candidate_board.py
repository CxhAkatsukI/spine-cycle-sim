"""Measure resident G once on the exact ResPR image after its R board screen."""

import argparse
import json
from pathlib import Path
import time

from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import clocks
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.analysis import (
    profiled_runs, records, summarize,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.follow import unchanged
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import (
    check_memory, execute, identity, lease, save,
)
from .native_profile import update_only_profile
from .reference_board import BDF, DEVICE, IMAGE_SHA256, INPUT_SHA256


HOST_NAME = "sharded_k4_residual_pagerank_native_host"
HOST_SHA256 = "882acf641227f182985b2c9da4754be8a658f030d9e8371d5799afbcbf3f1ee8"
TAIL_HOST_SHA256 = "25e57511effb18aa2c35368915a46f5bc46e2fcd4fd69c667d7add535e405a68"
R_PASS = "SUPPORTED_R_GATE_PASS_AWAITING_SPINE"
R_FINISHED = {R_PASS, "R_PERFORMANCE_GATE_FAILED_RETAINED"}
MAX_WAIT_SECONDS = 43200


def native_host_sha256(route):
    manifest = json.loads((route / "manifest.json").read_text())
    if "tail_hosts" not in manifest:
        return HOST_SHA256
    unchanged([manifest["tail_hosts"]])
    return TAIL_HOST_SHA256


def wait_for_image(route, r_report, timeout):
    deadline = time.monotonic() + timeout
    while True:
        check_memory()
        screen = json.loads(r_report.read_text())
        if screen["status"] in R_FINISHED:
            break
        if screen["status"] == "FAILED_RETAINED":
            raise RuntimeError("the R screen did not complete; candidate G not launched")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("bounded wait for the R screen expired")
        time.sleep(min(30, remaining))
    execution = route / "execution/execution.json"
    routed = json.loads(execution.read_text())
    image = route / "candidate.hw.xclbin"
    if (routed["status"] != "LINK_PASS_AWAITING_TIMING_AND_BOARD"
            or routed["xclbin"]["path"] != str(image)
            or routed["xclbin"] not in screen["pins"]
            or identity(execution) not in screen["pins"]):
        raise ValueError("R did not screen this exact completed route")
    unchanged([routed["xclbin"], screen["analysis"], *json.loads((route / "manifest.json").read_text())["pins"]])
    board_report = r_report.parent / "board-once/results.json"
    board = json.loads(board_report.read_text())
    board_image = board["pins"]["r_current"]
    if (board["bdf"] != BDF or board["device"] != DEVICE
            or any(board_image[key] != routed["xclbin"][key] for key in ("path", "sha256"))):
        raise ValueError("candidate image or board differs from the R screen")
    unchanged([board_image])
    return image, screen["status"], [identity(r_report), identity(execution), identity(board_report),
                                     routed["xclbin"], screen["analysis"]]


def run(reference, host_dir, route, r_report, output, *, wait_seconds=0):
    if not 0 <= wait_seconds <= MAX_WAIT_SECONDS:
        raise ValueError("waiting is limited to twelve hours")
    group = check_memory()
    output.mkdir(parents=True, exist_ok=False)
    result = output / "results.json"
    report = {"status": "PREDECLARED", "board_launch_attempted": False, "repetitions": 1,
              "bdf": BDF, "device": DEVICE, "affinity": "124,125", "partition_vertices": 65536,
              "boundary": "first update CU start through last update CU end; includes inter-shard gaps "
                          "and device degree CU; initial residency and final status/readback excluded",
              "publication_match": False}
    save(result, report)
    try:
        frozen = json.loads(reference.read_text())
        graph = Path(frozen["pins"]["input"]["path"])
        binary = host_dir / HOST_NAME
        pins = {key: identity(path) for key, path in {
            "input": graph, "host": binary, "reference": reference, "runner": Path(__file__),
            "host_manifest": host_dir / "manifest.txt",
            "host_source_hashes": host_dir / "weighted_pma_native_host.sha256",
            "route_manifest": route / "manifest.json",
        }.items()}
        host_sha256 = native_host_sha256(route)
        if (frozen["status"] != "REFERENCE_MEASURED_AWAITING_CANDIDATE"
                or frozen["bdf"] != BDF or frozen["device"] != DEVICE or frozen["partition_vertices"] != 65536
                or frozen["pins"]["image"]["sha256"] != IMAGE_SHA256
                or pins["input"]["sha256"] != INPUT_SHA256 or pins["host"]["sha256"] != host_sha256):
            raise ValueError("the declared reference measurement, input and route-matched host are required")
        ref_runs = profiled_runs(frozen["row"])
        config, = records(frozen["row"]["stdout"]["path"], "G_CONTROL_CONFIG ")
        if (config != frozen["config"] or (config["vertices"], config["updates"], config["shards"],
                                            config["pma_slots"], config["metadata_replicas"])
                != (515281, 131072, 8, 2245472, 4)):
            raise ValueError("unexpected reference input dimensions")
        ref_clock = clocks.replay(frozen["row"]["clock_evidence"])
        if ref_clock["bdf"] != BDF or ref_clock["binary"] != frozen["pins"]["image"]:
            raise ValueError("wrong reference image or board clock evidence")
        report.update(status="WAITING_FOR_R_SCREEN", pins=pins, reference_clock=ref_clock)
        save(result, report)
        image, r_status, r_pins = wait_for_image(route, r_report, wait_seconds)
        unchanged(pins.values())
        report.update(r_status=r_status, r_pins=r_pins)
        if host_sha256 == TAIL_HOST_SHA256 and r_status != R_PASS:
            report["status"] = "NOT_ADMITTED_R_FAILED"
            return report
        expected = clocks.image(image, output, "candidate")
        oracle = output / "native-oracle.txt"
        command = ["/usr/bin/env", "-u", "XCL_EMULATION_MODE", f"XCL_DEVICE_INDEX={DEVICE}",
                   f"GRASU_REGRAPH_EXPECT_BDF={BDF}", "GRASU_UPDATE_REPEATS=1",
                   "GRASU_SHARDED_PREMIGRATE_INPUTS=1", "GRASU_SHARDED_METADATA_REPLICAS=4",
                   "GRASU_SHARDED_EVENT_TRACE=0",
                   binary, "--update-only", image, graph, oracle]
        with lease(DEVICE, BDF) as (node, fd):
            report.update(status="RUNNING_CANDIDATE", board_launch_attempted=True,
                          command=list(map(str, command)))
            save(result, report)
            row = execute(command, output, "candidate", fd, node, BDF)
            report["row"] = row
            row["clock_evidence"] = clocks.capture(BDF, expected, output, "candidate")
        row["oracle"] = identity(oracle)
        profile = update_only_profile(Path(row["stdout"]["path"]).read_text(), oracle.read_text(),
                                      bdf=BDF, reference=config)
        if int(profile["config"]["static_edges"]) != 390847:
            raise ValueError("unexpected candidate initial edge count")
        comparison = summarize(ref_runs, [profile], repetitions=1)
        unchanged([*pins.values(), *r_pins])
        report.update(status="G_GATE_PASS_FOR_AU_RES_PR_IMAGE" if comparison["at_most_15_percent_slower"]
                      else "G_PERFORMANCE_GATE_FAILED_RETAINED", profile=profile, comparison=comparison,
                      candidate_clock=clocks.replay(row["clock_evidence"]))
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events_final"] = (group / "memory.events").read_text()
        save(result, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reference", "host-dir", "route", "r-report", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--wait-seconds", type=int, default=0)
    args = parser.parse_args()
    print(run(*(getattr(args, name).resolve() for name in ("reference", "host_dir", "route", "r_report", "output")),
              wait_seconds=args.wait_seconds)["status"], flush=True)
