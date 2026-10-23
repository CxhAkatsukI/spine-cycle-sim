"""Whole-parent refill on the unchanged finite addressed R architecture."""

import argparse
from functools import partial
import json
from pathlib import Path

from . import elastic_analysis, prefetch_convergence, ready_bursts

ARMS = ("a4_io16", "prefetch_ready_bursts", "prefetch_ready_fullburst")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]
MASTERS = dict(zip(ARMS, (13, 16, 16)))


def summarize(rows, reference, *, before):
    return elastic_analysis.summarize(rows, reference, before=before, arms=ARMS,
        before_matrix=ready_bursts.MATRIX, physical_masters=MASTERS,
        reduction_key="cycle_reduction_from_available_space_refill")


def run(output, reference, before, freeze, cpus):
    frozen = json.loads(before.read_text())
    if (frozen.get("pins_unchanged") is not True or
            frozen.get("status") != "READY_BURSTS_COMPLETE_SIMULATOR_PREDICTION"):
        raise ValueError("checked pre-edit complete ready-burst convergence required")
    return prefetch_convergence.run(output, reference, cpus, matrix=MATRIX,
        analyze=partial(summarize, before=frozen["r_rows"]), extra_references=(before, freeze),
        complete_status="READY_FULLBURST_COMPLETE_SIMULATOR_PREDICTION", prefetch_checks=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "reference", "before", "freeze"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cpus", type=int, nargs="+", required=True)
    args = parser.parse_args()
    print(json.dumps({"status": run(args.output.resolve(), args.reference.resolve(),
        args.before.resolve(), args.freeze.resolve(), args.cpus)["status"]}))
