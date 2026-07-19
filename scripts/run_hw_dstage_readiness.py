#!/usr/bin/env python3
"""Run built-in HW D-stage timing matrices."""

from __future__ import annotations

import argparse
import csv
import json
import shlex
import statistics
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.calibration.maintenance import (  # noqa: E402
    DEFAULT_XRT_SETUP,
    KEY_VALUE_RE,
)

DEFAULT_XCLBIN = (
    "/data/feiyang/spine-dynamic-graph-builds/"
    "stream_sparse_carry_cursors_local_20260716_160954/"
    "compact_validation_20260717/hw_134_routed_accepted/xclbin/"
    "spine_partitioned_split_e2e.hw.xclbin"
)
DEFAULT_HOST_EXE = (
    "/home/chuxiao/spine-dynamic-graph-reduce-levels/tests/test_integration/"
    "host_partitioned_csr_e2e_smoke"
)

BASE_FIELDS = [
    "case",
    "sweep",
    "repeat",
    "returncode",
    "status",
    "tile_schedule_entries",
    "batch_event_entries",
    "stdout_log",
    "stderr_log",
    "command_log",
    "command",
]

SUMMARY_FIELDS = [
    "case",
    "sweep",
    "repeats",
    "successful_repeats",
    "median_conv_ms",
    "min_conv_ms",
    "max_conv_ms",
    "conv_ms_jitter_pct",
    "median_reader_ms",
    "median_conv_span_ms",
    "median_maint_ms",
    "median_kernel_e2e_ms",
    "median_input_edges",
    "median_persisted",
    "median_batches",
    "median_target_level",
    "median_active_sources",
    "median_active_records",
    "median_active_record_replays",
    "median_touched_tiles",
    "median_marked_tiles",
    "median_nonempty_tiles",
    "median_empty_tile_passes",
    "median_fallback_used",
    "median_row_lookups",
    "median_clipped_ranges",
]

TILE_SCHEDULE_FIELDS = [
    "case",
    "sweep",
    "repeat",
    "partition",
    "tile",
    "tile_begin",
    "tile_end",
    "tile_size",
    "tile_work",
    "path",
    "fallback_used",
    "nonempty",
    "clipped_ranges",
    "gathered_vertex_words",
    "swept_vertex_words",
    "scattered_vertex_words",
]

BATCH_EVENT_FIELDS = [
    "case",
    "sweep",
    "repeat",
    "batch",
    "input_edges",
    "target_level",
    "consumed_mask",
    "persisted",
    "overflow",
    "l0_partitions_written",
    "l0_pages_epoch_stamped",
    "l0_full_clear_fallbacks",
    "l0_epoch_wrap_events",
    "maint_ms",
]


@dataclass(frozen=True)
class DStageCase:
    case: str
    sweep: str
    args: tuple[str, ...]
    purpose: str


def default_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            case="tiny_default",
            sweep="tiny",
            args=(),
            purpose="Minimal graph; exposes fixed CONV overhead and small-counter path.",
        ),
        DStageCase(
            case="star_e512",
            sweep="single_source_fanout",
            args=("--star", "512"),
            purpose="One active source with moderate fanout across partitions.",
        ),
        DStageCase(
            case="fanout_e4096_s64",
            sweep="multi_source_fanout",
            args=("--fanout", "4096", "64"),
            purpose="Many active sources with a larger edge stream.",
        ),
        DStageCase(
            case="repeat_fanout_e512_b3_s64",
            sweep="multi_batch_level_state",
            args=("--repeat-fanout", "512", "3", "64"),
            purpose="Multiple update batches before CONV; checks level-state exposure.",
        ),
        DStageCase(
            case="fallback_forced",
            sweep="full_path_tile",
            args=("--fallback-forced",),
            purpose="Forces the non-tiny tile path and broader tile scheduling counters.",
        ),
    ]


def phase3a1_calibration_matrix() -> list[DStageCase]:
    return [
        DStageCase("calib_tiny_default", "tiny", (), "Small fixed-overhead case."),
        DStageCase(
            "calib_sparse_wide",
            "tiny_wide_tiles",
            ("--sparse-wide",),
            "Few edges touching distant tiles.",
        ),
        DStageCase(
            "calib_star_e128",
            "single_source_fanout",
            ("--star", "128"),
            "Single active source, small fanout.",
        ),
        DStageCase(
            "calib_star_e512",
            "single_source_fanout",
            ("--star", "512"),
            "Single active source, medium fanout.",
        ),
        DStageCase(
            "calib_star_e2048",
            "single_source_fanout",
            ("--star", "2048"),
            "Single active source, larger fanout.",
        ),
        DStageCase(
            "calib_fanout_e1024_s16",
            "multi_source_fanout",
            ("--fanout", "1024", "16"),
            "Moderate edge stream with limited active sources.",
        ),
        DStageCase(
            "calib_fanout_e4096_s64",
            "multi_source_fanout",
            ("--fanout", "4096", "64"),
            "Larger edge stream with many active records.",
        ),
        DStageCase(
            "calib_fanout_e8192_s128",
            "multi_source_fanout",
            ("--fanout", "8192", "128"),
            "Large fast-tile path case.",
        ),
        DStageCase(
            "calib_repeat_fanout_e256_b2_s32",
            "multi_batch_level_state",
            ("--repeat-fanout", "256", "2", "32"),
            "Two batches creating L1 state before CONV.",
        ),
        DStageCase(
            "calib_repeat_fanout_e512_b3_s64",
            "multi_batch_level_state",
            ("--repeat-fanout", "512", "3", "64"),
            "Three batches with mixed L0/L1 state.",
        ),
        DStageCase(
            "calib_repeat_star_e1024_b2",
            "repeat_single_source",
            ("--repeat-star", "1024", "2"),
            "Repeated single-source fanout batches.",
        ),
        DStageCase(
            "calib_fallback_forced",
            "full_path_tile",
            ("--fallback-forced",),
            "Full tile path dominated by vertex-state sweep.",
        ),
    ]


def phase3a1_holdout_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "holdout_star_e256",
            "single_source_fanout",
            ("--star", "256"),
            "Unseen single-source fanout.",
        ),
        DStageCase(
            "holdout_star_e1024",
            "single_source_fanout",
            ("--star", "1024"),
            "Unseen medium single-source fanout.",
        ),
        DStageCase(
            "holdout_star_onepart_e512",
            "one_partition_fanout",
            ("--star-onepart", "512"),
            "Unseen one-partition destination fanout.",
        ),
        DStageCase(
            "holdout_fanout_e2048_s32",
            "multi_source_fanout",
            ("--fanout", "2048", "32"),
            "Unseen fast-tile multi-source case.",
        ),
        DStageCase(
            "holdout_fanout_e6144_s96",
            "multi_source_fanout",
            ("--fanout", "6144", "96"),
            "Unseen larger fast-tile case.",
        ),
        DStageCase(
            "holdout_repeat_fanout_e256_b4_s32",
            "multi_batch_level_state",
            ("--repeat-fanout", "256", "4", "32"),
            "Unseen four-batch level-state case.",
        ),
        DStageCase(
            "holdout_repeat_fanout_e1024_b2_s128",
            "multi_batch_level_state",
            ("--repeat-fanout", "1024", "2", "128"),
            "Unseen repeated fanout with more active sources.",
        ),
        DStageCase(
            "holdout_repeat_star_dense_e512_b2",
            "repeat_single_source",
            ("--repeat-star-dense", "512", "2"),
            "Unseen dense repeated star with destination local_start at zero.",
        ),
    ]


