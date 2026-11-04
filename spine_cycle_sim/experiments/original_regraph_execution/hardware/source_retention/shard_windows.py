"""Replay ordered publication windows from one pinned candidate-R board run."""

import argparse
import json
from pathlib import Path

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
        "event_span_ns": span_ns, "pma_slots": config["pma_slots"],
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--case")
    mode.add_argument("--derated-respr", action="store_true", help="replay the archived same-clock skewed-sources pair")
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--csr", type=Path, help="also replay the frozen resident CSR layout")
    args = parser.parse_args()
    if args.derated_respr and args.csr:
        parser.error("--csr requires --case")
    result = (replay_derated_respr(args.results, args.raw_root) if args.derated_respr
              else replay(args.results, args.case, args.raw_root, args.csr))
    print(json.dumps(result, indent=2))
