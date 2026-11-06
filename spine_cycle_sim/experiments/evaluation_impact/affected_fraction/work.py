"""Export available in-window work records without inventing missing counters."""

import argparse
import json
from pathlib import Path
import tarfile

from .analyze import write_csv


PREFIXES = {
    "KERNEL_PAIR_RESULT", "SPINE_RESIDENT_BENCHMARK_PASS", "CC_UPDATE_PASS", "CC_RESIDENT_WALL",
    "WEIGHTED_PMA_NATIVE_SHARDED_RESULT", "WEIGHTED_PMA_NATIVE_SHARDED_TIMING",
    "CC_PMA_NATIVE_SHARDED_RESULT", "CC_PMA_NATIVE_SHARDED_TIMING",
    "RESIDUAL_PR_PMA_NATIVE_SHARDED_RESULT", "RESIDUAL_PR_PMA_NATIVE_SHARDED_TIMING",
    "SHARDED_RESIDENT_BATCH_WALL",
}


def records(text):
    result = []
    for line in text.splitlines():
        tokens = line.split()
        if not tokens or tokens[0] not in PREFIXES:
            continue
        fields = {}
        for token in tokens[1:]:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            if key in fields:
                raise ValueError("duplicate log field: " + key)
            fields[key] = value
        result.append(dict(record=tokens[0], fields=fields))
    return result


def export(root, output):
    output.mkdir(parents=True, exist_ok=False)
    summary = json.loads((root / "data/summary.json").read_text())
    rows = []
    with tarfile.open(root / "data/host-logs.tar.gz") as archive:
        for study in summary["studies"]:
            index = study["campaign"]
            campaign = json.loads((root / f"data/campaign-{index}.json").read_text())
            for point in campaign["cases"]:
                for sample in point["samples"]:
                    for arm in sample["arms"]:
                        name = f"campaign-{index}/{point['name']}/sample-{sample['sample_index']}/{arm}.stdout.txt"
                        text = archive.extractfile(name).read().decode()
                        for ordinal, record in enumerate(records(text)):
                            row = dict(campaign=index, dataset=study["dataset"], algorithm=study["algorithm"],
                                       name=point["name"], sample=sample["sample_index"],
                                       warmup=sample["warmup"], status=sample.get("status", "INCOMPLETE"),
                                       arm=arm, record=record["record"], ordinal=ordinal)
                            row.update({"log_" + key: value for key, value in record["fields"].items()})
                            rows.append(row)
    write_csv(output / "records.csv", rows)
    report = dict(records=len(rows), source="archived host stdout; original field names prefixed log_",
                  excludes="bootstrap/pre-update work; no timing subtraction or missing-counter imputation",
                  semantics={
                      "KERNEL_PAIR_RESULT": "one Spine propagation round; processed_edges and source_requests are work counts",
                      "CC_UPDATE_PASS": "one complete Spine CC update; physical_edges/row_queries/vertex_visits are distinct work counts",
                      "SHARDED_RESULT": "G+R result; processed_edge_slots_per_superstep is a layout count, not measured AXI bytes",
                      "TIMING": "available host/event fields; overlapping component durations are not additive host time"})
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("handoff", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = export(args.handoff, args.output)
    print(result["records"], "archived work/timing records")


if __name__ == "__main__":
    main()
