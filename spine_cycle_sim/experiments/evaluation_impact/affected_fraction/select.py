"""Select PR points using CPU spread only, before observing FPGA latency."""

import argparse
import json
import math
from pathlib import Path

from ...original_regraph_execution.hardware.source_retention.runtime import identity, save
from .sssp import TARGETS


def select(manifests, output):
    documents = [json.loads(path.read_text()) for path in manifests]
    first = documents[0]
    for document in documents:
        for key in ("algorithm", "vertices", "edges", "original", "epsilon"):
            if document[key] != first[key]:
                raise ValueError("PR candidate sets use different inputs or semantics")
    candidates = [row for document in documents for row in document["points"]]
    positive = [row for row in candidates if row["kind"] != "ordinary" and row["changed_fraction"] > 0]
    if not positive:
        raise ValueError("no positive-spread PR candidate")
    chosen = {}
    for target in TARGETS:
        row = min(positive, key=lambda row: (abs(math.log(row["changed_fraction"] / target)), row["name"]))
        chosen.setdefault(row["name"], dict(row, selected_for_targets=[]))["selected_for_targets"].append(target)
    for row in candidates:
        if row["kind"] == "ordinary" or row["changed_fraction"] == 0 and not any(
                previous["changed_fraction"] == 0 for previous in chosen.values()):
            chosen.setdefault(row["name"], row)
    manifest = dict(first, points=sorted(chosen.values(), key=lambda row: row["name"]),
                    selection=dict(rule="closest_log_actual_fraction_for_each_target_plus_ordinary_and_one_zero",
                                   uses_hardware_timings=False, sources=[identity(path) for path in manifests],
                                   selector=identity(__file__)))
    save(output, manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("selection output already exists")
    select(args.manifest, args.output)


if __name__ == "__main__":
    main()