def phase3a1_final_holdout_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "final_star_e384",
            "single_source_fanout",
            ("--star", "384"),
            "Final unseen single-source fanout.",
        ),
        DStageCase(
            "final_star_e1536",
            "single_source_fanout",
            ("--star", "1536"),
            "Final unseen larger single-source fanout.",
        ),
        DStageCase(
            "final_star_onepart_e1024",
            "one_partition_fanout",
            ("--star-onepart", "1024"),
            "Final unseen one-partition destination fanout.",
        ),
        DStageCase(
            "final_fanout_e3072_s48",
            "multi_source_fanout",
            ("--fanout", "3072", "48"),
            "Final unseen multi-source fanout.",
        ),
        DStageCase(
            "final_fanout_e7168_s112",
            "multi_source_fanout",
            ("--fanout", "7168", "112"),
            "Final unseen larger multi-source fanout.",
        ),
        DStageCase(
            "final_repeat_fanout_e384_b3_s48",
            "multi_batch_level_state",
            ("--repeat-fanout", "384", "3", "48"),
            "Final unseen three-batch level-state case.",
        ),
        DStageCase(
            "final_repeat_fanout_e768_b2_s96",
            "multi_batch_level_state",
            ("--repeat-fanout", "768", "2", "96"),
            "Final unseen two-batch level-state case.",
        ),
        DStageCase(
            "final_repeat_star_dense_e768_b2",
            "repeat_single_source",
            ("--repeat-star-dense", "768", "2"),
            "Final unseen dense repeated star case.",
        ),
    ]


def phase3a2_tile_calibration_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "tile_calib_fast_128",
            "tile_fast_range",
            ("--tile-work", "128", "--print-tile-schedule"),
            "Small fast tile.",
        ),
        DStageCase(
            "tile_calib_fast_1024",
            "tile_fast_range",
            ("--tile-work", "1024", "--print-tile-schedule"),
            "Medium fast tile.",
        ),
        DStageCase(
            "tile_calib_fast_4095",
            "tile_threshold",
            ("--tile-work", "4095", "--print-tile-schedule"),
            "Fast tile just below threshold.",
        ),
        DStageCase(
            "tile_calib_fast_4096",
            "tile_threshold",
            ("--tile-work", "4096", "--print-tile-schedule"),
            "Fast tile at threshold.",
        ),
        DStageCase(
            "tile_calib_full_4097",
            "tile_threshold",
            ("--tile-work", "4097", "--print-tile-schedule"),
            "Full tile just above threshold.",
        ),
        DStageCase(
            "tile_calib_full_4098",
            "tile_threshold",
            ("--tile-work", "4098", "--print-tile-schedule"),
            "Full tile above threshold.",
        ),
        DStageCase(
            "tile_calib_full_8192",
            "tile_full_range",
            ("--tile-work", "8192", "--print-tile-schedule"),
            "Medium full tile.",
        ),
        DStageCase(
            "tile_calib_full_32768",
            "tile_full_range",
            ("--tile-work", "32768", "--print-tile-schedule"),
            "Large partial full tile.",
        ),
        DStageCase(
            "tile_calib_mixed_4096_4097",
            "tile_mixed_boundary",
            ("--tile-work", "4096", "4097", "--print-tile-schedule"),
            "Boundary fast/full mixed pair.",
        ),
        DStageCase(
            "tile_calib_mixed_128_8192",
            "tile_mixed_range",
            ("--tile-work", "128", "8192", "--print-tile-schedule"),
            "Small fast plus medium full.",
        ),
        DStageCase(
            "tile_calib_mixed_1024_16384",
            "tile_mixed_range",
            ("--tile-work", "1024", "16384", "--print-tile-schedule"),
            "Medium fast plus larger full.",
        ),
        DStageCase(
            "tile_calib_mixed_128_32768",
            "tile_mixed_range",
            ("--tile-work", "128", "32768", "--print-tile-schedule"),
            "Small fast plus large full.",
        ),
    ]


def phase3a2_tile_holdout_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "tile_holdout_fast_256",
            "tile_fast_range",
            ("--tile-work", "256", "--print-tile-schedule"),
            "Unseen small fast tile.",
        ),
        DStageCase(
            "tile_holdout_fast_2048",
            "tile_fast_range",
            ("--tile-work", "2048", "--print-tile-schedule"),
            "Unseen medium fast tile.",
        ),
        DStageCase(
            "tile_holdout_full_16384",
            "tile_full_range",
            ("--tile-work", "16384", "--print-tile-schedule"),
            "Unseen medium full tile.",
        ),
        DStageCase(
            "tile_holdout_full_49152",
            "tile_full_range",
            ("--tile-work", "49152", "--print-tile-schedule"),
            "Unseen large full tile.",
        ),
        DStageCase(
            "tile_holdout_mixed_256_16384",
            "tile_mixed_range",
            ("--tile-work", "256", "16384", "--print-tile-schedule"),
            "Unseen small fast plus medium full.",
        ),
        DStageCase(
            "tile_holdout_mixed_2048_49152",
            "tile_mixed_range",
            ("--tile-work", "2048", "49152", "--print-tile-schedule"),
            "Unseen fast plus large full.",
        ),
        DStageCase(
            "tile_holdout_mixed_4095_8192",
            "tile_mixed_boundary_range",
            ("--tile-work", "4095", "8192", "--print-tile-schedule"),
            "Unseen near-threshold fast plus medium full.",
        ),
        DStageCase(
            "tile_holdout_mixed_4098_32768",
            "tile_mixed_boundary_range",
            ("--tile-work", "4098", "32768", "--print-tile-schedule"),
            "Unseen near-threshold full plus larger full.",
        ),
    ]


def phase3a2_tile_regression_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "tile_regression_tiny_mixed_fallback",
            "tile_mixed_boundary",
            ("--tiny-mixed-fallback", "--print-tile-schedule"),
            "Original mixed fast/full diagnostic regression case.",
        ),
    ]


def phase3a3_tile_calibration_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "a3_calib_mt_4096_4096_4097",
            "multi_tile_single_partition",
            ("--tile-work", "4096", "4096", "4097", "--print-tile-schedule"),
            "Three local tiles with a fast/fast/full boundary mix.",
        ),
        DStageCase(
            "a3_calib_mt_128_8192_32768",
            "multi_tile_single_partition",
            ("--tile-work", "128", "8192", "32768", "--print-tile-schedule"),
            "Small fast tile plus two full tiles.",
        ),
        DStageCase(
            "a3_calib_mt_256_2048_16384_49152",
            "multi_tile_single_partition",
            (
                "--tile-work",
                "256",
                "2048",
                "16384",
                "49152",
                "--print-tile-schedule",
            ),
            "Four tiles spanning tiny, medium, and large work.",
        ),
        DStageCase(
            "a3_calib_mt_1024_4096_4097_8192",
            "multi_tile_single_partition",
            (
                "--tile-work",
                "1024",
                "4096",
                "4097",
                "8192",
                "--print-tile-schedule",
            ),
            "Boundary pair surrounded by smaller/larger tiles.",
        ),
        DStageCase(
            "a3_calib_mt_4095_4096_4097_4098",
            "multi_tile_boundary",
            (
                "--tile-work",
                "4095",
                "4096",
                "4097",
                "4098",
                "--print-tile-schedule",
            ),
            "Dense coverage of the fast/full threshold boundary.",
        ),
        DStageCase(
            "a3_calib_mt_512_4096_16384",
            "multi_tile_single_partition",
            ("--tile-work", "512", "4096", "16384", "--print-tile-schedule"),
            "Moderate three-tile interpolation case.",
        ),
        DStageCase(
            "a3_calib_mp_p0_4096_4097_p1_128_8192",
            "multi_partition_tile",
            (
                "--partition-tile-work",
                "0:4096,4097",
                "1:128,8192",
                "--print-tile-schedule",
            ),
            "Two partitions, each with fast/full tile mix.",
        ),
        DStageCase(
            "a3_calib_mp_p0_256_16384_p1_2048_49152",
            "multi_partition_tile",
            (
                "--partition-tile-work",
                "0:256,16384",
                "1:2048,49152",
                "--print-tile-schedule",
            ),
            "Two partitions with asymmetric large full-tile pressure.",
        ),
        DStageCase(
            "a3_calib_mp_p0_4095_8192_p3_4098_32768",
            "multi_partition_boundary",
            (
                "--partition-tile-work",
                "0:4095,8192",
                "3:4098,32768",
                "--print-tile-schedule",
            ),
            "Separated partitions with near-boundary fast/full split.",
        ),
        DStageCase(
            "a3_calib_mp_p0_128_p1_8192_p2_32768",
            "multi_partition_tile",
            (
                "--partition-tile-work",
                "0:128",
                "1:8192",
                "2:32768",
                "--print-tile-schedule",
            ),
            "Three partitions with one active tile each.",
        ),
        DStageCase(
            "a3_calib_mp_p0_4096_p1_4096_p2_4097_p3_4097",
            "multi_partition_boundary",
            (
                "--partition-tile-work",
                "0:4096",
                "1:4096",
                "2:4097",
                "3:4097",
                "--print-tile-schedule",
            ),
            "Four partitions exactly around the threshold.",
        ),
        DStageCase(
            "a3_calib_mp_p2_128_8192_p5_1024_16384",
            "multi_partition_tile",
            (
                "--partition-tile-work",
                "2:128,8192",
                "5:1024,16384",
                "--print-tile-schedule",
            ),
            "Nonzero partition ids check partition-index handling.",
        ),
    ]


