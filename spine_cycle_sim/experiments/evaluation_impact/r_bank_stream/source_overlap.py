"""Fresh core and full convergence for an independent source-cache loader."""

import argparse
from functools import partial
import json
from pathlib import Path

from . import prefetch_convergence
from .source_overlap_analysis import MATRIX, summarize


def run(output, reference, before, cpus):
    frozen = json.loads(before.read_text())
    if (frozen.get("pins_unchanged") is not True or
            frozen.get("status") != "COMPACT_CONVERGENCE_COMPLETE_NOT_HARDWARE_ADMISSION"):
        raise ValueError("checked pre-edit complete compact convergence required")
    return prefetch_convergence.run(output, reference, cpus, matrix=MATRIX,
        analyze=partial(summarize, before=frozen["r_rows"]), extra_references=(before,),
        complete_status="SOURCE_OVERLAP_COMPLETE_NOT_HARDWARE_ADMISSION")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--cpus", type=int, nargs="+", required=True)
    args = parser.parse_args()
    print(json.dumps({"status": run(args.output.resolve(), args.reference.resolve(),
                                  args.before.resolve(), args.cpus)["status"]}))
