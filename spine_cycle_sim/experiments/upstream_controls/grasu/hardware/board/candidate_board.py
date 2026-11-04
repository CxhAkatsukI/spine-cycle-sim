"""Measure resident G once on the exact ResPR image after its R board screen."""

import argparse
import json
from pathlib import Path
import time

from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import pair_resources
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    clocks, degree_prefix_link, matched_hbm, returned_route,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.follow import unchanged
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import (
    check_memory, execute, identity, lease, save,
)
from .native_profile import update_only_profile
from .active_min_candidate import compare, reference_arm
from .reference_board import BDF, DEVICE, BOARDS, QUALIFIED_BDF


HOST_NAME = degree_prefix_link.HOST_NAME
HOST_SHA256 = "882acf641227f182985b2c9da4754be8a658f030d9e8371d5799afbcbf3f1ee8"
TAIL_HOST_SHA256 = "25e57511effb18aa2c35368915a46f5bc46e2fcd4fd69c667d7add535e405a68"
R_PASS = "SUPPORTED_R_GATE_PASS_AWAITING_SPINE"
R_FINISHED = {R_PASS, "R_PERFORMANCE_GATE_FAILED_RETAINED"}
MAX_WAIT_SECONDS = 43200


def native_host_sha256(route):
    manifest = json.loads((route / "manifest.json").read_text())
    if prefix := manifest.get("degree_prefix"):
        if (Path(prefix["host"]["path"]).name != HOST_NAME
                or any(pin not in manifest["pins"] for pin in prefix.values())
                or manifest["command"].count(prefix["after"]["path"]) != 1):
            raise ValueError("expected degree replacement and route-matched native host pins")
        unchanged(prefix.values())
        return prefix["host"]["sha256"]
    if "tail_hosts" not in manifest:
        return HOST_SHA256
    unchanged([manifest["tail_hosts"]])
    return TAIL_HOST_SHA256


def wait_for_image(route, r_report, timeout, *, bdf=BDF):
    deadline = time.monotonic() + timeout
    while True:
        check_memory(require_live_reserve=False)
        screen = json.loads(r_report.read_text())
        if screen["status"] in R_FINISHED:
            break
        if screen["status"] == "FAILED_RETAINED":
            raise RuntimeError("the R screen did not complete; candidate G not launched")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("bounded wait for the R screen expired")
        time.sleep(min(30, remaining))
    if proof := screen.get("returned_admission"):
        unchanged([proof])
        if proof not in screen["pins"]:
            raise ValueError("returned route admission was not pinned by the R screen")
        image, image_pin, route_pins = returned_route.replay(route, screen, proof)
    else:
        execution = route / "execution/execution.json"
        routed = json.loads(execution.read_text())
        image = route / "candidate.hw.xclbin"
        image_pin = routed["xclbin"]
        route_pins = [identity(execution), image_pin]
        if (routed["status"] != "LINK_PASS_AWAITING_TIMING_AND_BOARD"
                or image_pin["path"] != str(image) or any(pin not in screen["pins"] for pin in route_pins)):
            raise ValueError("R did not screen this exact completed route")
    unchanged([*route_pins, screen["analysis"], *json.loads((route / "manifest.json").read_text())["pins"]])
    board_report = r_report.parent / "board-once/results.json"
    board = json.loads(board_report.read_text())
    board_image = board["pins"]["r_current"]
    if (board["bdf"] != bdf or board["device"] != BOARDS[bdf]
            or any(board_image[key] != image_pin[key] for key in ("path", "sha256"))):
        raise ValueError("candidate image or board differs from the R screen")
    unchanged([board_image])
    if not proof:
        # Keep the receipt order used by already queued local-route G checks.
        return image, screen["status"], [identity(r_report), route_pins[0], identity(board_report),
                                         image_pin, screen["analysis"]]
    return image, screen["status"], [identity(r_report), identity(board_report), screen["analysis"], *route_pins]