def phase3a3_tile_holdout_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "a3_hold_mt_512_4096_4097",
            "multi_tile_single_partition",
            ("--tile-work", "512", "4096", "4097", "--print-tile-schedule"),
            "Unseen three-tile boundary mix.",
        ),
        DStageCase(
            "a3_hold_mt_2048_8192_32768",
            "multi_tile_single_partition",
            ("--tile-work", "2048", "8192", "32768", "--print-tile-schedule"),
            "Unseen medium/large multi-tile mix.",
        ),
        DStageCase(
            "a3_hold_mt_128_4095_16384_49152",
            "multi_tile_boundary",
            (
                "--tile-work",
                "128",
                "4095",
                "16384",
                "49152",
                "--print-tile-schedule",
            ),
            "Unseen four-tile case below threshold plus large full tiles.",
        ),
        DStageCase(
            "a3_hold_mt_4098_8192_16384",
            "multi_tile_single_partition",
            ("--tile-work", "4098", "8192", "16384", "--print-tile-schedule"),
            "Unseen all-full multi-tile case.",
        ),
        DStageCase(
            "a3_hold_mp_p0_512_4097_p1_2048_16384",
            "multi_partition_tile",
            (
                "--partition-tile-work",
                "0:512,4097",
                "1:2048,16384",
                "--print-tile-schedule",
            ),
            "Unseen two-partition mixed fast/full workload.",
        ),
        DStageCase(
            "a3_hold_mp_p0_128_32768_p2_4096_8192",
            "multi_partition_tile",
            (
                "--partition-tile-work",
                "0:128,32768",
                "2:4096,8192",
                "--print-tile-schedule",
            ),
            "Unseen separated partitions with large full tile.",
        ),
        DStageCase(
            "a3_hold_mp_p1_4098_49152_p4_256_16384",
            "multi_partition_tile",
            (
                "--partition-tile-work",
                "1:4098,49152",
                "4:256,16384",
                "--print-tile-schedule",
            ),
            "Unseen high-load multi-partition case.",
        ),
        DStageCase(
            "a3_hold_mp_p0_4095_p1_4096_p2_4097_p3_4098",
            "multi_partition_boundary",
            (
                "--partition-tile-work",
                "0:4095",
                "1:4096",
                "2:4097",
                "3:4098",
                "--print-tile-schedule",
            ),
            "Unseen four-partition threshold sweep.",
        ),
    ]


def phase3a4_replay_calibration_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "a4_calib_src_s1_w1",
            "source_count_sweep",
            ("--multi-source-tile-work", "1", "0:1", "--print-tile-schedule"),
            "Single source baseline for replay calibration.",
        ),
        DStageCase(
            "a4_calib_src_s2_w1",
            "source_count_sweep",
            ("--multi-source-tile-work", "2", "0:1", "--print-tile-schedule"),
            "Two active source records, one tile.",
        ),
        DStageCase(
            "a4_calib_src_s4_w1",
            "source_count_sweep",
            ("--multi-source-tile-work", "4", "0:1", "--print-tile-schedule"),
            "Small active source count, one tile.",
        ),
        DStageCase(
            "a4_calib_src_s8_w1",
            "source_count_sweep",
            ("--multi-source-tile-work", "8", "0:1", "--print-tile-schedule"),
            "Eight active source records, one tile.",
        ),
        DStageCase(
            "a4_calib_src_s16_w1",
            "source_count_sweep",
            ("--multi-source-tile-work", "16", "0:1", "--print-tile-schedule"),
            "Sixteen active source records, one tile.",
        ),
        DStageCase(
            "a4_calib_src_s32_w1",
            "source_count_sweep",
            ("--multi-source-tile-work", "32", "0:1", "--print-tile-schedule"),
            "Thirty-two active source records, one tile.",
        ),
        DStageCase(
            "a4_calib_src_s64_w1",
            "source_count_sweep",
            ("--multi-source-tile-work", "64", "0:1", "--print-tile-schedule"),
            "Sixty-four active source records, one tile.",
        ),
        DStageCase(
            "a4_calib_src_s128_w1",
            "source_count_sweep",
            ("--multi-source-tile-work", "128", "0:1", "--print-tile-schedule"),
            "One hundred twenty-eight active source records, one tile.",
        ),
        DStageCase(
            "a4_calib_work_s4_w4",
            "per_source_work_sweep",
            ("--multi-source-tile-work", "4", "0:4", "--print-tile-schedule"),
            "Per-source work sweep, small tile work.",
        ),
        DStageCase(
            "a4_calib_work_s4_w16",
            "per_source_work_sweep",
            ("--multi-source-tile-work", "4", "0:16", "--print-tile-schedule"),
            "Per-source work sweep, medium-small tile work.",
        ),
        DStageCase(
            "a4_calib_work_s4_w64",
            "per_source_work_sweep",
            ("--multi-source-tile-work", "4", "0:64", "--print-tile-schedule"),
            "Per-source work sweep, medium tile work.",
        ),
        DStageCase(
            "a4_calib_work_s4_w256",
            "per_source_work_sweep",
            ("--multi-source-tile-work", "4", "0:256", "--print-tile-schedule"),
            "Per-source work sweep, large fast tile.",
        ),
        DStageCase(
            "a4_calib_work_s4_w1024",
            "fast_boundary",
            ("--multi-source-tile-work", "4", "0:1024", "--print-tile-schedule"),
            "Exactly 4096 total tile work through four sources.",
        ),
        DStageCase(
            "a4_calib_boundary_s4097_w1",
            "fast_boundary",
            ("--multi-source-tile-work", "4097", "0:1", "--print-tile-schedule"),
            "4097 active sources make one tile cross the fast/full boundary.",
        ),
        DStageCase(
            "a4_calib_multitile_s16_w4x4",
            "multi_tile_replay",
            (
                "--multi-source-tile-work",
                "16",
                "0:4,4,4,4",
                "--print-tile-schedule",
            ),
            "Sixteen sources replayed across four touched tiles.",
        ),
        DStageCase(
            "a4_calib_multipart_s32_p0_p1",
            "multi_partition_replay",
            (
                "--multi-source-tile-work",
                "32",
                "0:1,4",
                "1:8,16",
                "--print-tile-schedule",
            ),
            "Multi-source replay across two partitions and four tile entries.",
        ),
        DStageCase(
            "a4_calib_replay_at_s4096_t16",
            "replay_fallback_boundary",
            (
                "--striped-source-tile-work",
                "4096",
                "0",
                "16",
                "1",
                "--full-vertices",
                "--print-tile-schedule",
            ),
            "Replay estimate at 65536, should not force fallback.",
        ),
        DStageCase(
            "a4_calib_replay_above_s4097_t16",
            "replay_fallback_boundary",
            (
                "--striped-source-tile-work",
                "4097",
                "0",
                "16",
                "1",
                "--full-vertices",
                "--print-tile-schedule",
            ),
            "Replay estimate just above 65536, should force fallback.",
        ),
        DStageCase(
            "a4_calib_full_s64_w128",
            "moderate_full_path",
            ("--multi-source-tile-work", "64", "0:128", "--print-tile-schedule"),
            "Moderate source count with 8192 total work in one full tile.",
        ),
        DStageCase(
            "a4_calib_full_s129_w32",
            "moderate_full_path",
            ("--multi-source-tile-work", "129", "0:32", "--print-tile-schedule"),
            "Moderate source count just above the 4096 fast/full boundary.",
        ),
        DStageCase(
            "a4_calib_full_s257_w16",
            "moderate_full_path",
            ("--multi-source-tile-work", "257", "0:16", "--print-tile-schedule"),
            "Higher source count just above the 4096 fast/full boundary.",
        ),
        DStageCase(
            "a4_calib_boundary_s682_w6",
            "fast_boundary",
            ("--multi-source-tile-work", "682", "0:6", "--print-tile-schedule"),
            "4092 total tile work below the holdout full-boundary point.",
        ),
        DStageCase(
            "a4_calib_mixed_s40_moderate",
            "multi_tile_mixed",
            (
                "--multi-source-tile-work",
                "40",
                "0:16,64,128,384",
                "--print-tile-schedule",
            ),
            "Moderate mixed fast/full multi-tile replay shape.",
        ),
        DStageCase(
            "a4_calib_multitile_s80_t8",
            "multi_tile_replay",
            (
                "--multi-source-tile-work",
                "80",
                "0:1,1,1,1,1,1,1,1",
                "--print-tile-schedule",
            ),
            "Eight-tile replay interpolation point below the holdout case.",
        ),
        DStageCase(
            "a4_calib_multipart_s96_p0_p2",
            "multi_partition_replay",
            (
                "--multi-source-tile-work",
                "96",
                "0:4",
                "2:4",
                "--print-tile-schedule",
            ),
            "Two-partition replay interpolation point.",
        ),
        DStageCase(
            "a4_calib_src_s3_w4",
            "source_count_sweep",
            ("--multi-source-tile-work", "3", "0:4", "--print-tile-schedule"),
            "Small unseen-source interpolation point.",
        ),
        DStageCase(
            "a4_calib_multitile_s20_w2_8",
            "multi_tile_replay",
            ("--multi-source-tile-work", "20", "0:2,8", "--print-tile-schedule"),
            "Two-tile replay interpolation below the holdout source count.",
        ),
        DStageCase(
            "a4_calib_multitile_s88_t8",
            "multi_tile_replay",
            (
                "--multi-source-tile-work",
                "88",
                "0:1,1,1,1,1,1,1,1",
                "--print-tile-schedule",
            ),
            "Eight-tile replay interpolation below the holdout source count.",
        ),
        DStageCase(
            "a4_calib_multipart_s112_p0_p3",
            "multi_partition_replay",
            (
                "--multi-source-tile-work",
                "112",
                "0:8",
                "3:8",
                "--print-tile-schedule",
            ),
            "Two-partition one-tile interpolation below the holdout source count.",
        ),
        DStageCase(
            "a4_calib_multipart_s72_mixed",
            "multi_partition_replay",
            (
                "--multi-source-tile-work",
                "72",
                "0:1,16",
                "2:4,32",
                "--print-tile-schedule",
            ),
            "Mixed multi-partition interpolation above the holdout source count.",
        ),
        DStageCase(
            "a4_calib_boundary_s684_w6",
            "fast_boundary",
            ("--multi-source-tile-work", "684", "0:6", "--print-tile-schedule"),
            "4104 total tile work above the holdout full-boundary point.",
        ),
    ]


