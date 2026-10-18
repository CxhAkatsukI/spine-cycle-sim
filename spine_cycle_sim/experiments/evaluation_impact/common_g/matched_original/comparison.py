"""Compare complete original/production G FPGA matrices, without timing fits."""

import argparse
import json
import math
from pathlib import Path
import re
import statistics

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board import execution as original
from spine_cycle_sim.experiments.upstream_controls.grasu.host.fixtures import NAMES
from ..search_pipeline.synthesis import unchanged
from .board import analysis, execution, inputs

SCOPE = "same_input_original_source_U55C_control_not_publication_reproduction"
BOUNDARY = "resident_argument_binding_enqueue_wait_excluding_preparation_dma_readback"
TARGET = 0.10


def _equal(actual, expected):
    return json.dumps(actual, sort_keys=True, allow_nan=False) == json.dumps(
        expected, sort_keys=True, allow_nan=False)


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def _pins(rows):
    indexed = {}
    for row in rows:
        previous = indexed.setdefault(row["path"], row)
        if not _equal(previous, row):
            raise ValueError("conflicting evidence identities for the same path")
    return list(indexed.values())


def compare_rows(original_rows, production_rows, cases, repeats):
    """Use ratio of repeated medians, never average unrelated repeat ratios."""
    if type(repeats) is not int or not 3 <= repeats <= 10 or [case["id"] for case in cases] != list(NAMES):
        raise ValueError("all eight declared inputs and 3--10 repetitions required")
    original.analysis.summaries(original_rows, NAMES, repeats)
    analysis.summaries(production_rows, NAMES, repeats)
    result = []
    for case in cases:
        name = case["id"]
        old = [row["analysis"]["observation"] for row in original_rows if row["case"] == name]
        new = [row["analysis"]["observation"] for row in production_rows if row["case"] == name]
        metrics = {}
        for label, before, after in (
            ("resident_wall", [row["resident_wall_ms"] for row in old], [row["launch_wait_ms"] for row in new]),
            ("kernel_span", [row["kernel_event_span_ns"] / 1e6 for row in old],
             [row["kernel_span_ms"] for row in new]),
        ):
            if not all(_positive(value) for value in before + after):
                raise ValueError("positive finite measured timings required for ratios")
            old_median, new_median = statistics.median(before), statistics.median(after)
            ratio = new_median / old_median
            deviation = abs(ratio - 1)
            metrics[label] = {"original_samples_ms": before, "production_samples_ms": after,
                "original_median_ms": old_median, "production_median_ms": new_median,
                "production_over_original_time": ratio, "original_over_production_speedup": 1 / ratio,
                "absolute_relative_difference": deviation,
                "within_10_percent": deviation <= TARGET or math.isclose(deviation, TARGET, abs_tol=1e-12)}
        result.append({"case": name, "updates": case["facts"]["updates"], "repeats": repeats,
            **metrics, "throughput_ratio_defined": case["facts"]["updates"] > 0,
            "production_publication_barrier_included": True,
            "production_preparation_dma_readback_excluded": True})
    return result


