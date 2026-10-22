"""An unchanged-reader lower bound, not a full R performance prediction."""

import json


def parse(text):
    lines = [line.removeprefix("ADAPTER_FLOOR ") for line in text.splitlines()
             if line.startswith("ADAPTER_FLOOR ")]
    if len(lines) != 1:
        raise ValueError("one completed adapter diagnostic required")
    row = json.loads(lines[0])
    workers = row["workers"]
    if any(type(row.get(key)) is not int or row[key] <= 0
           for key in ("cycles", "read_bytes", "requests", "live_edges")):
        raise ValueError("positive integer total counters required")
    if row.get("passed") is not True or len(workers) != 4 or {w["worker"] for w in workers} != set(range(4)):
        raise ValueError("four unique correctness-admitted workers required")
    for worker in workers:
        if any(type(worker.get(key)) is not int or worker[key] < 0 for key in
               ("worker", "adapter_done", "sink_done", "output_stalls", "live_edges",
                "packets", "read_bytes", "requests")):
            raise ValueError("nonnegative integer worker counters required")
        if not (0 < worker["adapter_done"] <= row["cycles"] and
                0 < worker["sink_done"] <= row["cycles"] and worker["output_stalls"] == 0 and
                0 < worker["live_edges"] <= worker["packets"] * 8):
            raise ValueError("completion, live lanes or stall-free sink invalid")
    for key in ("read_bytes", "requests", "live_edges"):
        if row[key] != sum(w[key] for w in workers):
            raise ValueError("worker ledger differs from total")
    return row


def summarize(rows, reference):
    if len(rows) != 4 or {(r["latency"], r["reverse"]) for r in rows} != {
            (latency, reverse) for latency in (64, 128) for reverse in (0, 1)}:
        raise ValueError("complete four-row diagnostic required")
    result = []
    for latency in (64, 128):
        pair = sorted((r for r in rows if r["latency"] == latency), key=lambda r: r["reverse"])
        if pair[0]["observations"] != pair[1]["observations"]:
            raise ValueError("registration order changed floor diagnostic")
        floor = pair[0]["observations"]
        a4 = next(r["observations"]["result"] for r in reference
                  if (r["latency"], r["reverse"], r["arm"]) == (latency, 0, "a4_io16"))
        current = next(r["observations"]["result"] for r in reference
                       if (r["latency"], r["reverse"], r["arm"]) == (latency, 0, "bank_stream"))
        if floor["live_edges"] * current["rounds"] != 1_450_899 * 46 or a4["rounds"] != current["rounds"]:
            raise ValueError("fixed input or convergence scope changed")
        bound = floor["cycles"] * current["rounds"]
        result.append(dict(latency=latency, one_scan_cycles=floor["cycles"],
            unchanged_reader_46_scan_floor=bound, strong_a4_cycles=a4["cycles"],
            current_r_cycles=current["cycles"], floor_over_strong_a4=bound / a4["cycles"],
            full_r_over_stall_free_adapter=current["cycles"] / bound,
            downstream_only_cannot_meet_ten_percent=bound > 1.1 * a4["cycles"]))
    return {"rows": result, "full_r_retention_pass": False, "hardware_calibrated": False,
            "scope": "one unchanged physical PMA scan with four one-packet-per-cycle sinks; "
                     "46-scan extrapolation is a diagnostic lower bound, not new R execution"}