def phase3a4_replay_holdout_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "a4_hold_src_s3_w7",
            "source_count_holdout",
            ("--multi-source-tile-work", "3", "0:7", "--print-tile-schedule"),
            "Unseen small source/work combination.",
        ),
        DStageCase(
            "a4_hold_multitile_s24_w2_8",
            "multi_tile_replay",
            ("--multi-source-tile-work", "24", "0:2,8", "--print-tile-schedule"),
            "Unseen two-tile replay shape.",
        ),
        DStageCase(
            "a4_hold_multitile_s48_mixed",
            "multi_tile_mixed",
            (
                "--multi-source-tile-work",
                "48",
                "0:16,64,128,512",
                "--print-tile-schedule",
            ),
            "Unseen mixed fast/full four-tile replay shape.",
        ),
        DStageCase(
            "a4_hold_multitile_s96_t8",
            "multi_tile_replay",
            (
                "--multi-source-tile-work",
                "96",
                "0:1,1,1,1,1,1,1,1",
                "--print-tile-schedule",
            ),
            "Unseen eight-tile replay without fallback.",
        ),
        DStageCase(
            "a4_hold_multipart_s128_p0_p3",
            "multi_partition_replay",
            (
                "--multi-source-tile-work",
                "128",
                "0:8",
                "3:8",
                "--print-tile-schedule",
            ),
            "Unseen two-partition one-tile replay.",
        ),
        DStageCase(
            "a4_hold_multipart_s64_mixed",
            "multi_partition_replay",
            (
                "--multi-source-tile-work",
                "64",
                "0:1,16",
                "2:4,32",
                "--print-tile-schedule",
            ),
            "Unseen multi-partition and multi-tile replay combination.",
        ),
        DStageCase(
            "a4_hold_boundary_s63_w65",
            "fast_boundary",
            ("--multi-source-tile-work", "63", "0:65", "--print-tile-schedule"),
            "Unseen 4095 total tile work fast-boundary case.",
        ),
        DStageCase(
            "a4_hold_boundary_s683_w6",
            "fast_boundary",
            ("--multi-source-tile-work", "683", "0:6", "--print-tile-schedule"),
            "Unseen 4098 total tile work full-boundary case.",
        ),
        DStageCase(
            "a4_hold_replay_below_s4095_t16",
            "replay_fallback_boundary",
            (
                "--striped-source-tile-work",
                "4095",
                "0",
                "16",
                "1",
                "--full-vertices",
                "--print-tile-schedule",
            ),
            "Replay estimate just below 65536.",
        ),
        DStageCase(
            "a4_hold_replay_above_s8193_t16",
            "replay_fallback_boundary",
            (
                "--striped-source-tile-work",
                "8193",
                "0",
                "16",
                "1",
                "--full-vertices",
                "--print-tile-schedule",
            ),
            "Larger unseen replay fallback case with low per-tile work.",
        ),
    ]


