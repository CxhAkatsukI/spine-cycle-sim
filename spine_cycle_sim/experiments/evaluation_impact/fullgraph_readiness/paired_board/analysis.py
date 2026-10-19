"""Validate recorded execution contracts and aggregate complete paired matrices."""

import json
import math
from pathlib import Path
from statistics import median

from ..board_analysis import BOUNDARY
from .. import board_memory
from ..preparation import ALGORITHMS, DATASETS

PASS = "PAIRED_RESIDENT_BOARD_REPORTS_REPLAYED_NOT_BASELINE_OR_FIGURE_ADMISSION"
CLAIMS = ("production_baseline_admitted", "publication_match", "spine_comparison")
DIMENSIONS = ("dataset", "algorithm", "vertices", "initial_edges", "updates", "source", "graph", "sha256")


def replay(report, plan, experiment, output, read):
    """Reparse raw records; this does not attest a systemd exit or rerun hardware."""
    if report.get("status") != experiment.pass_status or report.get("errors") != [] or \
            report.get("execution_requested") is not True or report.get("board_requested") is not True or \
            report.get("hardware_convergence_measured") is not True or \
            any(report.get(key) is not False for key in CLAIMS):
        raise ValueError("complete successful board report with no promoted claims required")
    if report["experiment"] != experiment.name or report["boundary"] != BOUNDARY or \
            report["algorithm"] != plan["algorithm"]:
        raise ValueError("algorithm, experiment or resident wall boundary differs")
    if {k: v for k, v in report["plan"].items() if k != "pins"} != \
            {k: v for k, v in plan.items() if k != "pins"}:
        raise ValueError("saved plan differs from revalidated preflight/artifact admission")
    if not all(pin in report["pins"] for pin in plan["pins"]):
        raise ValueError("complete source, input and artifact pin closure required")
    limits = report["containment"]["limits"]
    declared = report["policy"]
    board_memory.validate(limits, declared)
    board_memory.require_unthrottled(report["memory_events_after"])
    affinity = report["cpu_affinity"]
    repeats = report["repeats"]
    if len(affinity) != 2 or len(set(affinity)) != 2 or \
            type(repeats) is not int or not 3 <= repeats <= 10:
        raise ValueError("fixed two-CPU affinity and at least three repetitions required")
    bdf = report["runtime"]["device"]["bdf"]
    expected_env = experiment.environment(report["device_index"], bdf)
    if any(report["environment"].get(k) != v for k, v in expected_env.items()):
        raise ValueError("recorded device, repeat or trace environment differs")
    smokes = plan.get("smokes", [plan["smoke"]])
    cases = [("smoke", row, index) for index, row in enumerate(smokes)] + [
        ("matrix", row, repeat) for repeat in range(repeats) for row in plan["rows"]]
    attempts = report["attempts"]
    if len(attempts) != len(cases) or [row["dataset"] for row in plan["rows"]] != list(DATASETS):
        raise ValueError("complete ordered smoke and eight-graph repetitions required")
    for attempt, (scope, row, repeat) in zip(attempts, cases):
        if (attempt["scope"], attempt["dataset"], attempt["repeat"], attempt["status"]) != \
                (scope, row["dataset"], repeat, "PASS"):
            raise ValueError("ordered smoke/matrix execution differs")
        name = f"{scope}_r{repeat}_{row['dataset']}"
        resources = attempt["resources"]
        if resources != json.loads(read("raw/" + name + ".resources.json")):
            raise ValueError("saved child resources differ from raw record")
        if resources["exit_code"] != 0 or resources["stop_reason"] != "process_exit" or \
                resources["cleanup_snapshot_error"] is not None or \
                resources["host_affinity"] != affinity or \
                resources["tree_memory_gib"] != declared["tree_memory_gib"] or \
                resources["reserve_gib"] != 32 or \
                resources["timeout_seconds"] != (600 if scope == "smoke" else 1800):
            raise ValueError("failed child or changed execution/resource boundary")
        result = output / (name + ".result.txt")
        if resources["command"] != experiment.command(plan, row, result) or resources["cwd"] != str(output):
            raise ValueError("recorded command differs from admitted host boundary")
        analyzed = experiment.analyze(row, read("raw/" + name + ".stdout.txt"),
                                     read("raw/" + name + ".stderr.txt"), bdf=bdf)
        if attempt["analysis"] != analyzed:
            raise ValueError("saved analysis differs from raw board output")
        if experiment.writes_result_file and attempt["result_identity"]["path"] != str(result):
            raise ValueError("result identity belongs to a different child")
    return report


