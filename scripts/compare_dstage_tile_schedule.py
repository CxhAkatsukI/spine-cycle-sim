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
from spine_cycle_sim.workloads import Workload, generate_tile_workload  # noqa: E402


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
    "hw_gathered_vertex_words",
    "sim_gathered_vertex_words",
    "hw_swept_vertex_words",
    "sim_swept_vertex_words",
    "hw_scattered_vertex_words",
    "sim_scattered_vertex_words",
    "mismatch_fields",
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


def sim_entries_by_case(matrix: dict[str, Any], config: SpineConfig) -> dict[str, dict[tuple[int, int], dict[str, Any]]]:
    out: dict[str, dict[tuple[int, int], dict[str, Any]]] = {}
    for case in matrix["cases"]:
        workload = workload_from_case(case, config)
        schedule = build_tile_schedule(workload.edges, workload.vertices, config)
        out[str(case["case"])] = {
            (entry.partition, entry.tile): asdict(entry)
            for entry in schedule.entries
        }
    return out


def compare(hw_rows: list[dict[str, str]], sim_by_case: dict[str, dict[tuple[int, int], dict[str, Any]]]) -> list[dict[str, Any]]:
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
    sim_by_case = sim_entries_by_case(matrix, config)
    comparison = compare(hw_rows, sim_by_case)

    out_dir = args.out_dir or args.hw_dir / "schedule_compare"
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = [row for row in comparison if row["status"] != "PASS"]
    summary = {
        "hw_dir": str(args.hw_dir),
        "samples": len(comparison),
        "failures": len(failures),
        "status": "PASS" if not failures else "FAIL",
    }
    write_csv(out_dir / "schedule_comparison.csv", comparison)
    write_json(out_dir / "summary.json", summary)
    print(
        f"schedule_compare status={summary['status']} "
        f"samples={summary['samples']} failures={summary['failures']}"
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