def run(reference, host_dir, route, r_report, output, *, wait_seconds=0):
    if not 0 <= wait_seconds <= MAX_WAIT_SECONDS:
        raise ValueError("waiting is limited to twelve hours")
    group = check_memory(require_live_reserve=False)
    output.mkdir(parents=True, exist_ok=False)
    result = output / "results.json"
    report = {"status": "PREDECLARED", "board_launch_attempted": False, "repetitions": 1,
              "affinity": "124,125", "partition_vertices": 65536,
              "boundary": "first update CU start through last update CU end; includes inter-shard gaps "
                          "and device degree CU; initial residency and final status/readback excluded",
              "publication_match": False}
    save(result, report)
    try:
        ref_graph, config, ref_clock, ref_runs, _, _ = reference_arm(reference)
        bdf = ref_clock["bdf"]
        device = BOARDS[bdf]
        report.update(bdf=bdf, device=device)
        graph = Path(ref_graph["path"])
        binary = host_dir / HOST_NAME
        pins = {key: identity(path) for key, path in {
            "input": graph, "host": binary, "reference": reference, "runner": Path(__file__),
            "host_manifest": host_dir / "manifest.txt",
            "host_source_hashes": host_dir / "weighted_pma_native_host.sha256",
            "route_manifest": route / "manifest.json",
        }.items()}
        host_sha256 = native_host_sha256(route)
        if pins["input"] != ref_graph or pins["host"]["sha256"] != host_sha256:
            raise ValueError("the declared reference measurement, input and route-matched host are required")
        report.update(status="WAITING_FOR_R_SCREEN", pins=pins, reference_clock=ref_clock)
        save(result, report)
        image, r_status, r_pins = wait_for_image(route, r_report, wait_seconds, bdf=bdf)
        unchanged(pins.values())
        report.update(r_status=r_status, r_pins=r_pins)
        expected = clocks.image(image, output, "candidate")
        oracle = output / "native-oracle.txt"
        command = ["/usr/bin/env", "-u", "XCL_EMULATION_MODE", f"XCL_DEVICE_INDEX={device}",
                   f"GRASU_REGRAPH_EXPECT_BDF={bdf}", "GRASU_UPDATE_REPEATS=1",
                   "GRASU_SHARDED_PREMIGRATE_INPUTS=1", "GRASU_SHARDED_METADATA_REPLICAS=4",
                   "GRASU_SHARDED_EVENT_TRACE=0",
                   binary, "--update-only", image, graph, oracle]
        def admission_state(status, memory):
            report.update(status=status, admission_memory=memory)
            save(result, report)

        returned = json.loads(r_report.read_text()).get("returned_admission") in r_pins
        if not returned:
            check_memory()
        board = (pair_resources.admit(device, bdf, group, 21600, admission_state)
                 if returned or bdf == QUALIFIED_BDF else lease(device, bdf))
        with board as (node, fd):
            if bdf == QUALIFIED_BDF:
                report["clock_preparation"] = matched_hbm.prepare(
                    image, expected, 450, output, "candidate", fd, node, bdf, nominal=True)
            report.update(status="RUNNING_CANDIDATE", board_launch_attempted=True,
                          command=list(map(str, command)))
            save(result, report)
            row = execute(command, output, "candidate", fd, node, bdf)
            report["row"] = row
            row["clock_evidence"] = clocks.capture(bdf, expected, output, "candidate")
            if bdf == QUALIFIED_BDF:
                matched_hbm.validate_after(report["clock_preparation"], row["clock_evidence"],
                                           450, nominal=True)
        row["oracle"] = identity(oracle)
        profile = update_only_profile(Path(row["stdout"]["path"]).read_text(), oracle.read_text(),
                                      bdf=bdf, reference=config)
        if int(profile["config"]["static_edges"]) != 390847:
            raise ValueError("unexpected candidate initial edge count")
        clock = clocks.replay(row["clock_evidence"])
        comparison = compare(ref_runs, profile, ref_clock, clock)
        unchanged([*pins.values(), *r_pins])
        report.update(status="G_GATE_PASS_FOR_AU_RES_PR_IMAGE" if comparison["retention_gate_pass"]
                      else "G_PERFORMANCE_GATE_FAILED_RETAINED", profile=profile, comparison=comparison,
                      candidate_clock=clock)
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
