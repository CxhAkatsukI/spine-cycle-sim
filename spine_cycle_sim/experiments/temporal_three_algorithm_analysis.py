"""Fail-closed three-algorithm analysis on the GraSU temporal slices."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tarfile

from .comparison_analysis import aggregate_dram_stats, geometric_mean, sha256_file


ALGORITHM_LABELS = {
    "weighted_sssp": "SSSP",
    "full_pagerank": "Full PR",
    "thresholded_residual_pagerank": "Residual PR",
}
EXPECTED_SCENARIO = "insert"
EXPECTED_BATCH = 8
EXPANDED_BATCHES = (1, 8, 64)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def _expected_run_ids(input_manifest: dict[str, object]) -> set[str]:
    return {
        str(run["run_id"])
        for run in input_manifest["runs"]  # type: ignore[index]
        if run["scenario"] == EXPECTED_SCENARIO
        and int(run["batch_size"]) == EXPECTED_BATCH
    }


def _pair_correct(algorithm: str, row: dict[str, str]) -> bool:
    key = {
        "weighted_sssp": "cross_system_distances_match",
        "full_pagerank": "cross_system_ranks_match",
        "thresholded_residual_pagerank": "cross_system_state_match",
    }[algorithm]
    return _bool(row.get(key, False))


def _e2e_ms(algorithm: str, row: dict[str, str]) -> float:
    key = "aligned_e2e_ms" if algorithm == "weighted_sssp" else "e2e_ms"
    return float(row[key])


def _aligned_backend(algorithm: str, row: dict[str, str]) -> tuple[int, int]:
    if algorithm != "weighted_sssp":
        return int(row["backend_requests"]), int(row["backend_bytes"])
    requests = int(row["aligned_backend_requests"])
    bytes_key = (
        "aligned_backend_bytes" if row["system"] == "spine" else "backend_bytes"
    )
    return requests, int(row[bytes_key])


def _load_algorithm(
    *,
    algorithm: str,
    matrix_dir: Path,
    expected_runs: set[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    manifest = json.loads(
        (matrix_dir / "matrix_manifest.json").read_text(encoding="utf-8")
    )
    if (
        manifest.get("system_rows_sha256")
        != sha256_file(matrix_dir / "system_rows.csv")
        or manifest.get("pairs_sha256") != sha256_file(matrix_dir / "pairs.csv")
    ):
        raise ValueError(f"{algorithm} source matrix hash mismatch")
    rows = [
        row
        for row in _read_csv(matrix_dir / "system_rows.csv")
        if row["run_id"] in expected_runs
    ]
    pairs = [
        row
        for row in _read_csv(matrix_dir / "pairs.csv")
        if row["run_id"] in expected_runs
    ]
    if manifest.get("status") != "PASS" or not manifest.get("all_correct"):
        raise ValueError(f"{algorithm} source matrix did not pass correctness")
    if {row["run_id"] for row in pairs} != expected_runs:
        raise ValueError(f"{algorithm} five-dataset pair coverage is incomplete")
    if len(rows) != 2 * len(expected_runs) or len(pairs) != len(expected_runs):
        raise ValueError(f"{algorithm} selected row count is incomplete")
    if any(int(row["correctness_mismatches"]) != 0 for row in rows):
        raise ValueError(f"incorrect {algorithm} row entered analysis")
    if any(not _pair_correct(algorithm, row) for row in pairs):
        raise ValueError(f"cross-system {algorithm} result mismatch")

    unified_systems: list[dict[str, object]] = []
    for row in rows:
        run_dir = matrix_dir / row["run_id"] / row["system"]
        dram = aggregate_dram_stats(run_dir / "dram")
        if int(dram["requests"]) != int(row["backend_requests"]):
            raise ValueError(
                f"{algorithm}/{row['run_id']}/{row['system']} DRAM ledger mismatch"
            )
        aligned_requests, aligned_bytes = _aligned_backend(algorithm, row)
        physical_window_aligned = not (
            algorithm == "weighted_sssp" and row["system"] == "spine"
        )
        unified_systems.append(
            {
                "run_id": row["run_id"],
                "dataset_id": row["dataset_id"],
                "algorithm": algorithm,
                "system": row["system"],
                "batch_size": int(row["user_mutations"]),
                "scenario": row["scenario"],
                "dataset_kind": row.get("dataset_kind", ""),
                "input_scope": row.get("input_scope", ""),
                "e2e_ms": _e2e_ms(algorithm, row),
                "aligned_backend_requests": aligned_requests,
                "aligned_backend_bytes": aligned_bytes,
                "dram_full_window_requests": int(dram["requests"]),
                "dram_row_hit_rate": float(dram["row_hit_rate"]),
                "dram_average_read_latency": float(dram["average_read_latency"]),
                "dram_physical_window_aligned": physical_window_aligned,
                "correctness_mismatches": 0,
                "raw_result_sha256": row["raw_result_sha256"],
            }
        )

    indexed = {
        (str(row["run_id"]), str(row["system"])): row for row in unified_systems
    }
    unified_pairs: list[dict[str, object]] = []
    for pair in pairs:
        spine = indexed[(pair["run_id"], "spine")]
        grasu = indexed[(pair["run_id"], "grasu_regraph")]
        unified_pairs.append(
            {
                "run_id": pair["run_id"],
                "dataset_id": pair["dataset_id"],
                "algorithm": algorithm,
                "batch_size": int(pair["user_mutations"]),
                "scenario": pair["scenario"],
                "spine_e2e_ms": spine["e2e_ms"],
                "grasu_e2e_ms": grasu["e2e_ms"],
                "spine_speedup": float(grasu["e2e_ms"])
                / float(spine["e2e_ms"]),
                "cross_system_correct": True,
            }
        )
    return unified_systems, unified_pairs


def _paper_tables(
    pairs: list[dict[str, object]], abbreviation_by_dataset: dict[str, str]
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    correctness_rows: list[dict[str, object]] = []
    algorithm_rows: list[dict[str, object]] = []
    for algorithm, label in ALGORITHM_LABELS.items():
        selected = [row for row in pairs if row["algorithm"] == algorithm]
        if len(selected) != 5 or not all(row["cross_system_correct"] for row in selected):
            raise ValueError(f"{algorithm} paper table lacks five correct pairs")
        correctness_rows.append(
            {"algorithm": label, "real_pairs": len(selected), "synthetic_pairs": 0}
        )
        algorithm_rows.append(
            {
                "algorithm": label,
                "pairs": len(selected),
                "spine_ms": geometric_mean(
                    float(row["spine_e2e_ms"]) for row in selected
                ),
                "grasu_ms": geometric_mean(
                    float(row["grasu_e2e_ms"]) for row in selected
                ),
                "spine_speedup": geometric_mean(
                    float(row["spine_speedup"]) for row in selected
                ),
            }
        )

    dataset_rows: list[dict[str, object]] = []
    for dataset_id, abbreviation in sorted(
        abbreviation_by_dataset.items(), key=lambda item: item[1]
    ):
        row: dict[str, object] = {"dataset": abbreviation, "dataset_id": dataset_id}
        for algorithm in ALGORITHM_LABELS:
            selected = [
                item
                for item in pairs
                if item["dataset_id"] == dataset_id
                and item["algorithm"] == algorithm
            ]
            if len(selected) != 1:
                raise ValueError(f"missing {algorithm}/{dataset_id} paper point")
            row[f"{algorithm}_speedup"] = selected[0]["spine_speedup"]
        dataset_rows.append(row)
    return correctness_rows, algorithm_rows, dataset_rows


def _archive_raw(
    output_path: Path,
    matrix_dirs: dict[str, Path],
    expected_runs: set[str],
) -> None:
    with tarfile.open(output_path, "w:gz") as archive:
        for algorithm, matrix_dir in sorted(matrix_dirs.items()):
            for filename in ("system_rows.csv", "pairs.csv", "matrix_manifest.json"):
                archive.add(
                    matrix_dir / filename, arcname=f"raw/{algorithm}/{filename}"
                )
            for run_id in sorted(expected_runs):
                for system, result_name in (
                    ("spine", "summary.json"),
                    ("grasu_regraph", "manifest.json"),
                ):
                    run_dir = matrix_dir / run_id / system
                    archive.add(
                        run_dir / result_name,
                        arcname=f"raw/{algorithm}/{run_id}/{system}/{result_name}",
                    )
                    for path in sorted(
                        (run_dir / "dram").glob("channel*/dramsim3.json")
                    ):
                        archive.add(
                            path,
                            arcname=(
                                f"raw/{algorithm}/{run_id}/{system}/dram/"
                                f"{path.parent.name}/dramsim3.json"
                            ),
                        )


def analyze_temporal_three_algorithms(
    *,
    matrix_dirs: dict[str, Path],
    input_manifest_path: Path,
    out_dir: Path,
    paper_data_dir: Path | None = None,
) -> dict[str, object]:
    if set(matrix_dirs) != set(ALGORITHM_LABELS):
        raise ValueError("three-algorithm matrix directories are incomplete")
    matrix_dirs = {key: path.resolve() for key, path in matrix_dirs.items()}
    input_manifest_path = input_manifest_path.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    input_manifest = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    expected_runs = _expected_run_ids(input_manifest)
    abbreviation_by_dataset = {
        str(dataset["dataset_id"]): str(dataset["abbreviation"])
        for dataset in input_manifest["datasets"]
    }
    if len(expected_runs) != 5 or len(abbreviation_by_dataset) != 5:
        raise ValueError("temporal input manifest does not contain five datasets")

    systems: list[dict[str, object]] = []
    pairs: list[dict[str, object]] = []
    for algorithm in ALGORITHM_LABELS:
        algorithm_systems, algorithm_pairs = _load_algorithm(
            algorithm=algorithm,
            matrix_dir=matrix_dirs[algorithm],
            expected_runs=expected_runs,
        )
        systems.extend(algorithm_systems)
        pairs.extend(algorithm_pairs)
    correctness, algorithm_summary, dataset_summary = _paper_tables(
        pairs, abbreviation_by_dataset
    )
    _write_csv(out_dir / "system_rows.csv", systems)
    _write_csv(out_dir / "pair_rows.csv", pairs)
    _write_csv(out_dir / "correctness_coverage.csv", correctness)
    _write_csv(out_dir / "e2e_by_algorithm.csv", algorithm_summary)
    _write_csv(out_dir / "e2e_speedup_by_dataset_algorithm.csv", dataset_summary)
    if paper_data_dir is not None:
        paper_data_dir = paper_data_dir.resolve()
        _write_csv(paper_data_dir / "correctness_coverage.csv", correctness)
        _write_csv(paper_data_dir / "e2e_by_algorithm.csv", algorithm_summary)
        _write_csv(
            paper_data_dir / "e2e_speedup_by_dataset_algorithm.csv",
            dataset_summary,
        )

    raw_archive = out_dir / "raw_results.tar.gz"
    _archive_raw(raw_archive, matrix_dirs, expected_runs)
    outputs = [
        out_dir / "system_rows.csv",
        out_dir / "pair_rows.csv",
        out_dir / "correctness_coverage.csv",
        out_dir / "e2e_by_algorithm.csv",
        out_dir / "e2e_speedup_by_dataset_algorithm.csv",
        raw_archive,
    ]
    report = {
        "schema_version": 1,
        "analysis_id": "candidate10_grasu_temporal_three_algorithm_insert_u8_v1_20260727",
        "status": "PASS",
        "algorithms": list(ALGORITHM_LABELS),
        "datasets": sorted(abbreviation_by_dataset),
        "scenario": EXPECTED_SCENARIO,
        "batch_size": EXPECTED_BATCH,
        "pairs": len(pairs),
        "system_rows": len(systems),
        "all_correct": True,
        "dram_request_ledgers_closed": True,
        "phase_aligned_physical_memory_complete": all(
            bool(row["dram_physical_window_aligned"]) for row in systems
        ),
        "input_manifest_sha256": sha256_file(input_manifest_path),
        "source_matrix_manifest_sha256": {
            algorithm: sha256_file(matrix_dir / "matrix_manifest.json")
            for algorithm, matrix_dir in matrix_dirs.items()
        },
        "outputs": {path.name: sha256_file(path) for path in outputs},
        "limitations": [
            "Inputs are 8192-edge compact file-order slices, not full datasets.",
            "The formal cross-algorithm matrix covers insert batches of eight.",
            "Weighted SSSP uses oracle-minimum fixed host supersteps.",
            "Spine weighted-SSSP controller counters include cold initialization, so the phase-aligned physical-memory gate remains open.",
            "DRAM energy covers active channels only and excludes on-chip energy.",
        ],
    }
    (out_dir / "analysis_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _load_verified_analysis_rows(
    evidence_dir: Path,
    system_filename: str,
    pair_filename: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, object]]:
    manifest_path = evidence_dir / "analysis_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    system_path = evidence_dir / system_filename
    pair_path = evidence_dir / pair_filename
    outputs = manifest.get("outputs", {})
    if manifest.get("status") != "PASS" or manifest.get("all_correct") is not True:
        raise ValueError(f"source analysis did not pass: {evidence_dir}")
    if not isinstance(outputs, dict) or (
        outputs.get(system_filename) != sha256_file(system_path)
        or outputs.get(pair_filename) != sha256_file(pair_path)
    ):
        raise ValueError(f"source analysis hash mismatch: {evidence_dir}")
    return _read_csv(system_path), _read_csv(pair_path), manifest


def _expanded_paper_tables(
    pairs: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    correctness: list[dict[str, object]] = []
    batch_rows: list[dict[str, object]] = []
    for algorithm, label in ALGORITHM_LABELS.items():
        selected_algorithm = [row for row in pairs if row["algorithm"] == algorithm]
        if len(selected_algorithm) != 15:
            raise ValueError(f"{algorithm} expanded correctness coverage is incomplete")
        correctness.append(
            {"algorithm": label, "real_pairs": 15, "synthetic_pairs": 0}
        )
        for batch in EXPANDED_BATCHES:
            selected = [
                row
                for row in selected_algorithm
                if int(row["batch_size"]) == batch
            ]
            if len(selected) != 5 or any(
                not bool(row["cross_system_correct"]) for row in selected
            ):
                raise ValueError(f"{algorithm}/batch{batch} lacks five correct pairs")
            spine_ms = geometric_mean(
                float(row["spine_e2e_ms"]) for row in selected
            )
            grasu_ms = geometric_mean(
                float(row["grasu_e2e_ms"]) for row in selected
            )
            batch_rows.append(
                {
                    "algorithm": label,
                    "algorithm_id": algorithm,
                    "batch": batch,
                    "pairs": len(selected),
                    "spine_ms": spine_ms,
                    "grasu_ms": grasu_ms,
                    "spine_speedup": grasu_ms / spine_ms,
                }
            )
    return correctness, batch_rows


def analyze_temporal_expanded_small_batches(
    *,
    baseline_evidence_dir: Path,
    full_pagerank_evidence_dir: Path,
    weighted_gap_dir: Path,
    residual_gap_dir: Path,
    input_manifest_path: Path,
    out_dir: Path,
    paper_data_dir: Path | None = None,
) -> dict[str, object]:
    baseline_evidence_dir = baseline_evidence_dir.resolve()
    full_pagerank_evidence_dir = full_pagerank_evidence_dir.resolve()
    weighted_gap_dir = weighted_gap_dir.resolve()
    residual_gap_dir = residual_gap_dir.resolve()
    input_manifest_path = input_manifest_path.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    input_manifest = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    run_metadata = {
        str(run["run_id"]): run
        for run in input_manifest["runs"]
        if str(run["scenario"]) == EXPECTED_SCENARIO
        and int(run["batch_size"]) in EXPANDED_BATCHES
    }
    expected_by_batch = {
        batch: {
            run_id
            for run_id, run in run_metadata.items()
            if int(run["batch_size"]) == batch
        }
        for batch in EXPANDED_BATCHES
    }
    if any(len(run_ids) != 5 for run_ids in expected_by_batch.values()):
        raise ValueError("input manifest lacks five insert runs per expanded batch")

    baseline_system_raw, baseline_pair_raw, baseline_manifest = (
        _load_verified_analysis_rows(
            baseline_evidence_dir, "system_rows.csv", "pair_rows.csv"
        )
    )
    batch8_runs = expected_by_batch[EXPECTED_BATCH]
    if (
        len(baseline_system_raw) != 30
        or len(baseline_pair_raw) != 15
        or {row["run_id"] for row in baseline_pair_raw} != batch8_runs
    ):
        raise ValueError("three-algorithm batch-8 baseline coverage mismatch")
    systems: list[dict[str, object]] = []
    pairs: list[dict[str, object]] = []
    for row in baseline_system_raw:
        if int(row["correctness_mismatches"]) != 0:
            raise ValueError("incorrect batch-8 baseline row")
        systems.append(
            {
                **row,
                "batch_size": EXPECTED_BATCH,
                "scenario": EXPECTED_SCENARIO,
                "correctness_mismatches": 0,
            }
        )
    for row in baseline_pair_raw:
        if not _bool(row["cross_system_correct"]):
            raise ValueError("incorrect batch-8 baseline pair")
        pairs.append(
            {
                **row,
                "batch_size": EXPECTED_BATCH,
                "scenario": EXPECTED_SCENARIO,
                "cross_system_correct": True,
            }
        )

    gap_runs = expected_by_batch[1] | expected_by_batch[64]
    full_system_raw, full_pair_raw, full_manifest = _load_verified_analysis_rows(
        full_pagerank_evidence_dir,
        "system_rows_enriched.csv",
        "pairs_enriched.csv",
    )
    full_system_raw = [row for row in full_system_raw if row["run_id"] in gap_runs]
    full_pair_raw = [row for row in full_pair_raw if row["run_id"] in gap_runs]
    if len(full_system_raw) != 20 or len(full_pair_raw) != 10:
        raise ValueError("Full PageRank batch-1/64 evidence coverage mismatch")
    if any(int(row["correctness_mismatches"]) != 0 for row in full_system_raw):
        raise ValueError("incorrect Full PageRank expanded row")
    if any(not _bool(row["cross_system_ranks_match"]) for row in full_pair_raw):
        raise ValueError("incorrect Full PageRank expanded pair")
    for row in full_system_raw:
        systems.append(
            {
                **row,
                "batch_size": int(row["user_mutations"]),
                "correctness_mismatches": 0,
            }
        )
    for row in full_pair_raw:
        pairs.append(
            {
                **row,
                "algorithm": "full_pagerank",
                "batch_size": int(row["user_mutations"]),
                "spine_speedup": float(row["spine_speedup_over_grasu_e2e"]),
                "cross_system_correct": True,
            }
        )

    gap_systems: list[dict[str, object]] = []
    gap_pairs: list[dict[str, object]] = []
    gap_dirs = {
        "weighted_sssp": weighted_gap_dir,
        "thresholded_residual_pagerank": residual_gap_dir,
    }
    for algorithm, matrix_dir in gap_dirs.items():
        algorithm_systems, algorithm_pairs = _load_algorithm(
            algorithm=algorithm,
            matrix_dir=matrix_dir,
            expected_runs=gap_runs,
        )
        gap_systems.extend(algorithm_systems)
        gap_pairs.extend(algorithm_pairs)
    systems.extend(gap_systems)
    pairs.extend(gap_pairs)

    expected_keys = {
        (algorithm, run_id)
        for algorithm in ALGORITHM_LABELS
        for run_id in run_metadata
    }
    observed_pair_keys = {
        (str(row["algorithm"]), str(row["run_id"])) for row in pairs
    }
    if observed_pair_keys != expected_keys or len(pairs) != 45 or len(systems) != 90:
        raise ValueError("expanded three-algorithm small-batch matrix is incomplete")
    correctness, batch_rows = _expanded_paper_tables(pairs)

    system_path = out_dir / "expanded_system_rows.csv"
    pair_path = out_dir / "expanded_pairs.csv"
    gap_system_path = out_dir / "gap_system_rows.csv"
    gap_pair_path = out_dir / "gap_pairs.csv"
    correctness_path = out_dir / "correctness_coverage.csv"
    batch_path = out_dir / "small_batch_by_algorithm.csv"
    _write_csv(system_path, systems)
    _write_csv(pair_path, pairs)
    _write_csv(gap_system_path, gap_systems)
    _write_csv(gap_pair_path, gap_pairs)
    _write_csv(correctness_path, correctness)
    _write_csv(batch_path, batch_rows)
    if paper_data_dir is not None:
        paper_data_dir = paper_data_dir.resolve()
        _write_csv(paper_data_dir / "correctness_coverage.csv", correctness)
        _write_csv(paper_data_dir / "small_batch_by_algorithm.csv", batch_rows)

    raw_archive = out_dir / "gap_raw_results.tar.gz"
    _archive_raw(raw_archive, gap_dirs, gap_runs)
    outputs = (
        system_path,
        pair_path,
        gap_system_path,
        gap_pair_path,
        correctness_path,
        batch_path,
        raw_archive,
    )
    report = {
        "schema_version": 1,
        "analysis_id": "candidate10_temporal_three_algorithm_small_batches_v1_20260727",
        "status": "PASS",
        "algorithms": list(ALGORITHM_LABELS),
        "batch_sizes": list(EXPANDED_BATCHES),
        "scenario": EXPECTED_SCENARIO,
        "datasets": sorted({str(row["dataset_id"]) for row in pairs}),
        "pairs": len(pairs),
        "system_rows": len(systems),
        "all_correct": True,
        "dram_request_ledgers_closed": True,
        "input_manifest_sha256": sha256_file(input_manifest_path),
        "baseline_analysis_manifest_sha256": sha256_file(
            baseline_evidence_dir / "analysis_manifest.json"
        ),
        "full_pagerank_analysis_manifest_sha256": sha256_file(
            full_pagerank_evidence_dir / "analysis_manifest.json"
        ),
        "baseline_outputs": baseline_manifest["outputs"],
        "full_pagerank_outputs": full_manifest["outputs"],
        "gap_matrix_manifest_sha256": {
            algorithm: sha256_file(matrix_dir / "matrix_manifest.json")
            for algorithm, matrix_dir in gap_dirs.items()
        },
        "outputs": {path.name: sha256_file(path) for path in outputs},
        "limitations": [
            "Inputs are 8192-edge compact file-order slices, not full datasets.",
            "The expanded cross-algorithm matrix covers insertion only.",
            "Weighted SSSP uses oracle-minimum fixed host supersteps.",
            "All inputs remain within one normalized destination partition.",
        ],
    }
    (out_dir / "analysis_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
