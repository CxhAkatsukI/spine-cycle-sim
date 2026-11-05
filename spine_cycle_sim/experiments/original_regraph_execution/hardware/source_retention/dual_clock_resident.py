"""Single resident ResPR pair on explicitly downclocked, stage-screened images."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board import dual_clock_candidate as g_control
from spine_cycle_sim.experiments.evaluation_impact.common_g.continuous_board.execution.supervisor import runner_pins
from ..board_execution import memory_policy, pair_resources
from . import active_min_resident, analysis, clock_profile, clocks, host_correction, repackage_hbm
from . import resident_board as board, resident_results
from .follow import unchanged
from .runtime import check_memory, execute, identity, save


MEASURED = "MEASURED_RESIDENT_PAIR"
BOUNDARY = active_min_resident.BOUNDARY
QUALIFIED_HOST = "cpu_qualified_old_graph_correction_cache"


def admit(r_path, g_path, route):
    screen, measured = g_control.admit_screen(r_path)
    g = json.loads(g_path.read_text())
    profile = screen["profile_mhz"]
    if (g["status"] != "DERATED_G_GATE_PASS" or g["nominal_timing_pass"] is not False
            or g["r_report"] != identity(r_path) or g["profile_mhz"] != profile
            or (g["bdf"], g["device"]) != (measured["bdf"], measured["device"])
            or g["image"] != measured["pins"]["r_current"]
            or g["host"]["sha256"] != board.native_host_sha256(route)):
        raise ValueError("exact same-clock G/R image and bound native host required")
    pins = [identity(r_path), identity(g_path), identity(route / "manifest.json"), *g["pins"]]
    unchanged(pins)
    rows = g["rows"]
    if set(rows) != {"reference", "current"} or g["repetitions"] != 1:
        raise ValueError("one fresh G run per arm required")
    for row in rows.values():
        clock_profile.validate_after(row["clock_preparation"], row["clock_evidence"], profile)
        unchanged([row["stdout"], row["stderr"]])
    config, = analysis.records(rows["reference"]["stdout"]["path"], "G_CONTROL_CONFIG ")
    current = g_control.update_only_profile(Path(rows["current"]["stdout"]["path"]).read_text(),
        Path(g["oracle"]["path"]).read_text(), bdf=g["bdf"], reference=config)
    unchanged([g["oracle"]])
    comparison = g_control.active_min_candidate.compare(analysis.profiled_runs(rows["reference"]),
        current, *(clocks.replay(rows[arm]["clock_evidence"]) for arm in ("reference", "current")))
    if comparison != g["comparison"] or not comparison["retention_gate_pass"]:
        raise ValueError("G retention result does not replay")
    return {"pins": pins, "bdf": g["bdf"], "device": g["device"],
            "resident_mhz": profile, "nominal_timing_pass": False,
            "g_control": comparison, "r_controls": screen["pairs"],
            "host": g["host"], "image": g["image"]}


def declaration(previous, dataset, flickr=None):
    if dataset == "Flickr":
        graph = identity(flickr)
        return board.frozen_case(dataset, Path(graph["path"]), graph), 8, [graph]
    frozen, pins = active_min_resident.frozen_case(previous, "respr", dataset)
    case = {key: frozen[key] for key in ("dataset", "graph", "source", "vertices", "edges", "updates")}
    return dict(case, algorithm="residual_pagerank", requires_propagation=False), frozen["memory_gib"], pins


def spine_inputs(args):
    original = {name: identity(getattr(args, name)) for name in
                ("spine_host", "spine_image", "comparator", "verifier")}
    expected = dict(spine_image=board.SPINE_IMAGE_SHA256,
                    comparator=resident_results.COMPARATOR_SHA256)
    qualification = getattr(args, "qualification", None)
    qualified = []
    if qualification is None:
        expected["spine_host"] = board.SPINE_HOST_SHA256
    else:
        qualified = host_correction.admit(qualification, args.spine_host)
    if any(original[name]["sha256"] != sha for name, sha in expected.items()):
        raise ValueError("frozen Spine binary, host or comparator differs")
    return original, qualified


def run(args):
    with memory_policy.scope(getattr(args, "memory_profile", memory_policy.DEFAULT)):
        return _run(args)


def _run(args):
    case, budget, inputs = declaration(args.previous, args.dataset, args.flickr)
    group = check_memory(budget, require_live_reserve=False)
    args.output.mkdir(parents=True, exist_ok=False)
    report = dict(status="PREDECLARED", dataset=args.dataset, boundary=BOUNDARY,
        warmups=0, repetitions_per_arm=1, attempts=[], board_launch_attempted=False,
        case=case, memory_gib=budget, nominal_timing_pass=False,
        memory_profile=memory_policy.selected(),
        limitation="per-arm oracles; sparse rows may require zero propagation rounds")
    write = lambda: save(args.output / "results.json", report)
    write()
    try:
        gate = admit(args.r_report, args.g_report, args.route)
        args.gr_host = Path(gate["host"]["path"])
        original, qualified = spine_inputs(args)
        if getattr(args, "qualification", None) is not None:
            report.update(qualification=identity(args.qualification), spine_host_mode=QUALIFIED_HOST,
                fresh_samples=dict(spine=1, gr=1), gr_sample_reused=False,
                limitation="single-batch old-graph correction cache preparation excluded and reported")
        profile = gate["resident_mhz"]
        copy = args.output / "spine-clock-copy"
        repackage_hbm.run(args.spine_image, args.verifier, profile[2], copy, profile=profile)
        args.spine_image = copy / "control.xclbin"
        pins = {**original, "spine_image": identity(args.spine_image), "gr_host": gate["host"],
                args.dataset.lower(): identity(case["graph"])}
        evidence = [identity(__file__), *original.values(), *pins.values(), *gate["pins"],
                    *inputs, *qualified, identity(host_correction.__file__), *runner_pins()]
        report.update(stage_gates=gate, bdf=gate["bdf"], device=gate["device"], pins=pins,
                      original_artifacts=original, inputs=evidence, image=gate["image"])
        expected = {arm: clocks.image(image, args.output, arm) for arm, image in
                    (("spine", args.spine_image), ("gr", gate["image"]["path"]))}
        directory = args.output / args.dataset
        directory.mkdir()
        commands = board.commands(args, Path(gate["image"]["path"]), case, directory,
                                  bdf=gate["bdf"], device=gate["device"])
        record = dict(case=case, status="PREDECLARED", rows={}, attempts=[])
        report["row"] = record

        def admission(status, memory):
            report.update(status=status, board_memory=memory)
            write()

        with pair_resources.admit(gate["device"], gate["bdf"], group, args.board_wait_seconds,
                admission, legacy_lock=board.LEGACY_LOCK, memory_gib=budget) as (node, fd):
            for arm in ("spine", "gr"):
                unchanged(evidence)
                prepared = clock_profile.prepare(expected[arm]["binary"]["path"], expected[arm],
                    profile, directory, arm, fd, node, gate["bdf"], memory_gib=budget)
                report.update(status="RUNNING_" + arm.upper(), board_launch_attempted=True)
                report["attempts"].append(arm)
                record["attempts"].append(dict(arm=arm, argv=list(map(str, commands[arm]))))
                write()
                row = execute(commands[arm], directory, arm, fd, node, gate["bdf"],
                              memory_gib=budget, timeout=1800)
                row["clock_evidence"] = clocks.capture(gate["bdf"], expected[arm], directory, arm)
                row["clock"] = clock_profile.check(row["clock_evidence"], profile)
                row["clock_preparation"] = prepared
                clock_profile.validate_after(prepared, row["clock_evidence"], profile)
                record["rows"][arm] = row
                write()
        record["rows"]["gr"]["ranks"] = identity(directory / "gr-ranks.txt")
        record["pair"] = resident_results.analyze(case, record["rows"], args.comparator,
                                                  directory, gate["bdf"])
        if getattr(args, "qualification", None) is not None:
            report["correction"] = host_correction.validate_correction_log(
                Path(record["rows"]["spine"]["stdout"]["path"]).read_text())
        record["comparison_log"] = identity(directory / "pair.json")
        record["status"] = ("MEASURED" if record["pair"]["meets_propagation_screen"]
                            else "RETAINED_WITHOUT_REQUIRED_PROPAGATION")
        report["status"] = MEASURED if record["status"] == "MEASURED" else record["status"]
        unchanged(evidence)
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        report["memory_peak_bytes"] = int((group / "memory.peak").read_text())
        report["memory_events"] = (group / "memory.events").read_text()
        write()
    return report


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    for name in ("previous", "r-report", "g-report", "route", "spine-host", "spine-image",
                 "comparator", "verifier", "output"):
        result.add_argument("--" + name, type=lambda s: Path(s).resolve(), required=True)
    result.add_argument("--dataset", choices=(*active_min_resident.DATASETS, "Flickr"), required=True)
    result.add_argument("--qualification", type=lambda s: Path(s).resolve(),
                        help="Explicit CPU-qualified correction host; both arms still measured once")
    result.add_argument("--flickr", type=lambda s: Path(s).resolve())
    result.add_argument("--board-wait-seconds", type=int, default=21600)
    result.add_argument("--memory-profile", choices=memory_policy.PROFILES, default=memory_policy.DEFAULT)
    return result


if __name__ == "__main__":
    args = parser().parse_args()
    if not 1 <= args.board_wait_seconds <= 21600:
        raise ValueError("finite board admission wait required")
    print(run(args)["status"], flush=True)
