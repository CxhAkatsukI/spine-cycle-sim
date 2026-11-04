"""Admit a single ResPR comparison only on the independently screened image."""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import time

from spine_cycle_sim.experiments.upstream_controls.grasu.hardware.board.candidate_board import (
    BDF, DEVICE, HOST_SHA256, R_PASS, native_host_sha256, wait_for_image,
)
from .follow import unchanged
from . import respr_retention_audit
from .runtime import check_memory, identity


G_PASS = respr_retention_audit.G_PASS
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


def wait_for_candidates(candidates, frozen_r, wait_seconds, record):
    pending = list(candidates)
    if not 1 <= len(pending) <= 3 or len(set(c.route for c in pending)) != len(pending):
        raise ValueError("declare one to three distinct candidate routes")
    deadline = time.monotonic() + wait_seconds
    while pending:
        check_memory(require_live_reserve=False)
        for candidate in tuple(pending):
            try:
                states = [json.loads(path.read_text())["status"] if path.is_file() else "WAITING_FOR_RECEIPT"
                          for path in (candidate.r_path, candidate.g_path)]
                record(candidate, {"R": states[0], "G": states[1]})
                if any(state in FAILURES for state in states):
                    raise NotAdmitted(f"terminal stage result: R={states[0]}, G={states[1]}")
                if states == [R_PASS, G_PASS]:
                    image, gate = replay_gate(candidate, frozen_r)
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


def replay_gate(candidate, frozen_r):
    route, r_path, g_path, host_pin = candidate.route, candidate.r_path, candidate.g_path, candidate.host_pin
    g_pin = identity(g_path)
    g = json.loads(g_path.read_text())
    image, _, r_pins = wait_for_image(route, r_path, 0)
    board = json.loads((r_path.parent / "board-once/results.json").read_text())
    analysis = json.loads((r_path.parent / "analysis/summary.json").read_text())
    r_pairs = validate_gates(analysis, g, r_pins, host_pin, host_sha256=native_host_sha256(route))
    g_reference = g["pins"]["reference"]
    g_control = respr_retention_audit.g_gate(g, Path(g_reference["path"]), identity(image), host_pin)
    r_control = respr_retention_audit.r_controls(board, json.loads(Path(frozen_r["path"]).read_text()))
    resident_mhz = g_control["driver_mhz"]["current"]
    if (not g_control["retention_gate_pass"]
            or any(not row["retention_gate_pass"] or row["driver_mhz"]["current"] != resident_mhz
                   for row in r_control.values())):
        raise NotAdmitted("raw G/R timings or actual clocks do not pass")
    for pair in r_pairs:
        actual = r_control[pair["case"]]
        if any(pair[key] != value for key, value in actual.items() if key in pair):
            raise NotAdmitted("R summary differs from the raw one-shot replay")
    pins = [*r_pins, g_pin, g_reference, frozen_r]
    unchanged(pins)
    return image, {"pins": pins, "r_controls": r_control, "g_control": g_control,
                   "resident_mhz": resident_mhz}
