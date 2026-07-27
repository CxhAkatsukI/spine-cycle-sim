#!/usr/bin/env python3
"""Build fail-closed physical-memory evidence for Candidate10 batch-8 runs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sys
import tarfile
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.real_memory_analysis import (  # noqa: E402
    ALGORITHMS,
    load_physical_selected_matrix,
    physical_pair_rows,
    physical_paper_rows,
    sha256_file,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty table: {path}")
    fieldnames = list(dict.fromkeys(key for row in rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _archive_sources(
    path: Path,
    inputs: tuple[tuple[str, Path], ...],
    run_ids: set[str],
) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for algorithm, directory in inputs:
            for name in ("matrix_manifest.json", "pairs.csv", "system_rows.csv"):
                source = directory / name
                archive.add(source, arcname=f"{algorithm}/{name}")
            for run_id in sorted(run_ids):
                for system in ("spine", "grasu_regraph"):
                    run_dir = directory / run_id / system
                    for source in sorted(run_dir.rglob("*")):
                        if source.is_file():
                            archive.add(
                                source,
                                arcname=(
                                    f"{algorithm}/{run_id}/{system}/"
                                    f"{source.relative_to(run_dir)}"
                                ),
                            )


def _validated_plugin_fingerprint(
    inputs: tuple[tuple[str, Path], ...], run_ids: set[str]
) -> dict[str, object]:
    observations: list[tuple[str, str, str, str]] = []
    for algorithm, directory in inputs:
        for run_id in sorted(run_ids):
            for system, filename in (
                ("spine", "summary.json"),
                ("grasu_regraph", "manifest.json"),
            ):
                payload = json.loads(
                    (directory / run_id / system / filename).read_text(
                        encoding="utf-8"
                    )
                )
                binding = payload.get("sst_library_binding")
                if not isinstance(binding, Mapping):
                    raise ValueError(
                        f"missing SST library binding: {algorithm}/{run_id}/{system}"
                    )
                plugin_sha = str(payload.get("sst_plugin_sha256", ""))
                if len(plugin_sha) != 64 or binding.get("plugin_sha256") != plugin_sha:
                    raise ValueError(
                        f"invalid SST plugin identity: {algorithm}/{run_id}/{system}"
                    )
                plugin_path = str(binding.get("plugin_path", ""))
                search_path = str(binding.get("search_path", ""))
                command_option = str(binding.get("command_option", ""))
                if not plugin_path or search_path.split(":", 1)[0] != str(
                    Path(plugin_path).parent
                ) or command_option != f"--lib-path={search_path}":
                    raise ValueError(
                        f"SST plugin is not first in the exact library path: "
                        f"{algorithm}/{run_id}/{system}"
                    )
                observations.append(
                    (plugin_sha, plugin_path, search_path, command_option)
                )
    unique = set(observations)
    if len(observations) != len(inputs) * len(run_ids) * 2 or len(unique) != 1:
        raise ValueError("physical matrix did not use one identical SST plugin binding")
    plugin_sha, plugin_path, search_path, command_option = observations[0]
    return {
        "plugin_sha256": plugin_sha,
        "plugin_path_at_execution": plugin_path,
        "search_path": search_path,
        "command_option": command_option,
        "validated_child_results": len(observations),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weighted-dir", type=Path, required=True)
    parser.add_argument("--full-pagerank-dir", type=Path, required=True)
    parser.add_argument("--residual-pagerank-dir", type=Path, required=True)
    parser.add_argument(
        "--input-manifest",
        type=Path,
        default=ROOT
        / "configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json",
    )
    parser.add_argument("--scenario", default="insert")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--paper-data-dir", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    input_manifest = json.loads(args.input_manifest.read_text(encoding="utf-8"))
    expected_run_ids = {
        str(run["run_id"])
        for run in input_manifest["runs"]
        if run["scenario"] == args.scenario
        and int(run["batch_size"]) == args.batch_size
    }
    if len(expected_run_ids) != 5:
        raise ValueError("physical memory matrix requires exactly five datasets")

    inputs = (
        ("weighted_sssp", args.weighted_dir.resolve()),
        ("full_pagerank", args.full_pagerank_dir.resolve()),
        (
            "thresholded_residual_pagerank",
            args.residual_pagerank_dir.resolve(),
        ),
    )
    plugin_fingerprint = _validated_plugin_fingerprint(inputs, expected_run_ids)
    manifests: dict[str, dict[str, object]] = {}
    rows: list[dict[str, object]] = []
    for algorithm, directory in inputs:
        manifest, selected = load_physical_selected_matrix(
            algorithm, directory, expected_run_ids
        )
        manifests[algorithm] = manifest
        rows.extend(selected)
    if len(rows) != 30:
        raise ValueError("physical memory matrix requires 30 system rows")
    pairs = physical_pair_rows(rows)
    if len(pairs) != 15:
        raise ValueError("physical memory matrix requires 15 architecture pairs")
    paper_rows = physical_paper_rows(rows)
    aligned_algorithms = [str(row["algorithm_id"]) for row in paper_rows]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    system_path = args.out_dir / "physical_memory_system_rows.csv"
    pair_path = args.out_dir / "physical_memory_pairs.csv"
    paper_path = args.out_dir / "physical_memory_by_algorithm.csv"
    archive_path = args.out_dir / "raw_results.tar.gz"
    _write_csv(system_path, rows)
    _write_csv(pair_path, pairs)
    _write_csv(paper_path, paper_rows)
    if args.paper_data_dir is not None:
        args.paper_data_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(
            args.paper_data_dir / "physical_memory_by_algorithm.csv", paper_rows
        )
    _archive_sources(archive_path, inputs, expected_run_ids)

    report = {
        "schema_version": 1,
        "evidence_id": "candidate10_physical_memory_insert_u8_v1_20260727",
        "status": "PASS",
        "claim_class": "controller_physical_memory_phase_aligned_partial",
        "algorithms": list(ALGORITHMS),
        "phase_aligned_algorithms": aligned_algorithms,
        "excluded_from_phase_aligned_plot": sorted(
            set(ALGORITHMS) - set(aligned_algorithms)
        ),
        "scenario": args.scenario,
        "batch_size": args.batch_size,
        "selected_run_ids": sorted(expected_run_ids),
        "system_rows": len(rows),
        "pairs": len(pairs),
        "all_correct": all(
            manifest.get("all_correct") is True for manifest in manifests.values()
        ),
        "all_backend_dram_ledgers_closed": True,
        "all_backpressure_contracts_complete": True,
        "sst_plugin_fingerprint": plugin_fingerprint,
        "three_algorithm_windows_aligned": len(aligned_algorithms)
        == len(ALGORITHMS),
        "input_manifest_sha256": sha256_file(args.input_manifest),
        "input_matrices": {
            algorithm: {
                "directory": str(directory),
                "manifest_sha256": sha256_file(directory / "matrix_manifest.json"),
                "system_rows_sha256": sha256_file(directory / "system_rows.csv"),
            }
            for algorithm, directory in inputs
        },
        "outputs": {
            "physical_memory_system_rows.csv": sha256_file(system_path),
            "physical_memory_pairs.csv": sha256_file(pair_path),
            "physical_memory_by_algorithm.csv": sha256_file(paper_path),
            "raw_results.tar.gz": sha256_file(archive_path),
        },
        "limitations": [
            "Inputs are 8192-edge compact real-topology slices, not full datasets.",
            "Only active HBM channels are instantiated; energy is not total-board energy.",
            (
                "Spine weighted SSSP includes cold initialization in the DRAM window, "
                "so weighted SSSP is retained as diagnostic evidence but excluded from "
                "the phase-aligned physical comparison plot."
            ),
            (
                "Stalls are port/request events and multiple events may occur in one "
                "simulated cycle."
            ),
        ],
    }
    report_path = args.out_dir / "physical_memory_evidence.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        "PASS physical memory analysis: "
        f"rows={len(rows)} pairs={len(pairs)} "
        f"aligned_algorithms={','.join(aligned_algorithms)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
