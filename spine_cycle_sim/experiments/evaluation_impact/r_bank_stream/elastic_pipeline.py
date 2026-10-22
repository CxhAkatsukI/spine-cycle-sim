"""Bounded full convergence, not a reader-floor substitute for R admission."""

import argparse
from functools import partial
import json
from pathlib import Path

from . import elastic_analysis, prefetch_convergence


def run(output, reference, before, cpus):
    frozen = json.loads(before.read_text())
    if (frozen.get("pins_unchanged") is not True or
            frozen.get("status") != "SOURCE_OVERLAP_COMPLETE_NOT_HARDWARE_ADMISSION"):
        raise ValueError("checked pre-edit complete source-overlap convergence required")
    return prefetch_convergence.run(output, reference, cpus, matrix=elastic_analysis.MATRIX,
        analyze=partial(elastic_analysis.summarize, before=frozen["r_rows"]), extra_references=(before,),
        complete_status="DUAL_ELASTIC_COMPLETE_NOT_HARDWARE_ADMISSION", prefetch_checks=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "reference", "before"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--cpus", type=int, nargs="+", required=True)
    args = parser.parse_args()
    print(json.dumps({"status": run(args.output.resolve(), args.reference.resolve(),
                                  args.before.resolve(), args.cpus)["status"]}))
