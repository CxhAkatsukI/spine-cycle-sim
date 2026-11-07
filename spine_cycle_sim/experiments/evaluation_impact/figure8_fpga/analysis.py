"""Check native timing sums and chronological batch conservation."""

import csv
from pathlib import Path


def records(text, prefix):
    rows = []
    for line in text.splitlines():
        if line.startswith(prefix + " "):
            fields = [token.split("=", 1) for token in line.split()[1:]]
            row = dict(fields)
            if len(row) != len(fields):
                raise ValueError("duplicate timing fields")
            rows.append(row)
    return rows


def timing(text, arm, case):
    prefix = "SPINE" if arm == "spine" else "GRASU"
    summary, = records(text, prefix + "_PERSISTENT_UPDATE")
    expected = dict(status="PASS", vertices=str(case["vertices"]),
                    initial_edges=str(case["initial_edges"]), logical_updates=str(case["updates"]),
                    batches=str(case["batches"]))
    if arm == "spine":
        expected["checked_edges"] = str(case["initial_edges"] + case["updates"])
    else:
        expected["pma_mismatches"] = "0"
    if any(summary.get(key) != value for key, value in expected.items()):
        raise ValueError("host did not validate the declared persistent update sequence")
    components = ("layout_ns", "bootstrap_ns" if arm == "spine" else "upload_ns",
                  "batch_ns", "update_wall_ns")
    result = {key: int(summary[key]) for key in (*components, "setup_inclusive_ns")}
    if (any(value < 0 for value in result.values()) or result["setup_inclusive_ns"] <= 0
            or sum(result[key] for key in components) != result["setup_inclusive_ns"]):
        raise ValueError("invalid setup-inclusive timing sum")
    batches = records(text, prefix + "_PERSISTENT_BATCH")
    if len(batches) != case["batches"]:
        raise ValueError("missing per-batch timing records")
    total, number = case["updates"], case["batches"]
    for index, batch in enumerate(batches):
        if (int(batch["batch"]) != index or int(batch["updates"]) !=
                ((index + 1) * total // number - index * total // number)):
            raise ValueError("batch order or update count changed")
    for key in ("batch_ns", "update_wall_ns"):
        if sum(int(batch[key]) for batch in batches) != result[key]:
            raise ValueError("per-batch timers do not sum to summary")
    if "physical_launches" in summary:
        launches = [int(batch.get("physical_launches", "0")) for batch in batches]
        if min(launches) <= 0 or sum(launches) != int(summary["physical_launches"]):
            raise ValueError("physical maintenance launches do not sum to summary")
        result["physical_launches"] = sum(launches)
    result["updates_per_second"] = total * 1e9 / result["setup_inclusive_ns"]
    return dict(result, raw_summary=summary)


def write_table(report, output):
    rows = []
    for case in report["cases"]:
        row = {key: case[key] for key in ("name", "dataset", "panel", "updates", "batches", "status")}
        row.update(samples_per_arm=1, warmups=0, speedup_gr_over_spine=case.get("speedup", ""))
        for arm, result in case["arms"].items():
            row[arm + "_status"] = result["status"]
            row[arm + "_error"] = result.get("error", "")
            for key, value in result.get("timing", {}).items():
                if key != "raw_summary":
                    row[arm + "_" + key] = value
        rows.append(row)
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with Path(output).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
