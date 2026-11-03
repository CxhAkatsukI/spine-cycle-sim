"""Replay raw timestamp envelopes; never select the fastest launch mode."""

import argparse
import csv
import json
from pathlib import Path
import statistics

from .runtime import identity, save


def records(path, prefix):
    return [json.loads(line[len(prefix):]) for line in Path(path).read_text().splitlines()
            if line.startswith(prefix)]


def envelope(events):
    if not events or any(e["end_ns"] <= e["start_ns"] for e in events):
        raise ValueError("missing or nonpositive timestamp interval")
    return max(e["end_ns"] for e in events) - min(e["start_ns"] for e in events)


def relocated(path, root):
    path = Path(path)
    return root / path.parent.name / path.name if root else path


def verify_log(pin, root=None):
    actual = identity(relocated(pin["path"], root))
    if any(actual[key] != pin[key] for key in ("bytes", "sha256")):
        raise ValueError("raw log identity changed")


def profiled_runs(row, raw_root=None):
    verify_log(row["stdout"], raw_root)
    verify_log(row["stderr"], raw_root)
    log = relocated(row["stdout"]["path"], raw_root)
    if row["stage"] == "R" and row["arm"] == "reference":
        root = relocated(row["result_directory"], raw_root)
        runs = []
        for repeat in range(4):
            mode = f"baseline_r{repeat}"
            if f"{mode} correctness PASS" not in Path(log).read_text().splitlines():
                raise ValueError("missing original-R full-buffer correctness pass")
            timing = json.loads((root / mode / "timing.json").read_text())
            if envelope(timing["events"]) != timing["event_span_ns"]:
                raise ValueError("original-R timestamp mismatch")
            runs.append({"repeat": repeat, "event_span_ns": timing["event_span_ns"],
                         "resident_wall_ms": timing["resident_wall_ms"]})
        return runs
    g = row["stage"] == "G"
    configs = records(log, "G_CONTROL_CONFIG " if g else "RETENTION_CONFIG ")
    if len(configs) != 1:
        raise ValueError("one configuration record required")
    config = configs[0]
    runs = records(log, "G_CONTROL_RESULT " if g else "RETENTION_RESULT ")
    events = records(log, "G_CONTROL_EVENT " if g else "RETENTION_EVENT ")
    if [r["repeat"] for r in runs] != list(range(4)):
        raise ValueError("cold plus exactly three warm results required")
    for result in runs:
        selected = [e for e in events if e["repeat"] == result["repeat"]]
        expected = config["shards"] * 9 if g else config["shards"] * 3 + 2
        keys = [(e["shard"], e["cu"]) if g else e["ordinal"] for e in selected]
        expected_keys = {(s, cu) for s in range(config["shards"]) for cu in range(9)} if g else set(range(expected))
        if len(selected) != expected or set(keys) != expected_keys:
            raise ValueError("missing or duplicate event")
        if not result["full_pma_pass" if g else "correctness"]:
            raise ValueError("state correctness failed")
        if envelope(selected) != result["event_span_ns"]:
            raise ValueError("timestamp envelope differs from reported total")
    if len(events) != sum(config["shards"] * 9 if g else config["shards"] * 3 + 2 for _ in runs):
        raise ValueError("events outside the declared repetitions")
    return runs


def summarize(reference, current):
    def warm(runs):
        return [r["event_span_ns"] / 1e6 for r in runs if r["repeat"] in (1, 2, 3)]
    a, b = warm(reference), warm(current)
    if len(a) != 3 or len(b) != 3:
        raise ValueError("three warm repeats per arm required")
    ratio = statistics.median(b) / statistics.median(a)
    return {"reference_ms": statistics.median(a), "current_ms": statistics.median(b),
            "reference_min_ms": min(a), "reference_max_ms": max(a),
            "current_min_ms": min(b), "current_max_ms": max(b),
            "current_over_reference": ratio, "slowdown_percent": (ratio - 1) * 100,
            "at_most_15_percent_slower": ratio <= 1.15}


def analyze(g_path, r_path, destination, raw_root=None):
    destination.mkdir(exist_ok=False)
    campaigns = {"G": json.loads(g_path.read_text()), "R": json.loads(r_path.read_text())}
    pairs, all_runs, unsupported = [], [], []
    declarations = [("G", f"AU-{batch}-{partition}", {"batch": batch, "partition": partition})
                    for batch in (1024, 131072) for partition in (524288, 65536)]
    declarations += [("R", case, {"case": case}) for case in ("boundary_ring", "skewed_sources", "amazon")]
    for stage, name, selector in declarations:
        selected = [r for r in campaigns[stage]["rows"] if r["stage"] == stage and
                    all(r.get(key) == value for key, value in selector.items())]
        if len(selected) == 1 and selected[0].get("status", "").startswith("UNSUPPORTED_"):
            unsupported.append({"stage": stage, "case": name, **selected[0]})
            continue
        arms = {}
        for arm in ("reference", "current"):
            rows = [r for r in selected if r["arm"] == arm]
            if len(rows) != 1:
                raise ValueError(f"missing or duplicated {stage}/{name}/{arm}")
            arms[arm] = profiled_runs(rows[0], raw_root)
            all_runs += [{"stage": stage, "case": name, "arm": arm, **run} for run in arms[arm]]
        pairs.append({"stage": stage, "case": name, **summarize(arms["reference"], arms["current"])})
    report = {"status": "MATCHED_ROWS_PASS" if all(p["at_most_15_percent_slower"] for p in pairs)
              else "PERFORMANCE_GATE_FAILED", "publication_match": False,
              "coverage_complete": not unsupported, "pairs": pairs, "unsupported": unsupported,
              "runs": all_runs, "input_reports": [identity(p) for p in (g_path, r_path)],
              "selection": "baseline only for original R; warm repeats 1,2,3; ratio of medians"}
    save(destination / "summary.json", report)
    for name, values in (("comparison.csv", pairs), ("repetitions.csv", all_runs)):
        fields = list(dict.fromkeys(key for row in values for key in row))
        with (destination / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(values)
    print(json.dumps({"status": report["status"], "pairs": pairs, "unsupported": unsupported}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--g-results", type=Path, required=True)
    parser.add_argument("--r-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-root", type=Path)
    args = parser.parse_args()
    analyze(args.g_results, args.r_results, args.output, args.raw_root)
