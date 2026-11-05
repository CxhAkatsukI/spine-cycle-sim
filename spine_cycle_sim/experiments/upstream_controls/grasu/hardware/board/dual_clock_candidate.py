"""One public-G / degree-prefix-G pair at the R-screened shared clocks."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.original_regraph_execution.hardware.board_execution import (
    active_min_pair, pair_resources,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention import (
    analysis, clock_profile, clocks, repackage_hbm,
)
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.follow import unchanged
from spine_cycle_sim.experiments.original_regraph_execution.hardware.source_retention.runtime import (
    check_memory, execute, identity, save,
)
from . import active_min_candidate, candidate_board, reference_board
from .native_profile import update_only_profile


def admit_screen(path):
    report = json.loads(path.read_text())
    if (report["status"] != "DERATED_R_GATE_PASS" or report["supported_r_gate_pass"] is not True
            or report["nominal_timing_pass"] is not False):
        raise ValueError("a completed, explicitly derated R pass is required")
    profile = report["profile_mhz"]
    clock_profile.validate(profile)
    unchanged([identity(path), report["measurement"], *report["pins"]])
    measured = json.loads(Path(report["measurement"]["path"]).read_text())
    pairs = []
    for case in ("skewed_sources", "amazon"):
        arms = {row["arm"]: row for row in measured["rows"] if row["case"] == case}
        for row in arms.values():
            clock_profile.check(row["clock_evidence"], profile)
        pairs.append(dict(case=case, **analysis.summarize(
            analysis.profiled_runs(arms["reference"]), analysis.profiled_runs(arms["current"]),
            repetitions=1)))
    if pairs != report["pairs"] or not all(p["at_most_15_percent_slower"] for p in pairs):
        raise ValueError("the R screen does not replay from its raw one-shot logs")
    return report, measured


def run(args):
    group = check_memory(require_live_reserve=False)
    args.output.mkdir(exist_ok=False)
    report = dict(status="PREPARING", board_launch_attempted=False, repetitions=1,
        publication_match=False, nominal_timing_pass=False,
        boundary="first update CU start through last update CU end, including shard gaps and candidate degree CU; residency/readback excluded")
    write = lambda: save(args.output / "results.json", report)
    write()
    try:
        screen, r_board = admit_screen(args.r_report)
        graph, config, _, _, public_host, public_xrt = active_min_candidate.reference_arm(args.reference)
        bdf, device = r_board["bdf"], r_board["device"]
        if reference_board.BOARDS.get(bdf) != device:
            raise ValueError("invalid board in R evidence")
        native = args.host_dir / candidate_board.HOST_NAME
        host = identity(native)
        if host["sha256"] != candidate_board.native_host_sha256(args.route):
            raise ValueError("the candidate native host does not match its route")
        loaders = active_min_pair.paired_loader(public_host["path"], native)
        if loaders.get(public_xrt["path"]) != public_xrt["sha256"]:
            raise ValueError("G hosts must use the public control's XRT library")
        previous = json.loads(args.reference.read_text())
        images = {"reference": Path(previous["pins"]["image"]["path"]),
                  "current": Path(r_board["pins"]["r_current"]["path"])}
        profile = screen["profile_mhz"]
        destination = args.output / "reference-clock-copy"
        repackage_hbm.run(images["reference"], args.verifier, profile[2], destination, profile=profile)
        images["reference"] = destination / "control.xclbin"
        pins = [identity(p) for p in (args.reference, args.r_report, args.route / "manifest.json",
                args.verifier, native, Path(__file__))]
        pins += [graph, public_host, public_xrt, screen["measurement"], *screen["pins"],
                 *[identity(p) for p in images.values()]]
        report.update(pins=pins, bdf=bdf, device=device, profile_mhz=profile,
                      r_report=identity(args.r_report), image=identity(images["current"]),
                      host=host, rows={}, xrt_libraries=loaders)
        expected = {arm: clocks.image(image, args.output, arm) for arm, image in images.items()}
        oracle = args.output / "native-oracle.txt"
        commands = {
            "reference": [public_host["path"], images["reference"], graph["path"], 65536, 0, 1, device, 0],
            "current": ["/usr/bin/env", "-u", "XCL_EMULATION_MODE", f"XCL_DEVICE_INDEX={device}",
                f"GRASU_REGRAPH_EXPECT_BDF={bdf}", "GRASU_UPDATE_REPEATS=1",
                "GRASU_SHARDED_PREMIGRATE_INPUTS=1", "GRASU_SHARDED_METADATA_REPLICAS=4",
                "GRASU_SHARDED_EVENT_TRACE=0", native, "--update-only",
                images["current"], graph["path"], oracle],
        }

        def record(status, memory):
            report.update(status=status, admission_memory=memory)
            write()

        with pair_resources.admit(device, bdf, group, 21600, record) as (node, fd):
            for arm in ("reference", "current"):
                unchanged(pins)
                preparation = clock_profile.prepare(images[arm], expected[arm], profile,
                    args.output, arm, fd, node, bdf)
                report.update(status="RUNNING_" + arm.upper(), board_launch_attempted=True)
                write()
                row = execute(commands[arm], args.output, arm, fd, node, bdf)
                row.update(clock_preparation=preparation, stage="G", arm=arm, repetitions=1,
                    clock_evidence=clocks.capture(bdf, expected[arm], args.output, arm))
                clock_profile.check(row["clock_evidence"], profile)
                clock_profile.validate_after(preparation, row["clock_evidence"], profile)
                report["rows"][arm] = row
                write()
        public_config, = analysis.records(report["rows"]["reference"]["stdout"]["path"], "G_CONTROL_CONFIG ")
        if public_config != config:
            raise ValueError("public workload changed")
        current = update_only_profile(Path(report["rows"]["current"]["stdout"]["path"]).read_text(),
            oracle.read_text(), bdf=bdf, reference=config)
        if int(current["config"]["static_edges"]) != 390847:
            raise ValueError("candidate initial graph changed")
        comparison = active_min_candidate.compare(analysis.profiled_runs(report["rows"]["reference"]),
            current, *(clocks.replay(report["rows"][arm]["clock_evidence"])
                       for arm in ("reference", "current")))
        unchanged(pins)
        report.update(status="DERATED_G_GATE_PASS" if comparison["retention_gate_pass"]
                      else "DERATED_G_GATE_FAILED_RETAINED", comparison=comparison,
                      profile=current, oracle=identity(oracle))
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events"] = (group / "memory.events").read_text()
        write()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("reference", "r-report", "route", "host-dir", "verifier", "output"):
        parser.add_argument("--" + name, type=lambda value: Path(value).resolve(), required=True)
    print(run(parser.parse_args())["status"], flush=True)