def phase3b_bottleneck_synthetic_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "p3b_tiny_s1_w1",
            "fixed_overhead",
            ("--multi-source-tile-work", "1", "0:1", "--print-tile-schedule"),
            "One source and one edge; fixed overhead probe.",
        ),
        DStageCase(
            "p3b_src_s5_w11",
            "source_count",
            ("--multi-source-tile-work", "5", "0:11", "--print-tile-schedule"),
            "Small unseen source/work point.",
        ),
        DStageCase(
            "p3b_src_s48_w3",
            "source_count",
            ("--multi-source-tile-work", "48", "0:3", "--print-tile-schedule"),
            "Moderate source count with little per-source work.",
        ),
        DStageCase(
            "p3b_src_s160_w1",
            "source_count",
            ("--multi-source-tile-work", "160", "0:1", "--print-tile-schedule"),
            "Higher source count with one tile and one edge per source.",
        ),
        DStageCase(
            "p3b_fast_s7_w256",
            "fast_tile_work",
            ("--multi-source-tile-work", "7", "0:256", "--print-tile-schedule"),
            "Fast-path tile with larger per-source work.",
        ),
        DStageCase(
            "p3b_fast_boundary_s31_w132",
            "fast_full_boundary",
            ("--multi-source-tile-work", "31", "0:132", "--print-tile-schedule"),
            "4092 total tile work, just below the fast/full boundary.",
        ),
        DStageCase(
            "p3b_full_boundary_s31_w133",
            "fast_full_boundary",
            ("--multi-source-tile-work", "31", "0:133", "--print-tile-schedule"),
            "4123 total tile work, just above the fast/full boundary.",
        ),
        DStageCase(
            "p3b_full_s96_w96",
            "full_tile_work",
            ("--multi-source-tile-work", "96", "0:96", "--print-tile-schedule"),
            "Moderate full tile with many source records.",
        ),
        DStageCase(
            "p3b_full_large_s32_w1024",
            "full_tile_work",
            ("--multi-source-tile-work", "32", "0:1024", "--print-tile-schedule"),
            "Large single full tile with fewer source records.",
        ),
        DStageCase(
            "p3b_multitile_s16_mixed",
            "multi_tile",
            (
                "--multi-source-tile-work",
                "16",
                "0:1,4,16,64",
                "--print-tile-schedule",
            ),
            "Four fast tiles with increasing work.",
        ),
        DStageCase(
            "p3b_multitile_s64_t8_e2",
            "multi_tile_replay",
            (
                "--multi-source-tile-work",
                "64",
                "0:2,2,2,2,2,2,2,2",
                "--print-tile-schedule",
            ),
            "Eight touched tiles, replay dominates more than edge count.",
        ),
        DStageCase(
            "p3b_multitile_s96_mixed_full",
            "multi_tile_mixed",
            (
                "--multi-source-tile-work",
                "96",
                "0:1,8,64,256",
                "--print-tile-schedule",
            ),
            "Mixed fast/full tiles with substantial source replay.",
        ),
        DStageCase(
            "p3b_multitile_s128_t16_e1",
            "multi_tile_replay",
            (
                "--multi-source-tile-work",
                "128",
                "0:1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1",
                "--print-tile-schedule",
            ),
            "Sixteen touched tiles below replay fallback.",
        ),
        DStageCase(
            "p3b_multipart_s32_p0_p7_p15",
            "multi_partition",
            (
                "--multi-source-tile-work",
                "32",
                "0:2,8",
                "7:4",
                "15:16",
                "--print-tile-schedule",
            ),
            "Three partitions with small/mid tile work.",
        ),
        DStageCase(
            "p3b_multipart_s96_mixed",
            "multi_partition_mixed",
            (
                "--multi-source-tile-work",
                "96",
                "0:1,32",
                "5:4,64",
                "10:16",
                "--print-tile-schedule",
            ),
            "Multi-partition replay with mixed fast/full tiles.",
        ),
        DStageCase(
            "p3b_replay_below_s2048_t16",
            "replay_fallback_boundary",
            (
                "--striped-source-tile-work",
                "2048",
                "0",
                "16",
                "1",
                "--full-vertices",
                "--print-tile-schedule",
            ),
            "Replay proxy 32768, comfortably below fallback threshold.",
        ),
        DStageCase(
            "p3b_replay_below_s4094_t16",
            "replay_fallback_boundary",
            (
                "--striped-source-tile-work",
                "4094",
                "0",
                "16",
                "1",
                "--full-vertices",
                "--print-tile-schedule",
            ),
            "Replay proxy 65504, just below fallback threshold.",
        ),
        DStageCase(
            "p3b_replay_above_s4098_t16",
            "replay_fallback_boundary",
            (
                "--striped-source-tile-work",
                "4098",
                "0",
                "16",
                "1",
                "--full-vertices",
                "--print-tile-schedule",
            ),
            "Replay proxy 65568, just above fallback threshold.",
        ),
        DStageCase(
            "p3b_replay_at_s8192_t8",
            "replay_fallback_boundary",
            (
                "--striped-source-tile-work",
                "8192",
                "0",
                "8",
                "1",
                "--full-vertices",
                "--print-tile-schedule",
            ),
            "Replay proxy 65536 with only eight discovered tiles.",
        ),
        DStageCase(
            "p3b_replay_above_s8193_t8",
            "replay_fallback_boundary",
            (
                "--striped-source-tile-work",
                "8193",
                "0",
                "8",
                "1",
                "--full-vertices",
                "--print-tile-schedule",
            ),
            "Replay proxy above 65536; fallback also sweeps empty tiles.",
        ),
        DStageCase(
            "p3b_partition_full_p0_p1",
            "multi_partition_full",
            (
                "--partition-tile-work",
                "0:8192,8192",
                "1:4096,4097",
                "--print-tile-schedule",
            ),
            "One-source multi-partition full-tile interaction.",
        ),
        DStageCase(
            "p3b_partition_sparse_wide",
            "multi_partition_sparse",
            (
                "--partition-tile-work",
                "0:1",
                "3:1",
                "7:1",
                "15:1",
                "--print-tile-schedule",
            ),
            "Sparse one-source touches across distant partitions.",
        ),
    ]


def phase3b_multibatch_probe_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "p3b_repeat_fanout_e512_b2_s64",
            "multibatch_level_probe",
            ("--repeat-fanout", "512", "2", "64", "--print-tile-schedule"),
            "Two batches create level state before convergence; diagnostic only.",
        ),
        DStageCase(
            "p3b_repeat_fanout_e1024_b3_s64",
            "multibatch_level_probe",
            ("--repeat-fanout", "1024", "3", "64", "--print-tile-schedule"),
            "Three fanout batches exercise carry/level-state exposure.",
        ),
        DStageCase(
            "p3b_repeat_star_dense_e512_b2",
            "multibatch_level_probe",
            ("--repeat-star-dense", "512", "2", "--print-tile-schedule"),
            "Repeated dense star with destination overlap; diagnostic only.",
        ),
        DStageCase(
            "p3b_repeat_star_e1024_b3",
            "multibatch_level_probe",
            ("--repeat-star", "1024", "3", "--print-tile-schedule"),
            "Repeated star across batches; diagnostic only.",
        ),
    ]


