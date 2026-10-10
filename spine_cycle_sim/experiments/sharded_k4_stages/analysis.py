"""Validate event identity and account for overlapping hardware intervals."""

from __future__ import annotations

from collections import defaultdict


def fields(line: str) -> dict[str, str]:
    return dict(token.split("=", 1) for token in line.split()[1:] if "=" in token)


def union_ns(intervals: list[tuple[int, int]]) -> int:
    total = 0
    end = -1
    for start, stop in sorted(intervals):
        if start < 0 or stop <= start:
            raise ValueError("invalid hardware interval")
        total += max(0, stop - max(start, end))
        end = max(end, stop)
    return total


def peak_concurrency(intervals: list[tuple[int, int]]) -> int:
    changes = [(start, 1) for start, _ in intervals]
    changes += [(end, -1) for _, end in intervals]
    current = peak = 0
    for _, change in sorted(changes):
        current += change
        peak = max(peak, current)
    return peak


def analyze_log(log: str, *, require_trace: bool) -> dict:
    results = [fields(line) for line in log.splitlines()
               if "_RESULT " in line and "conversion_cost=absent" in line]
    timings = [fields(line) for line in log.splitlines() if "_TIMING " in line]
    if len(results) != 1 or results[0].get("status") != "PASS" or len(timings) != 1:
        raise ValueError("one passing compute result and timing record required")
    result = results[0]
    if result.get("k4_frontends") != "4" or result.get("shared_regraph_downstream") != "1":
        raise ValueError("not the actual four-frontend shared downstream path")
    events = []
    identities = set()
    groups = defaultdict(list)
    for line in log.splitlines():
        if not line.startswith("SHARDED_DEVICE_EVENT "):
            continue
        record = fields(line)
        for key in ("round", "shard", "worker", "queued_ns", "submit_ns", "start_ns", "end_ns"):
            record[key] = int(record[key])
        identity = tuple(record[key] for key in ("stage", "round", "shard", "worker"))
        if identity in identities:
            raise ValueError("duplicate device event identity")
        identities.add(identity)
        q, submit, start, end = (record[key] for key in
                                 ("queued_ns", "submit_ns", "start_ns", "end_ns"))
        if not (0 <= q <= submit <= start < end):
            raise ValueError("invalid timestamp ordering")
        groups[record["stage"]].append((start, end))
        events.append(record)
    if require_trace != bool(events):
        raise ValueError("trace enabled/disabled contract violated")
    summary = {"result": result, "timing_ms": {k: float(v) for k, v in timings[0].items()},
               "event_count": len(events), "events": events}
    if not events:
        return summary
    partitions = int(result["destination_partitions"])
    rounds = int(result.get("executed_supersteps", result.get("pipeline_executions", 0)))
    if rounds < 1 or partitions < 1:
        raise ValueError("missing completed compute geometry")
    expected = {(stage, r, p, p % 4) for r in range(rounds) for p in range(partitions)
                for stage in ("adapter", "gather", "mux")}
    expected |= {(stage, r, -1, -1) for r in range(rounds) for stage in ("hbm", "apply")}
    if "pipeline_executions" in result or "source_prepare" in groups:
        expected.add(("source_prepare", 0, -1, -1))
    if identities != expected:
        raise ValueError("incomplete or unexpected compute timeline")
    indexed = {tuple(e[key] for key in ("stage", "round", "shard", "worker")): e
               for e in events}
    for r in range(rounds):
        for p in range(partitions):
            for stage in ("adapter", "gather", "mux"):
                previous = p - (1 if stage == "mux" else 4)
                if previous >= 0:
                    before = indexed[stage, r, previous, previous % 4]
                    after = indexed[stage, r, p, p % 4]
                    if after["start_ns"] < before["end_ns"]:
                        raise ValueError("declared shard event dependency violated")
    compute = [(e["start_ns"], e["end_ns"]) for e in events if e["stage"] != "source_prepare"]
    stage_metrics = {}
    for stage, intervals in groups.items():
        stage_metrics[stage] = {
            "union_ms": union_ns(intervals) / 1e6,
            "sum_ms": sum(end - start for start, end in intervals) / 1e6,
            "max_concurrency": peak_concurrency(intervals),
        }
    span = max(end for _, end in compute) - min(start for start, _ in compute)
    busy = union_ns(compute)
    tails = []
    for r in range(rounds):
        for p in range(partitions):
            adapter = indexed["adapter", r, p, p % 4]
            gather = indexed["gather", r, p, p % 4]
            if adapter["end_ns"] > gather["end_ns"]:
                tails.append((gather["end_ns"], adapter["end_ns"]))
    summary.update({"stages": stage_metrics, "compute_span_ms": span / 1e6,
                    "compute_union_ms": busy / 1e6,
                    "between_compute_events_gap_ms": (span - busy) / 1e6,
                    "adapter_after_gather_union_ms": union_ns(tails) / 1e6,
                    "boundary": "compute_kernel_events_including_stalls_not_exclusive_stage_cycles"})
    return summary
