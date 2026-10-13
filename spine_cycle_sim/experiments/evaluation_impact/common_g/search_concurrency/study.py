"""Run context controls with the shared serial, finite, fixed-binary executor."""

import argparse
from pathlib import Path

from ..cached_hot.study import metadata
from ..runner import Study, run as execute_study
from .analysis import analyze
from .preparation import matrix, prepare


def run(output, core_build, previous):
    settings = metadata()
    settings.update(search_contexts_per_cu={"cached_hot": 16, "cached_hot64": 64,
        "original": 64, "original_forwarded": 64},
        assumptions=["original_forwarded alone forwards pending same-row cache values at unchanged II=3 and latency=7",
            "cached_hot64 changes contexts only; masters, physical banks, credits and cache transfers unchanged",
            "original source has eight metadata AXI masters per CU; compact candidate has one shared metadata master per CU",
            "original/reference and candidate are not resource-identical or hardware-timing admitted",
            "no integrated 64-context HLS or new routed FPGA evidence"],
        safety={"serial": True, "process_limit_gib": 1, "reserve_gib": 8,
            "basis": "prior complete 190-row cached matrix peak process RSS 231296 KiB"})
    return execute_study(output, core_build, previous, Study(
        "g_search_concurrency", matrix, prepare, analyze, settings,
        "G_SEARCH_CONCURRENCY_VALIDATED_REFERENCE_TIMING_OPEN",
        ("old_checkpoint_exact_rows", "forwarded_reference_no_more_than_ten_percent_slower",
         "forwarded_reference_within_ten_percent_both_directions")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("output", "core-build", "previous"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve(), args.core_build.resolve(), args.previous.resolve())
