"""Replay ordered publication windows from one pinned candidate-R board run."""

import argparse
import json
from pathlib import Path

from .. import artifact
from ..board_execution import active_min_candidate
from ..board_execution.active_min import BOUNDARY as ACTIVE_MIN_BOUNDARY
from ..board_execution.analysis import event_window
from . import clocks
from .analysis import profiled_runs, public_r_run, records, relocated, summarize, verify_log
from .shard_layout import replay_layout


def publication_windows(config, events, span_ns):
    by_ordinal = {event["ordinal"]: event for event in events}
    origin = min(event["start_ns"] for event in events)
    windows = []
    previous_end = origin
    for shard in range(config["shards"]):
        adapter, gather, mux = (by_ordinal[2 + 3 * shard + i] for i in range(3))
        if mux["start_ns"] < previous_end:
            raise ValueError("mux events violate the ordered publication contract")
        previous_end = mux["end_ns"]
        windows.append({
            "shard": shard, "worker": shard % 4,
            "mux_start_ns": mux["start_ns"] - origin,
            "mux_end_ns": mux["end_ns"] - origin,
            "mux_span_ns": mux["end_ns"] - mux["start_ns"],
            "adapter_end_ns": adapter["end_ns"] - origin,
            "gather_end_ns": gather["end_ns"] - origin,
        })
    worker_ns = [sum(w["mux_span_ns"] for w in windows if w["worker"] == worker)
                 for worker in range(4)]
    milestones = {
        "first_adapter_start_ns": min(by_ordinal[2 + 3 * s]["start_ns"] for s in range(len(windows))) - origin,
        "last_adapter_end_ns": max(w["adapter_end_ns"] for w in windows),
        "last_gather_end_ns": max(w["gather_end_ns"] for w in windows),
        "last_mux_end_ns": windows[-1]["mux_end_ns"],
        "hbm_end_ns": by_ordinal[0]["end_ns"] - origin,
        "apply_end_ns": by_ordinal[1]["end_ns"] - origin,
    }
    return {
        "event_span_ns": span_ns, "pma_slots": config.get("pma_slots"),
        "logical_edges": config["edges"], "windows": windows,
        "candidate_milestones_from_first_start_ns": milestones,
        "mux_span_by_worker_ns": worker_ns,
        "fraction_of_elapsed_by_worker": [value / span_ns for value in worker_ns],
    }


def replay_derated_respr(results, raw_root=None):
    """Replay both arms of a same-clock, one-shot derated ResPR receipt."""
    report = json.loads(results.read_text())
    if ((report["stage"], report["algorithm"], report["case"], report["repetitions"])
            != ("R", "respr", "skewed_sources", 1)
            or report["candidate_launch_attempted"] is not True
            or report["reference_replayed"] is not True):
        raise ValueError("one completed derated ResPR skewed-sources pair required")
    pin = report["reference_receipt"]
    public_path = verify_log(pin, raw_root)
    public = json.loads(public_path.read_text())
    if (public["status"] != "ONE_REFERENCE_ARM_RETAINED_NOT_PAIRED"
            or (public["stage"], public["arm"], public["repetitions"]) != ("R", "reference", 1)
            or any(public[key] != report[key] for key in ("case", "bdf", "device", "input_pins"))
            or public["clock_after"] != report["reference_clock"]):
        raise ValueError("public receipt does not match the measured pair")
    verify_log(public["run"]["stderr"], raw_root)
    public_log = verify_log(public["run"]["stdout"], raw_root)
    if Path(public["result"]["path"]) != Path(pin["path"]).parent / "public/result.json":
        raise ValueError("public result is outside the declared receipt layout")
    public_result = verify_log(public["result"], public_path.parent if raw_root else None)
    original = [public_r_run(public_log, public_result)]
    candidate = profiled_runs(dict(stage="R", arm="current", repetitions=1, **report["run"]), raw_root)
    control_clock = clocks.replay(public["clock_after"], raw_root)
    candidate_clock = clocks.replay(report["clock_after"], raw_root)
    observed = candidate_clock["driver_reported_mhz"]
    if (control_clock["driver_reported_mhz"] != observed or observed[2] != report["hbm_mhz"]
            or {control_clock["bdf"], candidate_clock["bdf"]} != {report["bdf"]}):
        raise ValueError("board or observed clock vector differs across arms")
    comparison = summarize(original, candidate, repetitions=1)
    passes = comparison["at_most_15_percent_slower"]
    status = "DERATED_R_ROW_PASS_NOT_MATRIX_ADMISSION" if passes else "DERATED_R_ROW_GATE_FAILED_RETAINED"
    if (report["status"] != status or original != report["reference_observation"]
            or candidate != report["candidate_observation"]
            or report["comparison"] != dict(comparison, equal_driver_reported_clocks=True, retention_gate_pass=passes)):
        raise ValueError("saved comparison differs from raw observations")
    span = candidate[0]["event_span_ns"]
    windows = candidate_windows(report["run"]["stdout"], span, raw_root)
    target_ns = original[0]["event_span_ns"] * 115 / 100
    last_adapter = windows["candidate_milestones_from_first_start_ns"]["last_adapter_end_ns"]
    return dict(windows, driver_reported_mhz=observed, reference_event_span_ns=original[0]["event_span_ns"],
                gate_pass=passes, gate_target_ns=target_ns, excess_over_gate_ns=max(0, span - target_ns),
                after_last_adapter_ns=span - last_adapter,
                budget_after_last_adapter_ns=target_ns - last_adapter)


