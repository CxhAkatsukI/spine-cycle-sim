"""Run the read-only diagnostic matrix using the shared bounded executor."""

import argparse
from pathlib import Path

from ..cached_hot.study import metadata
from ..runner import Study, run as execute_study
from .analysis import analyze
from .preparation import matrix, prepare


def run(output, core_build, previous):
    settings = metadata()
    settings.update(diagnostic_scope="all 19 cases, both latencies, original_forwarded/cached_hot/cached_hot64",
        assumptions=["fixed preceding model timing/resources, including original pending-value forwarding",
            "per-cycle observations do not change scheduling, queue capacity or memory requests"],
        diagnostic_markers="after commit; hot completion is retired cache write; write start is first backend write beat",
        diagnostic_limitations=["overlapping markers are not additive stage durations",
            "metadata full fractions use per-port cycle denominators, not equal master counts",
            "cold retirement markers are not available; complete final cold ledger remains checked",
            "these are simulator observations, not FPGA counters or timing calibration"])
    return execute_study(output, core_build, previous, Study("g_search_diagnostics", matrix, prepare,
        analyze, settings, "G_READ_ONLY_DIAGNOSTICS_EXACT_REPLAY", ("exact_replayed_rows",), True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "core-build", "previous"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve(), args.core_build.resolve(), args.previous.resolve())
