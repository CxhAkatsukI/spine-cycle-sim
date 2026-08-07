#!/usr/bin/env python3
"""Extract host-runtime observations for the Candidate10 figure pack."""

from __future__ import annotations

import argparse
import csv
import io
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = (
    ROOT
    / "docs/evidence/candidate10_grasu_temporal_three_algorithms_insert_u8_20260727"
    / "raw_results.tar.gz"
)
DEFAULT_OUTPUT = ROOT / "docs/paper/data/simulator_host_runtime.csv"

ALGORITHMS = {
    "weighted_sssp": "sssp",
    "full_pagerank": "full_pr",
    "thresholded_residual_pagerank": "residual_pr",
}
SYSTEMS = {
    "spine": "spine",
    "grasu_regraph": "grasu",
}
DATASETS = (
    ("sx_askubuntu", "AU"),
    ("sx_superuser", "SU"),
    ("wiki_talk_temporal", "WK"),
    ("sx_stackoverflow", "SO"),
    ("soc_bitcoin", "BC"),
)


def _positive_number(row: dict[str, str], name: str) -> float:
    try:
        value = float(row[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid {name} in row {row.get('run_id')}") from exc
    if value <= 0:
        raise RuntimeError(f"non-positive {name} in row {row.get('run_id')}")
    return value


def _integer(row: dict[str, str], name: str) -> int:
    try:
        return int(row[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid {name} in row {row.get('run_id')}") from exc


def _read_algorithm_rows(
    archive: tarfile.TarFile, algorithm: str
) -> list[dict[str, str]]:
    member_name = f"raw/{algorithm}/system_rows.csv"
    try:
        member = archive.getmember(member_name)
    except KeyError as exc:
        raise RuntimeError(f"missing archive member {member_name}") from exc
    stream = archive.extractfile(member)
    if stream is None:
        raise RuntimeError(f"cannot read archive member {member_name}")
    with stream:
        text = io.TextIOWrapper(stream, encoding="utf-8", newline="")
        return list(csv.DictReader(text))


def build_rows(archive_path: Path) -> list[dict[str, object]]:
    selected: dict[tuple[str, str, str], dict[str, object]] = {}
    expected_datasets = {dataset for dataset, _ in DATASETS}

    with tarfile.open(archive_path, "r:gz") as archive:
        for algorithm, output_prefix in ALGORITHMS.items():
            for row in _read_algorithm_rows(archive, algorithm):
                run_id = row.get("run_id", "")
                dataset = row.get("dataset_id", "")
                system = row.get("system", "")
                if not run_id.endswith("_insert_u8") or dataset not in expected_datasets:
                    continue
                if system not in SYSTEMS:
                    continue
                if row.get("scenario", "insert") != "insert":
                    continue
                if _integer(row, "initial_edges") != 8192:
                    raise RuntimeError(f"{run_id}/{system} is not an 8192-edge slice")
                if _integer(row, "user_mutations") != 8:
                    raise RuntimeError(f"{run_id}/{system} is not an eight-update run")
                mismatches = row.get("correctness_mismatches", "0")
                if mismatches and int(mismatches) != 0:
                    raise RuntimeError(f"{run_id}/{system} failed correctness")

                key = (algorithm, dataset, system)
                if key in selected:
                    raise RuntimeError(f"duplicate runtime row for {key}")
                selected[key] = {
                    "vertices": _integer(row, "vertices"),
                    "seconds": _positive_number(row, "host_wall_seconds"),
                    "prefix": output_prefix,
                }

    expected = len(ALGORITHMS) * len(DATASETS) * len(SYSTEMS)
    if len(selected) != expected:
        raise RuntimeError(f"expected {expected} runtime rows, found {len(selected)}")

    output: list[dict[str, object]] = []
    for dataset, label in DATASETS:
        result: dict[str, object] = {
            "dataset": label,
            "dataset_id": dataset,
            "vertices": 0,
            "edges": 8192,
        }
        vertex_counts: set[int] = set()
        for algorithm, prefix in ALGORITHMS.items():
            for system, system_prefix in SYSTEMS.items():
                observation = selected[(algorithm, dataset, system)]
                vertex_counts.add(int(observation["vertices"]))
                result[f"{prefix}_{system_prefix}_seconds"] = observation["seconds"]
        if len(vertex_counts) != 1:
            raise RuntimeError(f"inconsistent vertex counts for {dataset}")
        result["vertices"] = vertex_counts.pop()
        output.append(result)
    return output


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "dataset",
        "dataset_id",
        "vertices",
        "edges",
        "sssp_spine_seconds",
        "sssp_grasu_seconds",
        "full_pr_spine_seconds",
        "full_pr_grasu_seconds",
        "residual_pr_spine_seconds",
        "residual_pr_grasu_seconds",
    ]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    rows = build_rows(args.archive)
    write_rows(args.output, rows)
    print(f"wrote {len(rows)} dataset rows to {args.output}")


if __name__ == "__main__":
    main()