def phase3c_full_partition_calibration_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "p3c_cal_full_s1_w4097",
            "full_low_replay",
            ("--multi-source-tile-work", "1", "0:4097", "--print-tile-schedule"),
            "One source, one low-replay full tile just above threshold.",
        ),
        DStageCase(
            "p3c_cal_full_s1_w8192",
            "full_low_replay",
            ("--multi-source-tile-work", "1", "0:8192", "--print-tile-schedule"),
            "One source, medium full tile.",
        ),
        DStageCase(
            "p3c_cal_full_s1_w32768",
            "full_low_replay",
            ("--multi-source-tile-work", "1", "0:32768", "--print-tile-schedule"),
            "One source, large full tile.",
        ),
        DStageCase(
            "p3c_cal_full_s2_w4096",
            "full_low_replay",
            ("--multi-source-tile-work", "2", "0:4096", "--print-tile-schedule"),
            "Two sources, 8192 total full work.",
        ),
        DStageCase(
            "p3c_cal_full_s4_w4096",
            "full_low_replay",
            ("--multi-source-tile-work", "4", "0:4096", "--print-tile-schedule"),
            "Four sources, 16384 total full work.",
        ),
        DStageCase(
            "p3c_cal_full_s8_w4096",
            "full_low_replay",
            ("--multi-source-tile-work", "8", "0:4096", "--print-tile-schedule"),
            "Eight sources, 32768 total full work.",
        ),
        DStageCase(
            "p3c_cal_full_s16_w2048",
            "full_low_replay",
            ("--multi-source-tile-work", "16", "0:2048", "--print-tile-schedule"),
            "Sixteen sources, 32768 total full work.",
        ),
        DStageCase(
            "p3c_cal_full_s32_w512",
            "full_low_replay",
            ("--multi-source-tile-work", "32", "0:512", "--print-tile-schedule"),
            "Thirty-two sources, 16384 total full work.",
        ),
        DStageCase(
            "p3c_cal_full_s48_w256",
            "full_low_replay",
            ("--multi-source-tile-work", "48", "0:256", "--print-tile-schedule"),
            "Forty-eight sources, 12288 total full work.",
        ),
        DStageCase(
            "p3c_cal_full_s64_w128",
            "full_low_replay",
            ("--multi-source-tile-work", "64", "0:128", "--print-tile-schedule"),
            "Sixty-four sources, 8192 total full work.",
        ),
        DStageCase(
            "p3c_cal_full_boundary_s17_w241",
            "full_low_replay_boundary",
            ("--multi-source-tile-work", "17", "0:241", "--print-tile-schedule"),
            "4097 total full work with a different source/work ratio.",
        ),
        DStageCase(
            "p3c_cal_full_boundary_s33_w125",
            "full_low_replay_boundary",
            ("--multi-source-tile-work", "33", "0:125", "--print-tile-schedule"),
            "4125 total full work near the boundary.",
        ),
        DStageCase(
            "p3c_cal_multitile_s8_small",
            "small_multitile_fixed",
            (
                "--multi-source-tile-work",
                "8",
                "0:1,4,16,64",
                "--print-tile-schedule",
            ),
            "Small fast multi-tile overhead point.",
        ),
        DStageCase(
            "p3c_cal_multitile_s16_scaled",
            "small_multitile_fixed",
            (
                "--multi-source-tile-work",
                "16",
                "0:2,8,32,128",
                "--print-tile-schedule",
            ),
            "Scaled four-tile fast path point.",
        ),
        DStageCase(
            "p3c_cal_multitile_s24_t4_e1",
            "small_multitile_fixed",
            (
                "--multi-source-tile-work",
                "24",
                "0:1,1,1,1",
                "--print-tile-schedule",
            ),
            "Four tiny fast tiles with more sources.",
        ),
        DStageCase(
            "p3c_cal_multitile_s32_t6",
            "small_multitile_fixed",
            (
                "--multi-source-tile-work",
                "32",
                "0:1,2,4,8,16,32",
                "--print-tile-schedule",
            ),
            "Six small fast tiles below replay fallback.",
        ),
        DStageCase(
            "p3c_cal_multipart_s24_p0_p5_p12",
            "multi_partition_interaction",
            (
                "--multi-source-tile-work",
                "24",
                "0:2,8",
                "5:4",
                "12:12",
                "--print-tile-schedule",
            ),
            "Three partitions near the Phase 3B multi-partition failure shape.",
        ),
        DStageCase(
            "p3c_cal_multipart_s48_p0_p6",
            "multi_partition_interaction",
            (
                "--multi-source-tile-work",
                "48",
                "0:1,16",
                "6:4,32",
                "--print-tile-schedule",
            ),
            "Two partitions with four fast tiles.",
        ),
        DStageCase(
            "p3c_cal_multipart_s96_p0_p5_p11",
            "multi_partition_interaction",
            (
                "--multi-source-tile-work",
                "96",
                "0:1,16",
                "5:4,48",
                "11:8",
                "--print-tile-schedule",
            ),
            "Three partitions with one full tile and several fast tiles.",
        ),
        DStageCase(
            "p3c_cal_multipart_s64_p1_p8_p14",
            "multi_partition_interaction",
            (
                "--multi-source-tile-work",
                "64",
                "1:2,64",
                "8:4",
                "14:16",
                "--print-tile-schedule",
            ),
            "Separated partitions with mixed tile counts.",
        ),
        DStageCase(
            "p3c_cal_partition_full_p0_p2_p4",
            "multi_partition_full",
            (
                "--partition-tile-work",
                "0:4097",
                "2:8192",
                "4:16384",
                "--print-tile-schedule",
            ),
            "One-source full tiles spread over three partitions.",
        ),
        DStageCase(
            "p3c_cal_partition_sparse_p0_p2_p4_p6_p8",
            "multi_partition_sparse",
            (
                "--partition-tile-work",
                "0:1",
                "2:1",
                "4:1",
                "6:1",
                "8:1",
                "--print-tile-schedule",
            ),
            "Sparse partition fixed-overhead point.",
        ),
        DStageCase(
            "p3c_cal_partition_mixed_p0_p3_p9",
            "multi_partition_full",
            (
                "--partition-tile-work",
                "0:4096,4097",
                "3:8192",
                "9:32768",
                "--print-tile-schedule",
            ),
            "One-source multi-partition mixed fast/full point.",
        ),
    ]


def phase3c_full_partition_holdout_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "p3c_hold_full_s3_w2048",
            "full_low_replay",
            ("--multi-source-tile-work", "3", "0:2048", "--print-tile-schedule"),
            "Unseen low-replay full tile.",
        ),
        DStageCase(
            "p3c_hold_full_s5_w4096",
            "full_low_replay",
            ("--multi-source-tile-work", "5", "0:4096", "--print-tile-schedule"),
            "Unseen 20480-work full tile.",
        ),
        DStageCase(
            "p3c_hold_full_boundary_s31_w134",
            "full_low_replay_boundary",
            ("--multi-source-tile-work", "31", "0:134", "--print-tile-schedule"),
            "Unseen near-boundary full tile close to Phase 3B final.",
        ),
        DStageCase(
            "p3c_hold_full_s40_w768",
            "full_low_replay",
            ("--multi-source-tile-work", "40", "0:768", "--print-tile-schedule"),
            "Unseen large full tile with forty sources.",
        ),
        DStageCase(
            "p3c_hold_full_s2_w16384",
            "full_low_replay",
            ("--multi-source-tile-work", "2", "0:16384", "--print-tile-schedule"),
            "Unseen large full tile with two sources.",
        ),
        DStageCase(
            "p3c_hold_multitile_s12_small",
            "small_multitile_fixed",
            (
                "--multi-source-tile-work",
                "12",
                "0:1,4,16,64",
                "--print-tile-schedule",
            ),
            "Unseen small multi-tile overhead point.",
        ),
        DStageCase(
            "p3c_hold_multitile_s20_t6",
            "small_multitile_fixed",
            (
                "--multi-source-tile-work",
                "20",
                "0:1,2,4,8,16,32",
                "--print-tile-schedule",
            ),
            "Unseen six-tile small fast path point.",
        ),
        DStageCase(
            "p3c_hold_multipart_s28_p0_p7_p15",
            "multi_partition_interaction",
            (
                "--multi-source-tile-work",
                "28",
                "0:2,8",
                "7:4",
                "15:12",
                "--print-tile-schedule",
            ),
            "Unseen three-partition shape near Phase 3B final.",
        ),
        DStageCase(
            "p3c_hold_multipart_s80_p0_p5_p10",
            "multi_partition_interaction",
            (
                "--multi-source-tile-work",
                "80",
                "0:1,24",
                "5:4,56",
                "10:8",
                "--print-tile-schedule",
            ),
            "Unseen mixed multi-partition shape.",
        ),
        DStageCase(
            "p3c_hold_partition_sparse_p1_p4_p8_p12",
            "multi_partition_sparse",
            (
                "--partition-tile-work",
                "1:1",
                "4:1",
                "8:1",
                "12:1",
                "--print-tile-schedule",
            ),
            "Unseen sparse partition fixed-overhead point.",
        ),
        DStageCase(
            "p3c_hold_partition_full_p1_p4_p11",
            "multi_partition_full",
            (
                "--partition-tile-work",
                "1:4097",
                "4:8192,16384",
                "11:4096",
                "--print-tile-schedule",
            ),
            "Unseen one-source multi-partition full path point.",
        ),
        DStageCase(
            "p3c_hold_multipart_s40_sparse",
            "multi_partition_interaction",
            (
                "--multi-source-tile-work",
                "40",
                "2:1,1",
                "7:1,1",
                "13:1,1",
                "--print-tile-schedule",
            ),
            "Unseen small work spread across partitions and tiles.",
        ),
    ]


