"""Finite 512-line PMA rings on the unchanged ready/full-burst R path."""

import argparse
from functools import partial
import json
from pathlib import Path

from . import elastic_analysis, prefetch_convergence, ready_fullburst

ARMS = ("a4_io16", "prefetch_ready_fullburst", "prefetch_ready_capacity512")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]
MASTERS = dict(zip(ARMS, (13, 16, 16)))
ADDED_DATA_BYTES = 4 * 2 * (512 - 256) * 64


def summarize(rows, reference, *, before):
    result = elastic_analysis.summarize(rows, reference, before=before, arms=ARMS,
        before_matrix=ready_fullburst.MATRIX, physical_masters=MASTERS,
        reduction_key="cycle_reduction_from_256_line_rings")
    result["added_ring_data_bytes"] = ADDED_DATA_BYTES
    return result


def run(output, reference, before, freeze, cpus):
    frozen = json.loads(before.read_text())
    if (frozen.get("pins_unchanged") is not True or
            frozen.get("status") != "READY_FULLBURST_COMPLETE_SIMULATOR_PREDICTION"):
        raise ValueError("checked pre-edit complete full-burst convergence required")
    return prefetch_convergence.run(output, reference, cpus, matrix=MATRIX,
        analyze=partial(summarize, before=frozen["r_rows"]), extra_references=(before, freeze),
        complete_status="PREFETCH_CAPACITY_COMPLETE_SIMULATOR_PREDICTION", prefetch_checks=True,
        extra_input_checks={"PREFETCH_CAPACITY_TEST": 16})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "reference", "before", "freeze"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cpus", type=int, nargs="+", required=True)
    args = parser.parse_args()
    print(json.dumps({"status": run(args.output.resolve(), args.reference.resolve(),
        args.before.resolve(), args.freeze.resolve(), args.cpus)["status"]}))