def runtime_key(report):
    captured = report["runtime"]
    device = captured["device"]
    platform = captured["platform"]
    if platform["status"]["mig_calibrated"] != "true":
        raise ValueError("calibrated memory required")
    libraries = sorted((Path(pin["path"]).name, pin["sha256"]) for pin in captured["pins"]
                       if ".so" in Path(pin["path"]).name or Path(pin["path"]).name == "xbutil")
    if not libraries:
        raise ValueError("frozen runtime library identities required")
    return ([device[k] for k in ("driver_version", "driver_srcversion", "kernel_release")],
            platform["static_region"], libraries)


def clock(report):
    plan = report["plan"]
    topology = plan.get("topology", plan.get("artifact_admission", {}).get("topology", {}))
    data = [row for row in topology["clock"] if row[0] == "DATA"]
    if data != [["DATA", "DATA_CLK", 150]]:
        raise ValueError("same admitted 150-MHz data clock required")


def aggregate(gr, spine):
    """Only complete matrices yield ratios; never synthesize missing values."""
    reports = [*gr, *spine]
    for arm in (gr, spine):
        if [r["algorithm"] for r in arm] != list(ALGORITHMS):
            raise ValueError("all three distinct algorithms required in declared order")
    first = reports[0]
    for report in reports:
        clock(report)
        if report["boundary"] != BOUNDARY or report["cpu_affinity"] != first["cpu_affinity"] or \
                report["repeats"] != first["repeats"] or runtime_key(report) != runtime_key(first):
            raise ValueError("matched wall, affinity, repeats and runtime required")
    rows = []
    for left, right in zip(gr, spine):
        for a, b in zip(left["plan"]["rows"], right["plan"]["rows"]):
            if any(a.get(key) != b.get(key) for key in DIMENSIONS) or a["input_identity"] != b["input_identity"]:
                raise ValueError("same graph identity, source and update batch required")
            times = []
            for report in (left, right):
                attempts = [p for p in report["attempts"] if p["scope"] == "matrix" and p["dataset"] == a["dataset"]]
                if [p["repeat"] for p in attempts] != list(range(report["repeats"])) or \
                        any(p["status"] != "PASS" for p in attempts):
                    raise ValueError("complete per-dataset repetitions required")
                values = [p["analysis"]["resident_wall_ms"] for p in attempts]
                if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in values):
                    raise ValueError("finite positive measured wall times required")
                times.append(values)
            rows.append({**{key: a[key] for key in DIMENSIONS},
                         "gr_wall_ms": times[0], "spine_wall_ms": times[1],
                         "gr_median_ms": median(times[0]), "spine_median_ms": median(times[1]),
                         "speedup_gr_over_spine": median(times[0]) / median(times[1])})
    if len(rows) != 24 or [(r["algorithm"], r["dataset"]) for r in rows] != [
            (a, d) for a in ALGORITHMS for d in DATASETS]:
        raise ValueError("all 24 matched algorithm/dataset rows required")
    return {"status": PASS, "boundary": BOUNDARY, "rows": rows,
            "aggregation": "ratio_of_medians_of_independent_state_restoring_processes",
            "report_replay_only": True, "service_exit_attested": False,
            "stage_calibration": False, "publication_match": False,
            "production_baseline_admitted": False, "final_figures_admitted": False}