def phase3c_final_validation_matrix() -> list[DStageCase]:
    return [
        DStageCase(
            "p3c_final_full_boundary_s31_w133",
            "phase3b_untrusted_full",
            ("--multi-source-tile-work", "31", "0:133", "--print-tile-schedule"),
            "Exact Phase 3B untrusted full-boundary case; final validation only.",
        ),
        DStageCase(
            "p3c_final_full_large_s32_w1024",
            "phase3b_untrusted_full",
            ("--multi-source-tile-work", "32", "0:1024", "--print-tile-schedule"),
            "Exact Phase 3B untrusted large full tile; final validation only.",
        ),
        DStageCase(
            "p3c_final_multitile_s16_mixed",
            "phase3b_untrusted_multitile",
            (
                "--multi-source-tile-work",
                "16",
                "0:1,4,16,64",
                "--print-tile-schedule",
            ),
            "Exact Phase 3B untrusted small multi-tile case; final validation only.",
        ),
        DStageCase(
            "p3c_final_multipart_s32_p0_p7_p15",
            "phase3b_untrusted_multipart",
            (
                "--multi-source-tile-work",
                "32",
                "0:2,8",
                "7:4",
                "15:16",
                "--print-tile-schedule",
            ),
            "Exact Phase 3B untrusted multi-partition case; final validation only.",
        ),
        DStageCase(
            "p3c_final_multipart_s96_mixed",
            "phase3b_untrusted_multipart",
            (
                "--multi-source-tile-work",
                "96",
                "0:1,32",
                "5:4,64",
                "10:16",
                "--print-tile-schedule",
            ),
            "Exact Phase 3B untrusted mixed multi-partition case.",
        ),
        DStageCase(
            "p3c_final_replay_below_s4094_t16",
            "phase3b_replay_guard",
            (
                "--striped-source-tile-work",
                "4094",
                "0",
                "16",
                "1",
                "--full-vertices",
                "--print-tile-schedule",
            ),
            "Replay guard case that was already accurate in Phase 3B.",
        ),
        DStageCase(
            "p3c_final_replay_above_s4098_t16",
            "phase3b_replay_guard",
            (
                "--striped-source-tile-work",
                "4098",
                "0",
                "16",
                "1",
                "--full-vertices",
                "--print-tile-schedule",
            ),
            "Replay fallback guard case that must not regress.",
        ),
        DStageCase(
            "p3c_final_replay_above_s8193_t8",
            "phase3b_replay_guard",
            (
                "--striped-source-tile-work",
                "8193",
                "0",
                "8",
                "1",
                "--full-vertices",
                "--print-tile-schedule",
            ),
            "Large replay fallback guard case that must not regress.",
        ),
    ]


def matrix_by_name(name: str) -> list[DStageCase]:
    if name == "phase3a0_readiness":
        return default_matrix()
    if name == "phase3a1_calibration":
        return phase3a1_calibration_matrix()
    if name == "phase3a1_holdout":
        return phase3a1_holdout_matrix()
    if name == "phase3a1_final_holdout":
        return phase3a1_final_holdout_matrix()
    if name == "phase3a2_tile_calibration":
        return phase3a2_tile_calibration_matrix()
    if name == "phase3a2_tile_holdout":
        return phase3a2_tile_holdout_matrix()
    if name == "phase3a2_tile_regression":
        return phase3a2_tile_regression_matrix()
    if name == "phase3a3_tile_calibration":
        return phase3a3_tile_calibration_matrix()
    if name == "phase3a3_tile_holdout":
        return phase3a3_tile_holdout_matrix()
    if name == "phase3a4_replay_calibration":
        return phase3a4_replay_calibration_matrix()
    if name == "phase3a4_replay_holdout":
        return phase3a4_replay_holdout_matrix()
    if name == "phase3b_bottleneck_synthetic":
        return phase3b_bottleneck_synthetic_matrix()
    if name == "phase3b_multibatch_probe":
        return phase3b_multibatch_probe_matrix()
    if name == "phase3c_full_partition_calibration":
        return phase3c_full_partition_calibration_matrix()
    if name == "phase3c_full_partition_holdout":
        return phase3c_full_partition_holdout_matrix()
    if name == "phase3c_final_validation":
        return phase3c_final_validation_matrix()
    raise ValueError(f"unknown D-stage matrix: {name}")


def load_matrix_json(path: Path) -> tuple[str, list[DStageCase]]:
    data = json.loads(path.read_text())
    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError(f"matrix json is missing a cases list: {path}")
    cases: list[DStageCase] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise ValueError(f"case {index} is not an object in {path}")
        case_id = str(raw.get("case", "")).strip()
        if not case_id:
            raise ValueError(f"case {index} is missing a case id in {path}")
        if case_id in seen:
            raise ValueError(f"duplicate case id {case_id!r} in {path}")
        seen.add(case_id)
        sweep = str(raw.get("sweep", "external"))
        args = raw.get("args", [])
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise ValueError(f"case {case_id!r} args must be a list of strings")
        purpose = str(raw.get("purpose", "External D-stage case."))
        cases.append(DStageCase(case=case_id, sweep=sweep, args=tuple(args), purpose=purpose))
    matrix_name = str(data.get("matrix", path.stem))
    return matrix_name, cases


def parse_scalar(value: str) -> int | float | str:
    if value in {"PASS", "FAIL"}:
        return value
    try:
        return int(value, 0)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def parse_stdout(stdout: str) -> dict[str, Any]:
    final_line = ""
    for line in stdout.splitlines():
        if line.startswith("PARTITIONED_CSR_E2E_SMOKE "):
            final_line = line
    if not final_line:
        return {"status": "MISSING"}
    parts = final_line.split()
    row: dict[str, Any] = {"status": parts[1] if len(parts) > 1 else "UNKNOWN"}
    for key, value in KEY_VALUE_RE.findall(final_line):
        row[key] = parse_scalar(value)
    return row


def parse_tile_schedule(stdout: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not line.startswith("PARTITIONED_CSR_E2E_TILE_SCHEDULE "):
            continue
        row: dict[str, Any] = {}
        for key, value in KEY_VALUE_RE.findall(line):
            row[key] = parse_scalar(value)
        if row:
            rows.append(row)
    return rows


def parse_batch_events(stdout: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if not line.startswith("PARTITIONED_CSR_E2E_BATCH "):
            continue
        row: dict[str, Any] = {}
        for key, value in KEY_VALUE_RE.findall(line):
            row[key] = parse_scalar(value)
        if row:
            rows.append(row)
    return rows


def build_command(
    case: DStageCase,
    host_exe: Path,
    xclbin: Path,
    timeout_s: int,
    xrt_setup: Path | None,
    split_kernels: bool,
) -> str:
    invocation = [
        str(host_exe),
        str(xclbin),
        *case.args,
        "--timeout",
        str(timeout_s),
    ]
    parts: list[str] = []
    if xrt_setup:
        parts.append(f"source {shlex.quote(str(xrt_setup))}")
    parts.append("unset XCL_EMULATION_MODE")
    if split_kernels:
        parts.append("export SPINE_PARTITIONED_SPLIT=1")
    parts.append(" ".join(shlex.quote(value) for value in invocation))
    return " && ".join(parts)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], preferred: list[str]) -> None:
    keys = set(preferred)
    for row in rows:
        keys.update(row.keys())
    fieldnames = preferred + sorted(keys.difference(preferred))
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def median_or_blank(values: list[float]) -> float | str:
    if not values:
        return ""
    return statistics.median(values)


