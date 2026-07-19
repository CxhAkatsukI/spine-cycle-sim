#!/usr/bin/env python3
"""Compare HW-emitted D-stage tile schedules against simulator schedules."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.models import SpineConfig, load_config  # noqa: E402
from spine_cycle_sim.models.dstage import build_tile_schedule  # noqa: E402
from spine_cycle_sim.workloads import (  # noqa: E402
    Workload,
    generate_multi_source_tile_workload,
    generate_partition_tile_workload,
    generate_striped_source_tile_workload,
    generate_tile_workload,
)


COMPARE_FIELDS = [
    "case",
    "repeat",
    "partition",
    "tile",
    "status",
    "hw_path",
    "sim_path",
    "hw_tile_work",
    "sim_tile_work",
    "hw_tile_size",
    "sim_tile_size",
    "hw_fallback_used",
    "sim_fallback_used",
    "hw_nonempty",
    "sim_nonempty",
    "hw_clipped_ranges",
    "sim_clipped_ranges",
    "hw_gathered_vertex_words",
    "sim_gathered_vertex_words",
    "hw_swept_vertex_words",
    "sim_swept_vertex_words",
    "hw_scattered_vertex_words",
    "sim_scattered_vertex_words",
    "mismatch_fields",
]

STRICT_COUNTER_FIELDS = [
    "active_sources",
    "active_records",
    "traversed_edges",
    "touched_tiles",
    "nonempty_tiles",
    "empty_tile_passes",
    "fast_path_tiles",
    "full_path_tiles",
    "gathered_vertex_words",
    "swept_vertex_words",
]

DIAGNOSTIC_COUNTER_FIELDS = [
    "marked_tiles",
    "fallback_used",
    "row_lookups",
    "clipped_ranges",
    "active_record_replays",
    "scattered_vertex_words",
]

COUNTER_COMPARE_FIELDS = [
    "case",
    "repeat",
    "status",
    "mismatch_fields",
    *[f"hw_{field}" for field in STRICT_COUNTER_FIELDS],
    *[f"sim_{field}" for field in STRICT_COUNTER_FIELDS],
    *[f"hw_{field}" for field in DIAGNOSTIC_COUNTER_FIELDS],
    *[f"sim_{field}" for field in DIAGNOSTIC_COUNTER_FIELDS],
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    keys = set(COMPARE_FIELDS)
    for row in rows:
        keys.update(row)
    fieldnames = COMPARE_FIELDS + sorted(keys.difference(COMPARE_FIELDS))
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def to_int(value: Any) -> int:
    if value in {None, ""}:
        return 0
    return int(float(value))


def parse_partition_tile_work_specs(specs: list[str]) -> dict[int, list[int]]:
    if not specs:
        raise ValueError("partition-tile-work requires at least one spec")
    partition_tile_work: dict[int, list[int]] = {}
    for spec in specs:
        partition_text, separator, counts_text = spec.partition(":")
        if not separator or not partition_text or not counts_text:
            raise ValueError(f"invalid partition-tile-work spec: {spec!r}")
        partition = int(partition_text, 0)
        if partition in partition_tile_work:
            raise ValueError(f"duplicate partition-tile-work partition: {partition}")
        counts = [int(value, 0) for value in counts_text.split(",")]
        if not counts:
            raise ValueError(f"empty partition-tile-work counts: {spec!r}")
        partition_tile_work[partition] = counts
    return partition_tile_work


def parse_striped_source_tile_work(args: list[str]) -> tuple[int, int, int, int]:
    if len(args) < 5:
        raise ValueError("striped-source-tile-work requires four arguments")
    return int(args[1], 0), int(args[2], 0), int(args[3], 0), int(args[4], 0)


def workload_from_case(case: dict[str, Any], config: SpineConfig) -> Workload:
    args = list(case["args"])
    full_vertices = False
    clean_args: list[str] = []
    for arg in args:
        if arg == "--print-tile-schedule":
            continue
        if arg == "--full-vertices":
            full_vertices = True
            continue
        clean_args.append(arg)
    if clean_args and clean_args[0] == "--tiny-mixed-fallback":
        tile_work = [config.tiny_active_threshold, config.tiny_active_threshold + 1]
    elif clean_args and clean_args[0] == "--tile-work":
        tile_work = [int(value) for value in clean_args[1:]]
    elif clean_args and clean_args[0] == "--partition-tile-work":
        vertices = config.max_vertices if full_vertices else None
        workload = generate_partition_tile_workload(
            parse_partition_tile_work_specs(clean_args[1:]),
            vertices=vertices,
            tile_vertices=config.conv_tile_vertices,
            vs_partition_size=config.vs_partition_size,
            max_vertices=config.max_vertices,
        )
        workload.metadata["case"] = str(case["case"])
        return workload
    elif clean_args and clean_args[0] == "--multi-source-tile-work":
        vertices = config.max_vertices if full_vertices else None
        workload = generate_multi_source_tile_workload(
            int(clean_args[1], 0),
            parse_partition_tile_work_specs(clean_args[2:]),
            vertices=vertices,
            tile_vertices=config.conv_tile_vertices,
            vs_partition_size=config.vs_partition_size,
            max_vertices=config.max_vertices,
        )
        workload.metadata["case"] = str(case["case"])
        return workload
    elif clean_args and clean_args[0] == "--striped-source-tile-work":
        vertices = config.max_vertices if full_vertices else None
        source_count, partition, tile_count, edges_per_source = (
            parse_striped_source_tile_work(clean_args)
        )
        workload = generate_striped_source_tile_workload(
            source_count,
            partition,
            tile_count,
            edges_per_source,
            vertices=vertices,
            tile_vertices=config.conv_tile_vertices,
            vs_partition_size=config.vs_partition_size,
            max_vertices=config.max_vertices,
        )
        workload.metadata["case"] = str(case["case"])
        return workload
    else:
        raise ValueError(f"unsupported schedule comparison args: {args}")
    vertices = config.max_vertices if full_vertices else None
    workload = generate_tile_workload(
        tile_work,
        vertices=vertices,
        tile_vertices=config.conv_tile_vertices,
        max_vertices=config.max_vertices,
    )
    workload.metadata["case"] = str(case["case"])
    return workload


def sim_schedules_by_case(matrix: dict[str, Any], config: SpineConfig) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for case in matrix["cases"]:
        workload = workload_from_case(case, config)
        schedule = build_tile_schedule(workload.edges, workload.vertices, config)
        out[str(case["case"])] = schedule
    return out


def sim_entries_by_case(sim_schedules: dict[str, Any]) -> dict[str, dict[tuple[int, int], dict[str, Any]]]:
    return {
        case: {
            (entry.partition, entry.tile): asdict(entry)
            for entry in schedule.entries
        }
        for case, schedule in sim_schedules.items()
    }


def compare_schedule(hw_rows: list[dict[str, str]], sim_by_case: dict[str, dict[tuple[int, int], dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    checked_keys: set[tuple[str, int, int, int]] = set()
    for hw in hw_rows:
        case = hw["case"]
        repeat = to_int(hw.get("repeat"))
        partition = to_int(hw.get("partition"))
        tile = to_int(hw.get("tile"))
        sim = sim_by_case.get(case, {}).get((partition, tile))
        mismatches: list[str] = []
        if sim is None:
            mismatches.append("missing_sim_entry")
            sim = {}
        comparisons = [
            ("path", str(hw.get("path", "")), str(sim.get("path", ""))),
            ("tile_work", to_int(hw.get("tile_work")), to_int(sim.get("tile_work"))),
            ("tile_size", to_int(hw.get("tile_size")), to_int(sim.get("tile_size"))),
            (
                "fallback_used",
                to_int(hw.get("fallback_used")),
                int(bool(sim.get("fallback_used", False))),
            ),
            (
                "nonempty",
                to_int(hw.get("nonempty")),
                int(bool(sim.get("nonempty", False))),
            ),
            (
                "clipped_ranges",
                to_int(hw.get("clipped_ranges")),
                to_int(sim.get("clipped_ranges")),
            ),
            (
                "gathered_vertex_words",
                to_int(hw.get("gathered_vertex_words")),
                to_int(sim.get("gathered_vertex_words")),
            ),
            (
                "swept_vertex_words",
                to_int(hw.get("swept_vertex_words")),
                to_int(sim.get("swept_vertex_words")),
            ),
            (
                "scattered_vertex_words",
                to_int(hw.get("scattered_vertex_words")),
                to_int(sim.get("scattered_vertex_words")),
            ),
        ]
        for field, got, expected in comparisons:
            if got != expected:
                mismatches.append(field)
        checked_keys.add((case, repeat, partition, tile))
        rows.append(
            {
                "case": case,
                "repeat": repeat,
                "partition": partition,
                "tile": tile,
                "status": "PASS" if not mismatches else "FAIL",
                "hw_path": hw.get("path", ""),
                "sim_path": sim.get("path", ""),
                "hw_tile_work": hw.get("tile_work", ""),
                "sim_tile_work": sim.get("tile_work", ""),
                "hw_tile_size": hw.get("tile_size", ""),
                "sim_tile_size": sim.get("tile_size", ""),
                "hw_fallback_used": hw.get("fallback_used", ""),
                "sim_fallback_used": int(bool(sim.get("fallback_used", False))),
                "hw_nonempty": hw.get("nonempty", ""),
                "sim_nonempty": int(bool(sim.get("nonempty", False))),
                "hw_clipped_ranges": hw.get("clipped_ranges", ""),
                "sim_clipped_ranges": sim.get("clipped_ranges", ""),
                "hw_gathered_vertex_words": hw.get("gathered_vertex_words", ""),
                "sim_gathered_vertex_words": sim.get("gathered_vertex_words", ""),
                "hw_swept_vertex_words": hw.get("swept_vertex_words", ""),
                "sim_swept_vertex_words": sim.get("swept_vertex_words", ""),
                "hw_scattered_vertex_words": hw.get("scattered_vertex_words", ""),
                "sim_scattered_vertex_words": sim.get("scattered_vertex_words", ""),
                "mismatch_fields": ",".join(mismatches),
            }
        )
    return rows


def sim_counter_value(schedule: Any, field: str) -> int:
    return int(getattr(schedule, field))


def compare_counters(
    run_rows: list[dict[str, str]],
    sim_schedules: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for hw in run_rows:
        case = hw["case"]
        repeat = to_int(hw.get("repeat"))
        sim = sim_schedules.get(case)
        mismatches: list[str] = []
        out: dict[str, Any] = {
            "case": case,
            "repeat": repeat,
        }
        if sim is None:
            mismatches.append("missing_sim_schedule")
        for field in STRICT_COUNTER_FIELDS:
            hw_value = to_int(hw.get(field))
            sim_value = sim_counter_value(sim, field) if sim is not None else 0
            out[f"hw_{field}"] = hw_value
            out[f"sim_{field}"] = sim_value
            if hw_value != sim_value:
                mismatches.append(field)
        for field in DIAGNOSTIC_COUNTER_FIELDS:
            hw_value = to_int(hw.get(field))
            sim_value = sim_counter_value(sim, field) if sim is not None else 0
            out[f"hw_{field}"] = hw_value
            out[f"sim_{field}"] = sim_value
        out["mismatch_fields"] = ",".join(mismatches)
        out["status"] = "PASS" if not mismatches else "FAIL"
        rows.append(out)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hw-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/spine_current.yaml"))
    parser.add_argument("--out-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    matrix_path = args.hw_dir / "matrix.json"
    schedule_path = args.hw_dir / "tile_schedule.csv"
    if not matrix_path.exists():
        raise SystemExit(f"missing matrix.json: {matrix_path}")
    if not schedule_path.exists():
        raise SystemExit(f"missing tile_schedule.csv: {schedule_path}")

    config = load_config(args.config)
    matrix = json.loads(matrix_path.read_text())
    hw_rows = read_csv(schedule_path)
    sim_schedules = sim_schedules_by_case(matrix, config)
    sim_by_case = sim_entries_by_case(sim_schedules)
    comparison = compare_schedule(hw_rows, sim_by_case)

    out_dir = args.out_dir or args.hw_dir / "schedule_compare"
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = [row for row in comparison if row["status"] != "PASS"]
    counter_failures: list[dict[str, Any]] = []
    runs_path = args.hw_dir / "runs.csv"
    if runs_path.exists():
        counter_comparison = compare_counters(read_csv(runs_path), sim_schedules)
        counter_failures = [
            row for row in counter_comparison if row["status"] != "PASS"
        ]
        write_csv(out_dir / "counter_comparison.csv", counter_comparison)
    summary = {
        "hw_dir": str(args.hw_dir),
        "schedule_samples": len(comparison),
        "schedule_failures": len(failures),
        "counter_samples": len(counter_comparison) if runs_path.exists() else 0,
        "counter_failures": len(counter_failures),
        "diagnostic_counter_fields": DIAGNOSTIC_COUNTER_FIELDS,
        "status": "PASS" if not failures and not counter_failures else "FAIL",
    }
    write_csv(out_dir / "schedule_comparison.csv", comparison)
    write_json(out_dir / "summary.json", summary)
    print(
        f"schedule_compare status={summary['status']} "
        f"schedule_samples={summary['schedule_samples']} "
        f"schedule_failures={summary['schedule_failures']} "
        f"counter_samples={summary['counter_samples']} "
        f"counter_failures={summary['counter_failures']}"
    )
    return 0 if not failures and not counter_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