def candidate_windows(stdout, span, raw_root, csr=None):
    log = relocated(stdout["path"], raw_root)
    config, = records(log, "RETENTION_CONFIG ")
    report = publication_windows(config, records(log, "RETENTION_EVENT "), span)
    if csr:
        report.update(replay_layout(csr, config))
    return report


def replay(results, case, raw_root=None, csr=None):
    candidates = [row for row in json.loads(results.read_text())["rows"]
                  if (row["stage"], row["arm"], row.get("case")) == ("R", "current", case)]
    if len(candidates) != 1 or candidates[0].get("repetitions") != 1:
        raise ValueError("one declared single-run candidate R row is required")
    row = candidates[0]
    span = profiled_runs(row, raw_root)[0]["event_span_ns"]
    return candidate_windows(row["stdout"], span, raw_root, csr)


def replay_active_min(results, raw_root=None):
    """Diagnose the time budget in a correctness-checked active-min board pair."""
    report = json.loads(results.read_text())
    reference, candidate = (report["arms"][name] for name in ("reference", "candidate"))
    control_ns = reference["analysis"]["event_span_ns"]
    observed, roots, logs = [], [], []
    for arm in (reference, candidate):
        stdout = arm["execution"]["stdout"]
        # A reused A4 arm may live in a different campaign directory in the archive.
        arm_root = raw_root / Path(stdout["path"]).parents[1].name if raw_root is not None else None
        roots.append(arm_root)
        logs.append(verify_log(stdout, arm_root).read_text().splitlines())
        observed.append(clocks.replay(arm["clock_evidence"], arm_root))
    result_lines = [line for line in logs[1] if line.startswith("ACTIVE_MIN_CANDIDATE_BOARD_RESULT")]
    if len(result_lines) != 1 or not (result := active_min_candidate.RESULT.fullmatch(result_lines[0])):
        raise ValueError("one correctness-checked active-min run required")
    logical, vertices, edges, shards, active = result.groups()
    shards = int(shards)
    if (shards <= 0 or active_min_candidate.ALGORITHM[report["algorithm"]] != logical or
            int(active) != candidate["analysis"]["active_outputs"] or
            report["requested_runs_per_arm"] != 1 or report["convergence_measured"] is not False or
            report["boundary"] != ACTIVE_MIN_BOUNDARY or
            report["attempts"] not in (["candidate"], ["reference", "candidate"]) or
            any(clock["bdf"] != report["bdf"] for clock in observed)):
        raise ValueError("saved active-min geometry or run scope differs")
    reference_pins = [pin for pin in reference["analysis"]["output_pins"]
                      if Path(pin["path"]).name == "result.json"]
    if len(reference_pins) != 1 or "A4_ACTIVE_MIN_BOARD_PASS" not in logs[0]:
        raise ValueError("missing public A4 result")
    pin = reference_pins[0]
    original_path = relocated(pin["path"], roots[0] / "pair" if roots[0] else None)
    if artifact.identity(original_path)["sha256"] != pin["sha256"]:
        raise ValueError("active-min reference analysis hash mismatch")
    original = json.loads(original_path.read_text())
    if (original["status"] != "A4_ACTIVE_MIN_BOARD_PASS" or original["hardware_timing_measured"] is not True
            or (original["algorithm"], original["bdf"], original["topology"], original["iterations"],
                original["vertices"], original["logical_edges"]) !=
               (report["algorithm"], report["bdf"], "a4", 1, int(vertices), int(edges))
            or event_window(original["events"]) != (reference["analysis"]["event_union_ns"], control_ns)
            or (original["event_union_ns"], original["event_span_ns"]) !=
               (reference["analysis"]["event_union_ns"], control_ns)):
        raise ValueError("public A4 geometry or event window differs")
    required = [(role, 0, -1, -1) for role in ("hbm", "apply")] + [
        (role, 0, shard, shard % 4) for shard in range(shards)
        for role in ("adapter", "gather", "mux")
    ]
    events, labels = [], []
    for line in logs[1]:
        if line.startswith("SHARDED_DEVICE_EVENT"):
            if not (match := active_min_candidate.EVENT.fullmatch(line)):
                raise ValueError("malformed candidate event")
            role, *values = match.groups()
            step, shard, worker, *times = map(int, values)
            labels.append((role, step, shard, worker))
            events.append(dict(zip(("queued_ns", "submitted_ns", "start_ns", "end_ns"), times),
                               ordinal=len(events)))
    if labels != required or len(events) != candidate["analysis"]["kernel_events"]:
        raise ValueError("missing, unexpected or repeated candidate kernel event")
    union, span = event_window(events)
    decision = active_min_candidate.compare(reference["analysis"], candidate["analysis"], *observed)
    passed = decision["retention_gate_pass"]
    status = "PAIRED_ACTIVE_MIN_R_GATE_PASS" if passed else "PAIRED_ACTIVE_MIN_R_GATE_FAILED_RETAINED"
    if ((union, span) != (candidate["analysis"]["event_union_ns"], candidate["analysis"]["event_span_ns"])
            or decision != report["comparison"] or not decision["equal_driver_reported_clocks"]
            or report["retention_gate_pass"] is not passed or report["status"] != status):
        raise ValueError("saved comparison differs from matched active-min observations")

    windows = publication_windows({"shards": shards, "edges": int(edges)}, events, span)
    mux = windows["windows"]
    gaps = sum(b["mux_start_ns"] - a["mux_end_ns"] for a, b in zip(mux, mux[1:]))
    suffix = span - mux[-1]["mux_end_ns"]
    target = control_ns * 115 // 100
    return {
        "algorithm": report["algorithm"], "reference_event_span_ns": control_ns,
        "candidate_event_span_ns": span, "gate_target_ns": target,
        "minimum_reduction_to_pass_ns": max(0, span - target),
        "driver_reported_mhz": observed[0]["driver_reported_mhz"],
        "mux_span_by_shard_ns": [row["mux_span_ns"] for row in mux],
        "inter_mux_gap_ns": gaps, "after_final_mux_ns": suffix,
        "still_over_gate_without_inter_mux_gaps_and_suffix_ns": max(0, span - gaps - suffix - target),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--case")
    mode.add_argument("--derated-respr", action="store_true", help="replay the archived same-clock skewed-sources pair")
    mode.add_argument("--active-min", action="store_true", help="replay one same-clock SSSP/CC active-min pair")
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--csr", type=Path, help="also replay the frozen resident CSR layout")
    args = parser.parse_args()
    if not args.case and args.csr:
        parser.error("--csr requires --case")
    if args.active_min:
        result = replay_active_min(args.results, args.raw_root)
    elif args.derated_respr:
        result = replay_derated_respr(args.results, args.raw_root)
    else:
        result = replay(args.results, args.case, args.raw_root, args.csr)
    print(json.dumps(result, indent=2))
