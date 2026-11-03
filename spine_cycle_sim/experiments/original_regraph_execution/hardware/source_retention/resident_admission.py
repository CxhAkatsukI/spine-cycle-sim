"""Admit a single ResPR comparison only on the independently screened image."""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import time

from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.active_min_candidate import (
    compare, reference_arm,
)
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.candidate_board import (
    BDF, DEVICE, HOST_SHA256, R_PASS, native_host_sha256, wait_for_image,
)
from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.native_profile import update_only_profile

from . import clocks
from .analysis import profiled_runs, summarize
from .follow import unchanged
from .runtime import check_memory, identity


G_PASS = "G_GATE_PASS_FOR_AU_RES_PR_IMAGE"
FAILURES = {"FAILED_RETAINED", "R_PERFORMANCE_GATE_FAILED_RETAINED",
            "G_PERFORMANCE_GATE_FAILED_RETAINED", "NOT_ADMITTED_R_FAILED"}


class NotAdmitted(ValueError):
    """A dependency finished but did not establish baseline retention."""


@dataclass(frozen=True)
class Candidate:
    route: Path
    r_path: Path
    g_path: Path
    host_pin: dict


def passed(row):
    ratio = row["current_over_reference"]
    return (type(ratio) in (int, float) and math.isfinite(ratio)
            and 0 < ratio <= 1.15 and row["at_most_15_percent_slower"] is True)


def validate_gates(r_summary, g_report, r_pins, host_pin, *, host_sha256=HOST_SHA256):
    pairs = [row for row in r_summary["pairs"] if row["stage"] == "R"]
    if (len(pairs) != 2 or {row["case"] for row in pairs} != {"skewed_sources", "amazon"}
            or not all(passed(row) and row["clock_evidence_recorded"] is True for row in pairs)):
        raise NotAdmitted("both declared R controls must pass the raw elapsed-time gate")
    if (g_report["status"] != G_PASS or g_report["r_status"] != R_PASS
            or g_report["r_pins"] != r_pins or g_report["bdf"] != BDF
            or g_report["device"] != DEVICE or g_report["repetitions"] != 1
            or g_report["pins"]["host"] != host_pin or host_pin["sha256"] != host_sha256
            or not passed(g_report["comparison"])):
        raise NotAdmitted("the exact R-screened ResPR image and host must also pass G")
    return pairs


def wait_for_candidates(candidates, wait_seconds, record):
    pending = list(candidates)
    if not 1 <= len(pending) <= 2 or len(set(c.route for c in pending)) != len(pending):
        raise ValueError("declare one or two distinct candidate routes")
    deadline = time.monotonic() + wait_seconds
    while pending:
        check_memory()
        for candidate in tuple(pending):
            try:
                states = [json.loads(path.read_text())["status"] if path.is_file() else "WAITING_FOR_RECEIPT"
                          for path in (candidate.r_path, candidate.g_path)]
                record(candidate, {"R": states[0], "G": states[1]})
                if any(state in FAILURES for state in states):
                    raise NotAdmitted(f"terminal stage result: R={states[0]}, G={states[1]}")
                if states == [R_PASS, G_PASS]:
                    image, gate = replay_gate(candidate)
                    return candidate, image, gate
            except (ValueError, OSError, KeyError, TypeError) as error:
                pending.remove(candidate)
                record(candidate, {"rejected": str(error)})
        if not pending:
            raise NotAdmitted("no candidate passed both raw, clock-matched G and R hardware gates")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("no joint G and R hardware pass before the bounded deadline")
        time.sleep(min(30, remaining))


def matching_clock(row, binary, mhz=None):
    clock = clocks.replay(row["clock_evidence"])
    if (clock["binary"] != binary or clock["bdf"] != BDF
            or (mhz is not None and clock["driver_reported_mhz"] != mhz)):
        raise NotAdmitted("hardware screen differs in image, PCI device or actual clocks")
    return clock


def replay_r(board, pairs, image_pin, mhz):
    reference = board["pins"]["r_reference"]
    unchanged([reference])
    for pair in pairs:
        rows = [row for row in board["rows"] if row["case"] == pair["case"] and row["stage"] == "R"]
        arms = {row["arm"]: row for row in rows}
        if (len(rows) != 2 or set(arms) != {"reference", "current"}
                or any(row["repetitions"] != 1 for row in rows)):
            raise NotAdmitted("each R control must have exactly one measured run per arm")
        matching_clock(arms["reference"], reference, mhz)
        matching_clock(arms["current"], image_pin, mhz)
        actual = summarize(*(profiled_runs(arms[arm]) for arm in ("reference", "current")), repetitions=1)
        if not passed(actual) or any(pair[key] != value for key, value in actual.items()):
            raise NotAdmitted("R summary does not match the raw timestamp envelope")
    return reference


def replay_g(g, image_pin, host_pin):
    ref_pin = g["pins"]["reference"]
    row = g["row"]
    unchanged([ref_pin, g["pins"]["input"], host_pin, row["stdout"], row["stderr"], row["oracle"]])
    graph, config, ref_clock, ref_runs, _, _ = reference_arm(Path(ref_pin["path"]))
    if graph != g["pins"]["input"] or g["command"][-5:] != [
        host_pin["path"], "--update-only", image_pin["path"], graph["path"], row["oracle"]["path"]
    ]:
        raise NotAdmitted("G command did not use the declared one-shot input, host and image")
    clock = matching_clock(row, image_pin, ref_clock["driver_reported_mhz"])
    profile = update_only_profile(Path(row["stdout"]["path"]).read_text(),
                                  Path(row["oracle"]["path"]).read_text(), bdf=BDF, reference=config)
    actual = compare(ref_runs, profile, ref_clock, clock)
    if not actual["retention_gate_pass"] or any(g["comparison"][key] != actual[key] for key in g["comparison"]):
        raise NotAdmitted("G summary does not match the raw timestamp envelope")
    return actual, clock["driver_reported_mhz"], ref_pin


def replay_gate(candidate):
    route, r_path, g_path, host_pin = candidate.route, candidate.r_path, candidate.g_path, candidate.host_pin
    g_pin = identity(g_path)
    g = json.loads(g_path.read_text())
    image, _, r_pins = wait_for_image(route, r_path, 0)
    board = json.loads((r_path.parent / "board-once/results.json").read_text())
    analysis = json.loads((r_path.parent / "analysis/summary.json").read_text())
    r_pairs = validate_gates(analysis, g, r_pins, host_pin, host_sha256=native_host_sha256(route))
    image_pin = identity(image)
    g_control, resident_mhz, g_reference = replay_g(g, image_pin, host_pin)
    r_reference = replay_r(board, r_pairs, image_pin, resident_mhz)
    pins = [*r_pins, g_pin, g_reference, r_reference]
    unchanged(pins)
    return image, {"pins": pins, "r_controls": r_pairs, "g_control": g_control,
                   "resident_mhz": resident_mhz}
