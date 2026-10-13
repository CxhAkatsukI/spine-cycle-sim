"""Run complete cached-G controls with fixed low-memory serial admission."""

import argparse
from pathlib import Path

from ..runner import Study, run as execute_study
from .analysis import analyze
from .preparation import matrix, prepare


def metadata():
    return {"timing_kind": "declared_prediction",
        "hardware_timing_admitted": False, "publication_match_admitted": False,
        "production_baseline_admitted": False, "reference_cache_timing_admitted": False,
        "boundary": "prepared resident single window, cache preload through all cold/cache write acknowledgements and memory drain",
        "clock_mhz": 200, "banks": 4, "bank_credits": 32,
        "hot_cache_halves": 2, "hot_cache_bytes_per_half": 131072 * 64,
        "banks_per_half": 16, "bank_queue_depth": 2, "bank_pipeline_entries": 3,
        "bank_interval_cycles": 3, "bank_latency_cycles": 7,
        "assumptions": ["logical same-row forwarding in each finite bank pipeline",
            "isolated original/source16 RTL II=3 is not integrated-G clock calibration",
            "legacy original model blocks same-row input until retirement; reference correction remains open"],
        "safety": {"serial": True, "process_limit_gib": 1, "reserve_gib": 8,
            "basis": "previous identical-size 152-run study peak process RSS 342244 KiB; heavy HLS/routing thresholds unchanged"}}


def run(output, core_build, previous):
    return execute_study(output, core_build, previous, Study(
        "cached_g", matrix, prepare, analyze, metadata(),
        "CACHED_G_PREDICTION_VALIDATED_REFERENCE_TIMING_OPEN",
        ("old_checkpoint_exact_rows", "legacy_reference_no_more_than_ten_percent_slower",
         "legacy_reference_within_ten_percent_both_directions")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("output", "core-build", "previous"):
        parser.add_argument("--" + key, type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve(), args.core_build.resolve(), args.previous.resolve())