def jitter_pct(values: list[float]) -> float | str:
    if len(values) < 2:
        return ""
    med = statistics.median(values)
    if med == 0:
        return ""
    return (max(values) - min(values)) / med * 100.0


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["case"]), []).append(row)

    summary: list[dict[str, Any]] = []
    for case, group in grouped.items():
        ok = [row for row in group if row.get("status") == "PASS" and row.get("returncode") == 0]
        out: dict[str, Any] = {
            "case": case,
            "sweep": group[0]["sweep"],
            "repeats": len(group),
            "successful_repeats": len(ok),
        }
        for key in ["conv_ms", "reader_ms", "conv_span_ms", "maint_ms", "kernel_e2e_ms"]:
            values = [
                float(row[key])
                for row in ok
                if key in row and isinstance(row[key], (int, float))
            ]
            out[f"median_{key}"] = median_or_blank(values)
            if key == "conv_ms" and values:
                out["min_conv_ms"] = min(values)
                out["max_conv_ms"] = max(values)
                out["conv_ms_jitter_pct"] = jitter_pct(values)
        for key in [
            "vertices",
            "batches",
            "input_edges",
            "persisted",
            "target_level",
            "active_sources",
            "active_records",
            "active_record_replays",
            "next_active",
            "traversed_edges",
            "touched_tiles",
            "marked_tiles",
            "nonempty_tiles",
            "empty_tile_passes",
            "fallback_used",
            "row_lookups",
            "clipped_ranges",
            "fast_path_tiles",
            "full_path_tiles",
            "gathered_vertex_words",
            "swept_vertex_words",
            "scattered_vertex_words",
        ]:
            values = [row.get(key) for row in ok if key in row]
            if values:
                out[f"median_{key}"] = statistics.median(float(value) for value in values)
        summary.append(out)
    return summary


def run_case(
    case: DStageCase,
    repeat: int,
    host_exe: Path,
    xclbin: Path,
    timeout_s: int,
    xrt_setup: Path | None,
    split_kernels: bool,
    out_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    raw_dir = out_dir / "raw" / case.case
    raw_dir.mkdir(parents=True, exist_ok=True)
    command = build_command(
        case,
        host_exe=host_exe,
        xclbin=xclbin,
        timeout_s=timeout_s,
        xrt_setup=xrt_setup,
        split_kernels=split_kernels,
    )
    completed = subprocess.run(
        ["bash", "-lc", command],
        cwd=str(host_exe.resolve().parent),
        text=True,
        capture_output=True,
        timeout=timeout_s + 120,
        check=False,
    )
    stdout_path = raw_dir / f"run_{repeat}.stdout"
    stderr_path = raw_dir / f"run_{repeat}.stderr"
    command_path = raw_dir / f"run_{repeat}.command.sh"
    stdout_path.write_text(completed.stdout)
    stderr_path.write_text(completed.stderr)
    command_path.write_text(command + "\n")

    row = {
        "case": case.case,
        "sweep": case.sweep,
        "repeat": repeat,
        "returncode": completed.returncode,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        "command_log": str(command_path),
        "command": command,
    }
    parsed = parse_stdout(completed.stdout)
    tile_schedule = parse_tile_schedule(completed.stdout)
    batch_events = parse_batch_events(completed.stdout)
    if "case" in parsed:
        parsed["host_case"] = parsed.pop("case")
    row.update(parsed)
    row["tile_schedule_entries"] = len(tile_schedule)
    row["batch_event_entries"] = len(batch_events)
    if completed.returncode != 0 and row.get("status") == "MISSING":
        row["status"] = "FAIL"
    for entry in tile_schedule:
        entry["case"] = case.case
        entry["sweep"] = case.sweep
        entry["repeat"] = repeat
    for entry in batch_events:
        entry["case"] = case.case
        entry["sweep"] = case.sweep
        entry["repeat"] = repeat
    return row, tile_schedule, batch_events


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host-exe", type=Path, default=Path(DEFAULT_HOST_EXE))
    parser.add_argument("--xclbin", type=Path, default=Path(DEFAULT_XCLBIN))
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--xrt-setup", type=Path, default=Path(DEFAULT_XRT_SETUP))
    parser.add_argument("--no-xrt-setup", action="store_true")
    parser.add_argument("--no-split-kernels", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--matrix",
        choices=[
            "phase3a0_readiness",
            "phase3a1_calibration",
            "phase3a1_holdout",
            "phase3a1_final_holdout",
            "phase3a2_tile_calibration",
            "phase3a2_tile_holdout",
            "phase3a2_tile_regression",
            "phase3a3_tile_calibration",
            "phase3a3_tile_holdout",
            "phase3a4_replay_calibration",
            "phase3a4_replay_holdout",
            "phase3b_bottleneck_synthetic",
            "phase3b_multibatch_probe",
            "phase3c_full_partition_calibration",
            "phase3c_full_partition_holdout",
            "phase3c_final_validation",
        ],
        default="phase3a0_readiness",
        help="Select the built-in D-stage experiment matrix.",
    )
    parser.add_argument(
        "--matrix-json",
        type=Path,
        help="Load D-stage cases from an external matrix JSON file.",
    )
    parser.add_argument("--only-case", action="append", help="Limit to one or more case ids.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.repeats <= 0:
        raise SystemExit("--repeats must be positive")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    matrix_name = args.matrix
    if args.matrix_json:
        matrix_name, cases = load_matrix_json(args.matrix_json)
    else:
        cases = matrix_by_name(args.matrix)
    if args.only_case:
        allowed = set(args.only_case)
        cases = [case for case in cases if case.case in allowed]
    if not cases:
        raise SystemExit("selected matrix is empty")

    xrt_setup = None if args.no_xrt_setup else args.xrt_setup
    split_kernels = not args.no_split_kernels
    write_json(
        args.out_dir / "matrix.json",
        {
            "host_exe": str(args.host_exe),
            "xclbin": str(args.xclbin),
            "repeats": args.repeats,
            "timeout_s": args.timeout,
            "xrt_setup": str(xrt_setup) if xrt_setup else "",
            "split_kernels": split_kernels,
            "matrix": matrix_name,
            "source_matrix_json": str(args.matrix_json) if args.matrix_json else "",
            "cases": [asdict(case) for case in cases],
        },
    )

    commands = [
        build_command(
            case,
            host_exe=args.host_exe,
            xclbin=args.xclbin,
            timeout_s=args.timeout,
            xrt_setup=xrt_setup,
            split_kernels=split_kernels,
        )
        for case in cases
    ]
    (args.out_dir / "commands.sh").write_text("\n".join(commands) + "\n")
    if args.dry_run:
        print(f"cases={len(cases)} repeats={args.repeats} total_runs={len(cases) * args.repeats}")
        return 0

    rows: list[dict[str, Any]] = []
    tile_schedule_rows: list[dict[str, Any]] = []
    batch_event_rows: list[dict[str, Any]] = []
    for case in cases:
        for repeat in range(1, args.repeats + 1):
            print(f"[{case.case}] repeat {repeat}/{args.repeats}", flush=True)
            row, tile_schedule, batch_events = run_case(
                case,
                repeat=repeat,
                host_exe=args.host_exe,
                xclbin=args.xclbin,
                timeout_s=args.timeout,
                xrt_setup=xrt_setup,
                split_kernels=split_kernels,
                out_dir=args.out_dir,
            )
            rows.append(row)
            tile_schedule_rows.extend(tile_schedule)
            batch_event_rows.extend(batch_events)
            print(
                "  status={status} returncode={returncode} conv_ms={conv_ms} "
                "reader_ms={reader_ms} traversed_edges={traversed_edges}".format(
                    status=row.get("status"),
                    returncode=row.get("returncode"),
                    conv_ms=row.get("conv_ms", ""),
                    reader_ms=row.get("reader_ms", ""),
                    traversed_edges=row.get("traversed_edges", ""),
                ),
                flush=True,
            )

    write_csv(args.out_dir / "runs.csv", rows, BASE_FIELDS)
    write_csv(args.out_dir / "summary.csv", aggregate(rows), SUMMARY_FIELDS)
    if tile_schedule_rows:
        write_csv(
            args.out_dir / "tile_schedule.csv",
            tile_schedule_rows,
            TILE_SCHEDULE_FIELDS,
        )
    if batch_event_rows:
        write_csv(
            args.out_dir / "batch_events.csv",
            batch_event_rows,
            BATCH_EVENT_FIELDS,
        )
    print(f"wrote runs: {args.out_dir / 'runs.csv'}")
    print(f"wrote summary: {args.out_dir / 'summary.csv'}")
    if tile_schedule_rows:
        print(f"wrote tile schedule: {args.out_dir / 'tile_schedule.csv'}")
    if batch_event_rows:
        print(f"wrote batch events: {args.out_dir / 'batch_events.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
