"""Run declared metadata-only credits with unchanged physical bank capacity."""

import argparse
from pathlib import Path

from ..cached_hot.study import metadata
from ..runner import Study, run as execute_study
from .analysis import analyze
from .preparation import CREDITS, matrix, prepare


def run(output, core_build, previous):
    settings = metadata()
    settings.update(metadata_credits_per_master=CREDITS, metadata_masters_per_cu=1,
        new_arm_contexts_per_cu=64,
        assumptions=["four original-source metadata port pairs per CU remain distinct from one candidate master",
            "only new-arm metadata parent, burst, request/response FIFO and reorder budgets increase",
            "physical-bank credits remain 32; issue/response bandwidth remains one beat per cycle per master",
            "original pending-value forwarding and hot-cache II=3, latency=7 are unchanged",
            "buffering must be implemented and checked in HLS before any routed baseline promotion"],
        safety={"serial": True, "process_limit_gib": 1, "reserve_gib": 8,
            "basis": "preceding diagnostic matrix peaks at 341672 KiB process RSS"})
    return execute_study(output, core_build, previous, Study("g_metadata_credits", matrix, prepare,
        analyze, settings, "G_METADATA_CREDIT_PREDICTIONS_VALIDATED",
        ("exact_replayed_rows", "no_more_than_ten_percent_slower", "within_ten_percent_both_directions"), True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "core-build", "previous"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve(), args.core_build.resolve(), args.previous.resolve())
