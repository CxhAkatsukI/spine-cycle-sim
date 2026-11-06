"""Export all crossover samples, retained failures, and empirical crossings."""

import argparse
import csv
import json
from pathlib import Path
import statistics
import tarfile

from ...original_regraph_execution.hardware.source_retention.runtime import identity, save
from .input_archive import archive_updates


def crossings(points):
    brackets = []
    usable = sorted((point for point in points if point["status"] == "MEASURED"
                     and point["kind"] != "ordinary" and point["changed_fraction"] > 0),
                    key=lambda point: point["changed_fraction"])
    for left, right in zip(usable, usable[1:]):
        if (left["speedup"] - 1) * (right["speedup"] - 1) < 0:
            brackets.append(dict(left=left["name"], right=right["name"],
                                 changed_fraction_bounds=[left["changed_fraction"], right["changed_fraction"]]))
    return brackets


def write_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def export(campaigns, output):
    output.mkdir(parents=True, exist_ok=False)
    points, samples, studies, raw, manifests = [], [], [], {}, []
    for index, path in enumerate(campaigns):
        document = json.loads(path.read_text())
        manifest_path = Path(document["workloads"]["path"])
        manifest = json.loads(manifest_path.read_text())
        manifests.append(manifest)
        group = dict(campaign=index, algorithm=manifest["algorithm"], dataset=manifest["dataset"])
        current = []
        for point in document["cases"]:
            row = dict(group, name=point["name"], kind=point["kind"], status=point["status"],
                       updates=point["updates"], vertices=manifest["vertices"],
                       changed_vertices=point["changed_vertices"], changed_fraction=point["changed_fraction"],
                       target_fraction=point.get("target_fraction"), epsilon=manifest.get("epsilon"),
                       target_reached=point.get("target_reached"), initial_active=point.get("initial_active"),
                       speedup=point.get("speedup"), **{name + "_wall_ms": value for name, value
                       in point.get("medians_ms", {}).items()})
            measured = [sample["pair"] for sample in point["samples"]
                        if not sample["warmup"] and sample.get("status") == "PASS"]
            row["measured_pair_count"] = len(measured)
            if measured:
                ratios = [pair["gr_wall_ms"] / pair["spine_wall_ms"] for pair in measured]
                row.update(paired_speedup_min=min(ratios), paired_speedup_max=max(ratios))
                for arm in ("spine", "gr"):
                    values = [pair[arm + "_wall_ms"] for pair in measured]
                    row[arm + "_wall_cv_fraction"] = statistics.pstdev(values) / statistics.mean(values)
            current.append(row)
            for sample in point["samples"]:
                detail = dict(group, name=point["name"], sample=sample["sample_index"],
                              warmup=sample["warmup"], order=",".join(sample["order"]),
                              status=sample.get("status", "INCOMPLETE"), error=sample.get("error"))
                detail.update(sample.get("pair", {}))
                for arm, counters in sample.get("counters", {}).items():
                    for key in ("processed_edges", "source_requests"):
                        detail[arm + "_" + key] = counters.get(key)
                    for prefix, records in counters.get("timing_records", {}).items():
                        if len(records) == 1:
                            for key, value in records[0].items():
                                if key.endswith("_ms"):
                                    detail[f"{arm}_{prefix}_{key}"] = float(value)
                samples.append(detail)
                for arm, result in sample["arms"].items():
                    for key in ("stdout", "stderr"):
                        raw[f"campaign-{index}/{point['name']}/sample-{sample['sample_index']}/{arm}.{key}.txt"] = result[key]["path"]
                # Failed arms can raise before their result is added to the journal.
                folder = path.parent / point["name"] / f"sample-{sample['sample_index']}"
                for pattern in ("*.stdout.txt", "*.stderr.txt", "*.json"):
                    for artifact in folder.glob(pattern):
                        name = f"campaign-{index}/{point['name']}/sample-{sample['sample_index']}/{artifact.name}"
                        raw[name] = str(artifact)
        points.extend(current)
        studies.append(dict(group, status=document["status"], error=document.get("error"),
                            source=identity(path), workloads=identity(manifest_path),
                            hardware_limitation=document.get("hardware_limitation"),
                            crossover_brackets=crossings(current)))
        save(output / f"campaign-{index}.json", document)
        save(output / f"workloads-{index}.json", manifest)
    write_csv(output / "points.csv", points)
    write_csv(output / "samples.csv", samples)
    with tarfile.open(output / "host-logs.tar.gz", "w:gz") as archive:
        for name, path in sorted(raw.items()):
            archive.add(path, arcname=name, recursive=False)
    archive_updates(manifests, output / "updates.tar.gz")
    result = dict(studies=studies, points=points, total_samples=len(samples),
                  measured_points=sum(row["status"] == "MEASURED" for row in points),
                  method="ratio_of_median_wall_times; warmup_excluded; three_measured_pairs",
                  crossings="adjacent measured sign-change brackets, not interpolated exact thresholds",
                  analysis=identity(__file__))
    result["crossovers"] = [dict(dataset=dataset, algorithm=algorithm, brackets=crossings(
        [row for row in points if (row["dataset"], row["algorithm"]) == (dataset, algorithm)]))
        for dataset, algorithm in sorted({(row["dataset"], row["algorithm"]) for row in points})]
    save(output / "summary.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = export(args.campaign, args.output)
    print(result["measured_points"], "measured points;", result["total_samples"], "samples")


if __name__ == "__main__":
    main()
