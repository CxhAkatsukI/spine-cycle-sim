"""Validate existing completion timestamps; overlapping endpoints are not stage costs."""

import csv


ROUND_FIELDS = ("round", "start", "apply_done", "writeback_done", "status_done", "end", "active")
INVOCATION_FIELDS = ("round", "partition", "worker", "adapter", "start", "end")


def read(path, fields):
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(fields):
            raise ValueError("unexpected progress schema")
        rows = []
        for row in reader:
            if set(row) != set(fields) or any(value is None or not value.isascii() or not value.isdecimal()
                                               for value in row.values()):
                raise ValueError("nonnegative integer progress fields required")
            rows.append({key: int(value) for key, value in row.items()})
    return rows


def analyze(rounds, invocations, observations, partitions):
    trajectory = observations["trajectory"]
    if not rounds or [r["round"] for r in rounds] != list(range(len(trajectory))):
        raise ValueError("complete ordered progress rounds required")
    if type(partitions) is not int or partitions <= 0:
        raise ValueError("positive partition count required")
    expected = {(r, p, a) for r in range(len(rounds)) for p in range(partitions) for a in (0, 1)}
    actual = [(r["round"], r["partition"], r["adapter"]) for r in invocations]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("unique complete frontend invocation records required")
    for i, row in enumerate(rounds):
        start, end = row["start"], row["end"]
        if end <= start or (i and start != rounds[i - 1]["end"]):
            raise ValueError("round windows are not contiguous")
        if any(not start < row[key] <= end for key in ("apply_done", "writeback_done", "status_done")):
            raise ValueError("completion outside round window")
        if row["status_done"] < row["apply_done"]:
            raise ValueError("status completed before Apply")
        if end - start != trajectory[i]["cycles"] or row["active"] != trajectory[i]["active"]:
            raise ValueError("progress disagrees with frozen trajectory")
    for row in invocations:
        window = rounds[row["round"]]
        if row["worker"] != row["partition"] % 4 or not (
                window["start"] <= row["start"] < row["end"] <= window["end"]):
            raise ValueError("invalid frontend assignment or invocation window")
    # These are completion offsets on overlapping pipelines, never additive attribution.
    endpoints = {name: 0 for name in ("adapter_last", "compute_last", "apply_done", "writeback_done",
                                     "status_done", "end", "tail_after_frontends")}
    workers = {str(w): {"adapter_last": 0, "compute_last": 0} for w in range(min(partitions, 4))}
    for row in rounds:
        start = row["start"]
        records = [r for r in invocations if r["round"] == row["round"]]
        for adapter, name in ((1, "adapter_last"), (0, "compute_last")):
            endpoints[name] += max(r["end"] for r in records if r["adapter"] == adapter) - start
            for worker, totals in workers.items():
                totals[name] += max(r["end"] for r in records
                                    if r["adapter"] == adapter and r["worker"] == int(worker)) - start
        for name in ("apply_done", "writeback_done", "status_done", "end"):
            endpoints[name] += row[name] - start
        endpoints["tail_after_frontends"] += row["end"] - max(r["end"] for r in records)
    total = observations["result"]["cycles"]
    if endpoints["end"] != total:
        raise ValueError("completion windows do not close")
    return {"rounds": len(rounds), "partitions": partitions, "completion_offset_cycles": endpoints,
        "completion_offset_fraction": {key: value / total for key, value in endpoints.items()},
        "worker_completion_offset_cycles": workers,
        "interpretation": "overlapping completion offsets, not exclusive stage attribution or stall causes"}


def load(directory, observations, partitions):
    rounds = read(directory / "rounds.csv", ROUND_FIELDS)
    invocations = read(directory / "invocations.csv", INVOCATION_FIELDS)
    return {"rounds": rounds, "invocations": invocations,
            "analysis": analyze(rounds, invocations, observations, partitions)}
