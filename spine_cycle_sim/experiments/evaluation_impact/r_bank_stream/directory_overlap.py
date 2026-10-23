"""Test bounded directory lookahead without changing memory service or ports."""

import argparse
from functools import partial
import json
from pathlib import Path

from . import apply_ports, elastic_analysis, prefetch_convergence

ARMS = ("a4_io16", "prefetch_triple_split_apply", "prefetch_directory_lookahead")
MATRIX = [(latency, reverse, arm) for latency in (64, 128)
          for reverse in (0, 1) for arm in ARMS]
MASTERS = dict(zip(ARMS, (13, 16, 16)))


def check_traffic(result, before):
    for field in ("read_bytes", "write_bytes"):
        if type(result.get(field)) is not int:
            raise ValueError("integer physical traffic required")
    extra = result["read_bytes"] - before["read_bytes"]
    # At most one extra 8-KiB tile per frontend per round can be prefetched
    # beyond the previous stop point. Every such beat is still paid and drained.
    if (extra < 0 or extra % 64 or extra > result["rounds"] * 4 * 8192 or
            result["write_bytes"] != before["write_bytes"]):
        raise ValueError("lookahead dropped work or exceeded its finite prefetch bound")


def summarize(rows, reference, *, before):
    result = elastic_analysis.summarize(rows, reference, before=before, arms=ARMS,
        before_matrix=apply_ports.MATRIX, physical_masters=MASTERS,
        reduction_key="cycle_reduction_from_single_directory", candidate_traffic=check_traffic)
    result["added_directory_value_bytes"] = 4 * 8192
    for comparison in result["comparisons"]:
        values = comparison["arms"]
        comparison["extra_directory_read_bytes"] = (
            values[ARMS[2]]["read_bytes"] - values[ARMS[1]]["read_bytes"])
    return result


def run(output, reference, before, freeze, cpus):
    frozen = json.loads(before.read_text())
    if (frozen.get("pins_unchanged") is not True or
            frozen.get("status") != "APPLY_PORTS_COMPLETE_NOT_HARDWARE_ADMISSION"):
        raise ValueError("checked pre-edit complete split-Apply convergence required")
    return prefetch_convergence.run(output, reference, cpus, matrix=MATRIX,
        analyze=partial(summarize, before=frozen["r_rows"]), extra_references=(before, freeze),
        complete_status="DIRECTORY_OVERLAP_COMPLETE_SIMULATOR_PREDICTION", prefetch_checks=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "reference", "before", "freeze"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cpus", type=int, nargs="+", required=True)
    args = parser.parse_args()
    print(json.dumps({"status": run(args.output.resolve(), args.reference.resolve(),
        args.before.resolve(), args.freeze.resolve(), args.cpus)["status"]}))
