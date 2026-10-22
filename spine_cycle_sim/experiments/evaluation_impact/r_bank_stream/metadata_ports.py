"""Separate directory/even/odd physical masters; full R, not a scan floor."""

import argparse
from functools import partial
import json
from pathlib import Path

from . import elastic_analysis, prefetch_convergence

ARMS = ("a4_io16", "prefetch_dual_elastic", "prefetch_triple_elastic")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]
MASTERS = dict(zip(ARMS, (13, 11, 15)))


def summarize(rows, reference, *, before):
    return elastic_analysis.summarize(rows, reference, before=before, arms=ARMS,
        before_matrix=elastic_analysis.MATRIX, physical_masters=MASTERS,
        reduction_key="cycle_reduction_from_dual")


def run(output, reference, before, freeze, cpus):
    frozen = json.loads(before.read_text())
    if (frozen.get("pins_unchanged") is not True or
            frozen.get("status") != "DUAL_ELASTIC_COMPLETE_NOT_HARDWARE_ADMISSION"):
        raise ValueError("checked pre-edit complete dual-elastic convergence required")
    return prefetch_convergence.run(output, reference, cpus, matrix=MATRIX,
        analyze=partial(summarize, before=frozen["r_rows"]), extra_references=(before, freeze),
        complete_status="METADATA_PORTS_COMPLETE_NOT_HARDWARE_ADMISSION", prefetch_checks=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "reference", "before", "freeze"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cpus", type=int, nargs="+", required=True)
    args = parser.parse_args()
    print(json.dumps({"status": run(args.output.resolve(), args.reference.resolve(),
        args.before.resolve(), args.freeze.resolve(), args.cpus)["status"]}))
