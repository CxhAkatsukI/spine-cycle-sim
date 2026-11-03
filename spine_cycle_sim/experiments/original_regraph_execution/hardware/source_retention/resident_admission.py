"""Admit a single ResPR comparison only on the independently screened image."""

import json
import math
import time

from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.candidate_board import (
    BDF, DEVICE, HOST_SHA256, wait_for_image,
)

from . import clocks
from .follow import unchanged
from .runtime import check_memory, identity


R_PASS = "SUPPORTED_R_GATE_PASS_AWAITING_SPINE"
G_PASS = "G_GATE_PASS_FOR_AU_RES_PR_IMAGE"


class NotAdmitted(ValueError):
    """A dependency finished but did not establish baseline retention."""


def passed(row):
    ratio = row["current_over_reference"]
    return (type(ratio) in (int, float) and math.isfinite(ratio)
            and 0 < ratio <= 1.15 and row["at_most_15_percent_slower"] is True)


def validate_gates(r_summary, g_report, r_pins, host_pin):
    pairs = [row for row in r_summary["pairs"] if row["stage"] == "R"]
    if (len(pairs) != 2 or {row["case"] for row in pairs} != {"skewed_sources", "amazon"}
            or not all(passed(row) and row["clock_evidence_recorded"] is True for row in pairs)):
        raise NotAdmitted("both declared R controls must pass the raw elapsed-time gate")
    if (g_report["status"] != G_PASS or g_report["r_status"] != R_PASS
            or g_report["r_pins"] != r_pins or g_report["bdf"] != BDF
            or g_report["device"] != DEVICE or g_report["repetitions"] != 1
            or g_report["pins"]["host"] != host_pin or host_pin["sha256"] != HOST_SHA256
            or not passed(g_report["comparison"])):
        raise NotAdmitted("the exact R-screened ResPR image and host must also pass G")
    return pairs


def wait_for_gate(route, r_path, g_path, host_pin, wait_seconds):
    deadline = time.monotonic() + wait_seconds
    while True:
        check_memory()
        r, g = (json.loads(path.read_text()) if path.is_file() else {}
                for path in (r_path, g_path))
        for name, report in (("R", r), ("G", g)):
            if report.get("status") in {"FAILED_RETAINED", f"{name}_PERFORMANCE_GATE_FAILED_RETAINED"}:
                raise NotAdmitted(f"{name}: {report['status']}; see {r_path if name == 'R' else g_path}")
        if r.get("status") == R_PASS and g.get("status") == G_PASS:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("no joint G and R hardware pass before the bounded deadline")
        time.sleep(min(30, remaining))

    g_pin = identity(g_path)
    g = json.loads(g_path.read_text())
    image, _, r_pins = wait_for_image(route, r_path, 0)
    board = json.loads((r_path.parent / "board-once/results.json").read_text())
    analysis = json.loads((r_path.parent / "analysis/summary.json").read_text())
    r_pairs = validate_gates(analysis, g, r_pins, host_pin)
    current = [row for row in board["rows"] if row["arm"] == "current" and "stdout" in row]
    if (len(current) != 2 or {row["case"] for row in current} != {"skewed_sources", "amazon"}
            or any(row["repetitions"] != 1 for row in current)):
        raise NotAdmitted("the current image was not screened once on both R controls")
    image_pin = identity(image)
    g_clock = clocks.replay(g["row"]["clock_evidence"])
    resident_mhz = g_clock["driver_reported_mhz"]
    for clock in (g_clock, *(clocks.replay(row["clock_evidence"]) for row in current)):
        if (clock["binary"] != image_pin or clock["bdf"] != BDF
                or clock["driver_reported_mhz"] != resident_mhz):
            raise NotAdmitted("G and R hardware screens did not use the same image, board and actual clocks")
    pins = [*r_pins, g_pin]
    unchanged(pins)
    return image, {"pins": pins, "r_controls": r_pairs, "g_control": g["comparison"],
                   "resident_mhz": resident_mhz}