def replay(root, digest, cases, *, production, host_pins):
    """Reparse every raw row; a success label or precomputed median is insufficient."""
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("explicit exact board report digest required")
    pin = identity(root / "results.json")
    report = json.loads((root / "results.json").read_text())
    statuses = {execution.PASS} if production else {original.PASS, original.EXTERNAL_PASS}
    boundary = analysis.BOUNDARY if production else original.analysis.BOUNDARY
    if pin["sha256"] != digest or report.get("status") not in statuses or report.get("errors") != [] or \
            report.get("boundary") != boundary or any(report.get(key) is not True for key in (
                "board_launch_attempted", "board_programmed", "hardware_timing_measured")) or \
            report.get("publication_performance_match") is not False or report.get("final_figures_admitted") is not False:
        raise ValueError("complete successful measured board report with exact boundary required")
    repeats = report.get("repeats")
    if type(repeats) is not int or not 3 <= repeats <= 10:
        raise ValueError("three to ten measured board repetitions required")
    pins = _pins(report["pins"])
    indexed = {row["path"]: row["sha256"] for row in pins}
    required = [*host_pins, *report["runtime"]["pins"], *(case["packet"] for case in cases)]
    if not pins or any(indexed.get(row["path"]) != row["sha256"] for row in required):
        raise ValueError("board report does not bind the reviewed host/input prerequisite")
    unchanged([pin, *pins])
    if production:
        checked = report["admission"]
        if checked.get("status") != "ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD" or \
                checked.get("clock_topology_connectivity_equal") is not True:
            raise ValueError("strict production routed admission required")
    elif report.get("source_modified") is not False or (report["status"] == original.EXTERNAL_PASS) != \
            (report.get("physical_interconnect_changed") is True):
        raise ValueError("original source and physical-port adaptation must remain explicit")
    bdf = report["runtime"]["device"]["bdf"]
    device = report.get("device_index")
    if type(device) is not int or device not in (0, 1):
        raise ValueError("known measured device index required")
    by_name = {case["id"]: case for case in cases}
    expected_attempts = {f"r{repeat}_{case['id']}" for repeat in range(repeats) for case in cases}
    attempts = report["attempts"]
    if len(attempts) != len(expected_attempts) or {row.get("id") for row in attempts} != expected_attempts:
        raise ValueError("complete repeated board attempts required")
    for attempt in attempts:
        command = attempt["command"]
        case = by_name[attempt["id"].split("_", 1)[1]]
        if type(attempt.get("exit_code")) is not int or attempt["exit_code"] != 0 or \
                len(command) != 8 or command[:3] != ["/usr/bin/taskset", "-c", "120"] or \
                command[4:6] != ["--board", case["packet"]["path"]] or command[7] != str(device) or \
                any(path not in indexed for path in (command[3], command[6])):
            raise ValueError("successful same-input common-affinity pinned host/artifact executions required")
    rows = []
    for repeat in range(repeats):
        for case in cases:
            label = f"r{repeat}_{case['id']}"
            stdout, stderr = (root / (label + suffix) for suffix in (".stdout.txt", ".stderr.txt"))
            for path in (stdout, stderr):
                if indexed.get(str(path)) != identity(path)["sha256"]:
                    raise ValueError("raw board observation is absent from the frozen report pins")
            observed = analysis.inspect(stdout.read_text(), stderr.read_text(), case) if production else \
                original.analysis.inspect(stdout, stderr, case, bdf)
            rows.append({"case": case["id"], "repeat": repeat, "analysis": observed})
    summarize = analysis.summaries if production else original.analysis.summaries
    if not _equal(report["rows"], rows) or not _equal(report["summaries"], summarize(rows, NAMES, repeats)):
        raise ValueError("board row/summary differs from independently replayed raw observations")
    unchanged([pin, *pins])
    return report, rows, [pin, *pins]


def run(original_board, production_board, original_preflight, production_preflight, output, *,
        original_board_sha256, production_board_sha256, original_preflight_sha256, production_preflight_sha256):
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "CHECKING", "errors": [], "scope": SCOPE, "boundary": BOUNDARY,
        "target_absolute_relative_difference": TARGET, "hardware_timing_measured": False,
        "publication_performance_match": False, "final_figures_admitted": False}
    try:
        _, cases, production_pins = inputs.load(production_preflight, original_preflight,
            preflight_sha256=production_preflight_sha256, original_preflight_sha256=original_preflight_sha256)
        _, original_cases, original_pins = original.inputs(original_preflight, expected_sha256=original_preflight_sha256)
        if not _equal(cases, original_cases):
            raise ValueError("same frozen original input matrix required on both arms")
        old, old_rows, old_pins = replay(original_board, original_board_sha256, cases,
                                       production=False, host_pins=original_pins)
        new, new_rows, new_pins = replay(production_board, production_board_sha256, cases,
                                       production=True, host_pins=production_pins)
        for key in ("device", "platform"):
            if not _equal(old["runtime"][key], new["runtime"][key]):
                raise ValueError("same physical board, driver and platform required")
        libraries = lambda row: sorted((pin["path"], pin["sha256"]) for pin in row["runtime"]["pins"]
                                       if ".so" in Path(pin["path"]).name)
        if not libraries(old) or libraries(old) != libraries(new):
            raise ValueError("same pinned XRT and dynamic runtime libraries required")
        if old["repeats"] != new["repeats"]:
            raise ValueError("same repetition count required")
        rows = compare_rows(old_rows, new_rows, cases, old["repeats"])
        pins = _pins([*old_pins, *new_pins, identity(Path(__file__))])
        unchanged(pins)
        wall_pass = all(row["resident_wall"]["within_10_percent"] for row in rows)
        report.update(status="SAME_PLATFORM_G_TIMING_CONTROL_COMPLETE_NOT_PUBLICATION_REPRODUCTION",
            rows=rows, pins=pins, hardware_timing_measured=True, same_platform_resident_match=wall_pass,
            same_platform_kernel_span_match=all(row["kernel_span"]["within_10_percent"] for row in rows),
            mismatch_cases=[row["case"] for row in rows if not row["resident_wall"]["within_10_percent"]],
            original_profile=old["profile"], original_physical_interconnect_changed=old["physical_interconnect_changed"],
            note="Production includes its required publication barrier; all cases retained; no timing fit.")
    except BaseException as error:
        report.update(status="FAILED_RETAINED", errors=[repr(error)])
        raise
    finally:
        atomic_write_json(output / "results.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original-board", "production-board", "original-preflight", "production-preflight", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("original-board", "production-board", "original-preflight", "production-preflight"):
        parser.add_argument("--" + name + "-sha256", required=True)
    args = vars(parser.parse_args())
    print(run(**{key: value.resolve() if isinstance(value, Path) else value for key, value in args.items()})["status"])


if __name__ == "__main__":
    main()
