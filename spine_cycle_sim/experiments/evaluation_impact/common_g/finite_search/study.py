"""Run finite 8x8 G search with unchanged bank/cache assumptions and all controls."""

import argparse
from pathlib import Path

from ..cached_hot.study import metadata
from ..metadata_credits.preparation import CREDITS
from ..runner import Study, run as execute_study
from .analysis import analyze
from .preparation import ARM, GEOMETRY, matrix, prepare


def settings():
    result = metadata()
    result.update(finite_search_geometry=GEOMETRY,
        metadata_credits_per_master={**CREDITS, ARM: 32},
        metadata_masters_per_cu=1, new_arm_contexts_per_cu=64,
        assumptions=["all finite transport stages use one registered cycle and II=1, not measured HLS schedules",
            "64 dependent search workers use bounded lane credits and strict ordered publication",
            "8x8 request arbitration and 8x8 response routing include all 339 finite HLS channels and end tokens",
            "16 update and 32 metadata response slots hold out-of-order arrivals; issue-order publication is registered and retains credits",
            "response slots add 3120 payload/valid bits and metadata lane tags add 192 bits per CU, excluding other control/adapter storage",
            "original eight metadata masters per CU versus candidate one remain a resource difference",
            "bank/cache latency, bandwidth, forwarding and work are unchanged; no timing multiplier",
            "whole-G HLS resources, clock and original-publication timing remain unadmitted"])
    return result


def run(output, core_build, previous):
    return execute_study(output, core_build, previous, Study("g_finite_search", matrix, prepare,
        analyze, settings(), "G_FINITE_SEARCH_PREDICTIONS_CHECKED",
        ("exact_replayed_rows", "no_more_than_ten_percent_slower", "within_ten_percent_both_directions"), True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "core-build", "previous"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve(), args.core_build.resolve(), args.previous.resolve())
