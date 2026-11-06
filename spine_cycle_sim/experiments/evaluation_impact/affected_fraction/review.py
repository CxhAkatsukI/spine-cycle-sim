"""Check a completed portable handoff independently of its board runner."""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics
import tarfile


def check_point(point, log_hashes, campaign):
    if point["status"] != "MEASURED":
        raise ValueError("primary point is not measured: " + point["name"])
    samples = point["samples"]
    if [sample["sample_index"] for sample in samples] != [0, 1, 2, 3]:
        raise ValueError("expected one warmup and three measured pairs")
    clocks, memory_peaks, available = set(), [], []
    for index, sample in enumerate(samples):
        order = ["spine", "gr"] if index % 2 == 0 else ["gr", "spine"]
        if (sample["warmup"] != (index == 0) or sample["status"] != "PASS"
                or sample["order"] != order):
            raise ValueError("sample status, warmup or alternating order differs")
        pair_clocks = []
        for arm in ("spine", "gr"):
            result = sample["arms"][arm]
            pair_clocks.append(tuple(result["clock"]["driver_reported_mhz"]))
            for stream in ("stdout", "stderr"):
                name = f"campaign-{campaign}/{point['name']}/sample-{index}/{arm}.{stream}.txt"
                if log_hashes.get(name) != result[stream]["sha256"]:
                    raise ValueError("raw log missing or changed: " + name)
            guard = result["memory_guard"]
            if guard["status"] != "COMPLETED":
                raise ValueError("memory guard did not complete")
            available.append(guard["minimum_effective_available_bytes"])
            memory_peaks.append(int(result["cgroup_after"]["memory.peak"]))
            before, after = (dict(line.split() for line in result[key]["memory.events"].splitlines())
                             for key in ("cgroup_before", "cgroup_after"))
            if any(int(after[key]) > int(before[key]) for key in ("oom", "oom_kill", "oom_group_kill")):
                raise ValueError("OOM event occurred during an arm")
        if pair_clocks[0] != pair_clocks[1]:
            raise ValueError("paired clocks differ")
        clocks.add(pair_clocks[0])
    medians = {arm: statistics.median(sample["pair"][arm + "_wall_ms"] for sample in samples[1:])
               for arm in ("spine", "gr")}
    if any(not math.isclose(value, point["medians_ms"][arm], rel_tol=1e-12)
           for arm, value in medians.items()):
        raise ValueError("median does not match raw pairs")
    if not math.isclose(point["speedup"], medians["gr"] / medians["spine"], rel_tol=1e-12):
        raise ValueError("speedup does not match wall medians")
    return dict(clocks=sorted(clocks), peak_memory_bytes=max(memory_peaks),
                minimum_effective_available_bytes=min(available))


def review(root):
    delivery = json.loads((root / "delivery.json").read_text())
    if delivery["status"] != "COMPLETED":
        raise ValueError("delivery is not complete")
    for name, record in delivery["files"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("delivery file changed: " + name)
    with tarfile.open(root / "data/host-logs.tar.gz") as archive:
        log_hashes = {member.name: hashlib.sha256(archive.extractfile(member).read()).hexdigest()
                      for member in archive.getmembers() if member.isfile()}
    points, reports = [], []
    for index, study in enumerate(delivery["studies"]):
        campaign = json.loads((root / f"data/campaign-{index}.json").read_text())
        manifest = json.loads((root / f"data/workloads-{index}.json").read_text())
        expected = {point["name"] for point in manifest["points"]}
        actual = [point["name"] for point in campaign["cases"]]
        if (campaign["status"] != "COMPLETED" or set(actual) != expected
                or len(actual) != len(expected)):
            raise ValueError("campaign does not contain every planned point exactly once")
        checks = [check_point(point, log_hashes, index) for point in campaign["cases"]]
        reports.append(dict(algorithm=study["algorithm"], dataset=study["dataset"],
                            points=len(checks), clocks=sorted({tuple(clock) for check in checks
                                                            for clock in check["clocks"]}),
                            peak_memory_bytes=max(check["peak_memory_bytes"] for check in checks),
                            minimum_effective_available_bytes=min(
                                check["minimum_effective_available_bytes"] for check in checks)))
        points.extend((index, point) for point in campaign["cases"])
    with (root / "data/points.csv").open() as stream:
        csv_points = {(int(row["campaign"]), row["name"]): row for row in csv.DictReader(stream)}
    for index, point in points:
        row = csv_points[(index, point["name"])]
        if (row["status"] != "MEASURED" or int(row["measured_pair_count"]) != 3
                or not math.isclose(float(row["speedup"]), point["speedup"], rel_tol=1e-12)):
            raise ValueError("CSV differs from campaign pairs")
    with (root / "data/samples.csv").open() as stream:
        exported = list(csv.DictReader(stream))
    primary = [row for row in exported if int(row["campaign"]) < len(reports)]
    if len(primary) != len(points) * 4 or any(row["status"] != "PASS" for row in primary):
        raise ValueError("sample CSV is incomplete")
    return dict(status="PASS", primary_points=len(points), primary_pairs=len(primary),
                measured_pairs=len(points) * 3, warmup_pairs=len(points), studies=reports,
                retained_other_pairs=len(exported) - len(primary),
                scope="archived protocol, clocks, logs, medians, completeness and OOM receipts; "
                      "CPU correctness was checked by each host and the frozen board comparator")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = review(args.handoff)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(result["status"], result["primary_points"], "points;", result["measured_pairs"], "measured pairs")


if __name__ == "__main__":
    main()
