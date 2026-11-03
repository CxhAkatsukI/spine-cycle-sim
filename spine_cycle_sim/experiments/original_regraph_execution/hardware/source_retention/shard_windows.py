"""Replay ordered publication windows from one pinned candidate-R board run."""

import argparse
import json
from pathlib import Path

from .analysis import profiled_runs, records, relocated
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
    return {
        "event_span_ns": span_ns, "pma_slots": config["pma_slots"],
        "logical_edges": config["edges"], "windows": windows,
        "mux_span_by_worker_ns": worker_ns,
        "fraction_of_elapsed_by_worker": [value / span_ns for value in worker_ns],
    }


def replay(results, case, raw_root=None, csr=None):
    candidates = [row for row in json.loads(results.read_text())["rows"]
                  if (row["stage"], row["arm"], row.get("case")) == ("R", "current", case)]
    if len(candidates) != 1 or candidates[0].get("repetitions") != 1:
        raise ValueError("one declared single-run candidate R row is required")
    row = candidates[0]
    span = profiled_runs(row, raw_root)[0]["event_span_ns"]
    log = relocated(row["stdout"]["path"], raw_root)
    config, = records(log, "RETENTION_CONFIG ")
    report = publication_windows(config, records(log, "RETENTION_EVENT "), span)
    if csr:
        report.update(replay_layout(csr, config))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--case", required=True)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--csr", type=Path, help="also replay the frozen resident CSR layout")
    args = parser.parse_args()
    print(json.dumps(replay(args.results, args.case, args.raw_root, args.csr), indent=2))
