"""Fail-closed analysis for the GraSU temporal real-slice comparison."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import fmean
import tarfile
from typing import Iterable

from .comparison_analysis import aggregate_dram_stats, geometric_mean, sha256_file


EXPECTED_SCENARIOS = {"insert", "delete", "mixed"}
DIFFERENTIAL_SCENARIOS = (*sorted(EXPECTED_SCENARIOS), "weight_change")
EXPECTED_ALGORITHM = "full_pagerank"
EXPECTED_BATCH = 8
SMALL_BATCHES = {1, 8, 64}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "true"
    return bool(value)


def _enrich_system_rows(
    matrix_dir: Path, rows: list[dict[str, str]]
) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for row in rows:
        dram = aggregate_dram_stats(
            matrix_dir / row["run_id"] / row["system"] / "dram"
        )
        backend_requests = int(row["backend_requests"])
        if int(dram["requests"]) != backend_requests:
            raise ValueError(f"DRAM request ledger mismatch for {row['run_id']}/{row['system']}")
        if int(dram["reads"]) != int(row["dram_reads"]):
            raise ValueError(f"DRAM read mismatch for {row['run_id']}/{row['system']}")
        if int(dram["writes"]) != int(row["dram_writes"]):
            raise ValueError(f"DRAM write mismatch for {row['run_id']}/{row['system']}")
        enriched.append(
            {
                **row,
                "dram_controller_channels": int(dram["channels"]),
                "dram_read_row_hits": int(dram["read_row_hits"]),
                "dram_write_row_hits": int(dram["write_row_hits"]),
                "dram_row_hit_rate": float(dram["row_hit_rate"]),
                "dram_average_read_latency": float(dram["average_read_latency"]),
                "dram_average_write_latency": float(dram["average_write_latency"]),
                "dram_write_latency_coverage": float(dram["write_latency_coverage"]),
            }
        )
    return enriched


def _pair_enriched_rows(
    pair_rows: list[dict[str, str]], system_rows: list[dict[str, object]]
) -> list[dict[str, object]]:
    indexed = {
        (str(row["run_id"]), str(row["system"])): row for row in system_rows
    }
    enriched: list[dict[str, object]] = []
    for pair in pair_rows:
        run_id = pair["run_id"]
        spine = indexed[(run_id, "spine")]
        grasu = indexed[(run_id, "grasu_regraph")]
        if not _bool(pair["cross_system_ranks_match"]):
            raise ValueError(f"cross-system rank mismatch for {run_id}")
        enriched.append(
            {
                **pair,
                "spine_dram_row_hit_rate": spine["dram_row_hit_rate"],
                "grasu_dram_row_hit_rate": grasu["dram_row_hit_rate"],
                "spine_dram_average_read_latency": spine[
                    "dram_average_read_latency"
                ],
                "grasu_dram_average_read_latency": grasu[
                    "dram_average_read_latency"
                ],
                "grasu_to_spine_dram_request_ratio": float(
                    grasu["backend_requests"]
                )
                / float(spine["backend_requests"]),
                "spine_dram_activates": int(spine["dram_activates"]),
                "grasu_dram_activates": int(grasu["dram_activates"]),
            }
        )
    return enriched


def _summary_row(
    group_type: str, group: str, rows: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "group_type": group_type,
        "group": group,
        "pairs": len(rows),
        "spine_wins": sum(
            float(row["spine_speedup_over_grasu_e2e"]) > 1.0 for row in rows
        ),
        "spine_e2e_ms_geomean": geometric_mean(
            float(row["spine_e2e_ms"]) for row in rows
        ),
        "grasu_e2e_ms_geomean": geometric_mean(
            float(row["grasu_e2e_ms"]) for row in rows
        ),
        "spine_speedup_e2e_geomean": geometric_mean(
            float(row["spine_speedup_over_grasu_e2e"]) for row in rows
        ),
        "spine_speedup_update_geomean": geometric_mean(
            float(row["spine_speedup_over_grasu_update"]) for row in rows
        ),
        "spine_speedup_compute_geomean": geometric_mean(
            float(row["spine_speedup_over_grasu_compute"]) for row in rows
        ),
        "grasu_to_spine_backend_requests_geomean": geometric_mean(
            float(row["grasu_to_spine_backend_request_ratio"]) for row in rows
        ),
        "grasu_to_spine_backend_bytes_geomean": geometric_mean(
            float(row["grasu_to_spine_backend_byte_ratio"]) for row in rows
        ),
        "spine_dram_row_hit_rate_mean": fmean(
            float(row["spine_dram_row_hit_rate"]) for row in rows
        ),
        "grasu_dram_row_hit_rate_mean": fmean(
            float(row["grasu_dram_row_hit_rate"]) for row in rows
        ),
        "spine_dram_read_latency_mean": fmean(
            float(row["spine_dram_average_read_latency"]) for row in rows
        ),
        "grasu_dram_read_latency_mean": fmean(
            float(row["grasu_dram_average_read_latency"]) for row in rows
        ),
    }


def _group_summaries(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    summaries = [_summary_row("all", "all", rows)]
    for group_type, key in (("dataset", "dataset_id"), ("scenario", "scenario")):
        values = sorted({str(row[key]) for row in rows})
        for value in values:
            summaries.append(
                _summary_row(
                    group_type, value, [row for row in rows if row[key] == value]
                )
            )
    return summaries


def _archive_raw(matrix_dir: Path, output_path: Path, run_ids: Iterable[str]) -> None:
    with tarfile.open(output_path, "w:gz") as archive:
        for filename in ("system_rows.csv", "pairs.csv", "matrix_manifest.json"):
            archive.add(matrix_dir / filename, arcname=f"raw/{filename}")
        for run_id in sorted(run_ids):
            for system, result_name in (
                ("spine", "summary.json"),
                ("grasu_regraph", "manifest.json"),
            ):
                run_dir = matrix_dir / run_id / system
                archive.add(
                    run_dir / result_name,
                    arcname=f"raw/{run_id}/{system}/{result_name}",
                )
                for path in sorted((run_dir / "dram").glob("channel*/dramsim3.json")):
                    channel = path.parent.name
                    archive.add(
                        path,
                        arcname=f"raw/{run_id}/{system}/dram/{channel}/dramsim3.json",
                    )


def analyze_temporal_full_pagerank(
    *,
    matrix_dir: Path,
    input_manifest_path: Path,
    out_dir: Path,
    paper_data_dir: Path | None = None,
) -> dict[str, object]:
    matrix_dir = matrix_dir.resolve()
    input_manifest_path = input_manifest_path.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix_manifest = json.loads(
        (matrix_dir / "matrix_manifest.json").read_text(encoding="utf-8")
    )
    input_manifest = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    system_rows = _read_csv(matrix_dir / "system_rows.csv")
    pair_rows = _read_csv(matrix_dir / "pairs.csv")
    expected_runs = {
        run["run_id"]
        for run in input_manifest["runs"]
        if int(run["batch_size"]) == EXPECTED_BATCH
        and run["scenario"] in EXPECTED_SCENARIOS
    }
    actual_runs = {row["run_id"] for row in pair_rows}
    datasets = {row["dataset_id"] for row in pair_rows}
    if matrix_manifest.get("status") != "PASS" or not matrix_manifest.get("all_correct"):
        raise ValueError("source matrix did not pass its correctness gate")
    if actual_runs != expected_runs or len(pair_rows) != 15 or len(system_rows) != 30:
        raise ValueError("temporal batch-8 matrix coverage is incomplete")
    if len(datasets) != 5 or {row["scenario"] for row in pair_rows} != EXPECTED_SCENARIOS:
        raise ValueError("temporal dataset/scenario coverage is incomplete")
    if any(int(row["correctness_mismatches"]) != 0 for row in system_rows):
        raise ValueError("incorrect system row entered temporal analysis")

    enriched_system = _enrich_system_rows(matrix_dir, system_rows)
    enriched_pairs = _pair_enriched_rows(pair_rows, enriched_system)
    summaries = _group_summaries(enriched_pairs)
    _write_csv(out_dir / "system_rows_enriched.csv", enriched_system)
    _write_csv(out_dir / "pairs_enriched.csv", enriched_pairs)
    _write_csv(out_dir / "group_summary.csv", summaries)

    abbreviation_by_dataset = {
        dataset["dataset_id"]: dataset["abbreviation"]
        for dataset in input_manifest["datasets"]
    }
    e2e_rows: list[dict[str, object]] = []
    for dataset_id in sorted(datasets, key=lambda item: abbreviation_by_dataset[item]):
        rows = [row for row in enriched_pairs if row["dataset_id"] == dataset_id]
        spine_ms = geometric_mean(float(row["spine_e2e_ms"]) for row in rows)
        grasu_ms = geometric_mean(float(row["grasu_e2e_ms"]) for row in rows)
        e2e_rows.append(
            {
                "dataset": abbreviation_by_dataset[dataset_id],
                "dataset_id": dataset_id,
                "algorithm": EXPECTED_ALGORITHM,
                "batch": EXPECTED_BATCH,
                "scenarios": len(rows),
                "spine_ms": spine_ms,
                "grasu_ms": grasu_ms,
                "spine_norm": spine_ms / grasu_ms,
                "grasu_norm": 1.0,
                "spine_speedup": grasu_ms / spine_ms,
            }
        )
    _write_csv(out_dir / "e2e_by_dataset.csv", e2e_rows)
    if paper_data_dir is not None:
        _write_csv(paper_data_dir.resolve() / "e2e_by_dataset.csv", e2e_rows)

    raw_archive = out_dir / "raw_results.tar.gz"
    _archive_raw(matrix_dir, raw_archive, expected_runs)
    outputs = [
        out_dir / "system_rows_enriched.csv",
        out_dir / "pairs_enriched.csv",
        out_dir / "group_summary.csv",
        out_dir / "e2e_by_dataset.csv",
        raw_archive,
    ]
    report = {
        "schema_version": 1,
        "analysis_id": "candidate10_grasu_temporal_full_pr_batch8_v1_20260727",
        "status": "PASS",
        "algorithm": EXPECTED_ALGORITHM,
        "batch_size": EXPECTED_BATCH,
        "datasets": sorted(datasets),
        "scenarios": sorted(EXPECTED_SCENARIOS),
        "system_rows": len(enriched_system),
        "pairs": len(enriched_pairs),
        "all_correct": True,
        "dram_request_ledgers_closed": True,
        "input_manifest_sha256": sha256_file(input_manifest_path),
        "source_matrix_manifest_sha256": sha256_file(
            matrix_dir / "matrix_manifest.json"
        ),
        "outputs": {path.name: sha256_file(path) for path in outputs},
        "headline": summaries[0],
        "limitations": input_manifest["limitations"],
    }
    (out_dir / "analysis_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _small_batch_expected_runs(input_manifest: dict[str, object]) -> set[str]:
    return {
        str(run["run_id"])
        for run in input_manifest["runs"]  # type: ignore[index]
        if int(run["batch_size"]) in SMALL_BATCHES
        and str(run["scenario"]) in EXPECTED_SCENARIOS
    }


def _small_batch_paper_rows(
    system_rows: list[dict[str, object]], pair_rows: list[dict[str, object]]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    throughput_rows: list[dict[str, object]] = []
    e2e_rows: list[dict[str, object]] = []
    for batch in sorted(SMALL_BATCHES):
        systems = [row for row in system_rows if int(row["user_mutations"]) == batch]
        pairs = [row for row in pair_rows if int(row["user_mutations"]) == batch]
        spine = [row for row in systems if row["system"] == "spine"]
        grasu = [row for row in systems if row["system"] == "grasu_regraph"]
        if not pairs or len(spine) != len(pairs) or len(grasu) != len(pairs):
            raise ValueError(f"incomplete small-batch pairing for batch {batch}")
        spine_mups = geometric_mean(
            float(row["user_mutations_per_second_update"]) for row in spine
        ) / 1.0e6
        grasu_mups = geometric_mean(
            float(row["user_mutations_per_second_update"]) for row in grasu
        ) / 1.0e6
        spine_ms = geometric_mean(float(row["e2e_ms"]) for row in spine)
        grasu_ms = geometric_mean(float(row["e2e_ms"]) for row in grasu)
        throughput_rows.append(
            {
                "batch": batch,
                "pairs": len(pairs),
                "spine_mups": spine_mups,
                "grasu_mups": grasu_mups,
                "spine_speedup": spine_mups / grasu_mups,
            }
        )
        e2e_rows.append(
            {
                "batch": batch,
                "pairs": len(pairs),
                "spine_ms": spine_ms,
                "grasu_ms": grasu_ms,
                "spine_norm": spine_ms / grasu_ms,
                "grasu_norm": 1.0,
                "spine_speedup": grasu_ms / spine_ms,
            }
        )
    return throughput_rows, e2e_rows


def analyze_temporal_small_batch_pagerank(
    *,
    matrix_dir: Path,
    input_manifest_path: Path,
    out_dir: Path,
    paper_data_dir: Path | None = None,
) -> dict[str, object]:
    matrix_dir = matrix_dir.resolve()
    input_manifest_path = input_manifest_path.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    matrix_manifest = json.loads(
        (matrix_dir / "matrix_manifest.json").read_text(encoding="utf-8")
    )
    input_manifest = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    system_rows = _read_csv(matrix_dir / "system_rows.csv")
    pair_rows = _read_csv(matrix_dir / "pairs.csv")
    expected_runs = _small_batch_expected_runs(input_manifest)
    actual_runs = {row["run_id"] for row in pair_rows}
    if matrix_manifest.get("status") != "PASS" or not matrix_manifest.get("all_correct"):
        raise ValueError("source small-batch matrix did not pass correctness")
    if actual_runs != expected_runs or len(pair_rows) != 40 or len(system_rows) != 80:
        raise ValueError("temporal Full PageRank small-batch matrix is incomplete")
    if any(int(row["correctness_mismatches"]) != 0 for row in system_rows):
        raise ValueError("incorrect system row entered small-batch analysis")

    enriched_system = _enrich_system_rows(matrix_dir, system_rows)
    enriched_pairs = _pair_enriched_rows(pair_rows, enriched_system)
    throughput_rows, e2e_rows = _small_batch_paper_rows(
        enriched_system, enriched_pairs
    )
    _write_csv(out_dir / "system_rows_enriched.csv", enriched_system)
    _write_csv(out_dir / "pairs_enriched.csv", enriched_pairs)
    _write_csv(out_dir / "update_throughput.csv", throughput_rows)
    _write_csv(out_dir / "e2e_by_batch.csv", e2e_rows)
    if paper_data_dir is not None:
        paper_data_dir = paper_data_dir.resolve()
        _write_csv(paper_data_dir / "update_throughput.csv", throughput_rows)
        _write_csv(paper_data_dir / "e2e_by_batch.csv", e2e_rows)

    raw_archive = out_dir / "raw_results.tar.gz"
    _archive_raw(matrix_dir, raw_archive, expected_runs)
    outputs = [
        out_dir / "system_rows_enriched.csv",
        out_dir / "pairs_enriched.csv",
        out_dir / "update_throughput.csv",
        out_dir / "e2e_by_batch.csv",
        raw_archive,
    ]
    report = {
        "schema_version": 1,
        "analysis_id": "candidate10_grasu_temporal_full_pr_small_batch_v1_20260727",
        "status": "PASS",
        "algorithm": EXPECTED_ALGORITHM,
        "batch_sizes": sorted(SMALL_BATCHES),
        "datasets": sorted({row["dataset_id"] for row in pair_rows}),
        "pairs": len(enriched_pairs),
        "system_rows": len(enriched_system),
        "all_correct": True,
        "dram_request_ledgers_closed": True,
        "input_manifest_sha256": sha256_file(input_manifest_path),
        "source_matrix_manifest_sha256": sha256_file(
            matrix_dir / "matrix_manifest.json"
        ),
        "outputs": {path.name: sha256_file(path) for path in outputs},
        "limitations": input_manifest["limitations"],
    }
    (out_dir / "analysis_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def _validate_update_shape(row: dict[str, object]) -> None:
    scenario = str(row["scenario"])
    user_mutations = int(row["user_mutations"])
    physical_records = int(row["physical_records"])
    initial_edges = int(row["initial_edges"])
    final_edges = int(row["final_edges"])
    expected = {
        "insert": (user_mutations, user_mutations),
        "delete": (user_mutations, -user_mutations),
        "mixed": (user_mutations, 0),
        "weight_change": (2 * user_mutations, 0),
    }
    if scenario not in expected:
        raise ValueError(f"unsupported differential scenario: {scenario}")
    expected_records, expected_edge_delta = expected[scenario]
    if physical_records != expected_records or final_edges - initial_edges != expected_edge_delta:
        raise ValueError(f"invalid {scenario} update shape for {row['run_id']}")


def _differential_scenario_rows(
    system_rows: list[dict[str, object]], pair_rows: list[dict[str, object]]
) -> list[dict[str, object]]:
    labels = {
        "insert": "Insert",
        "delete": "Delete",
        "mixed": "Mixed",
        "weight_change": "Weight-chg",
    }
    rows: list[dict[str, object]] = []
    for scenario in DIFFERENTIAL_SCENARIOS:
        systems = [row for row in system_rows if row["scenario"] == scenario]
        pairs = [row for row in pair_rows if row["scenario"] == scenario]
        spine = [row for row in systems if row["system"] == "spine"]
        grasu = [row for row in systems if row["system"] == "grasu_regraph"]
        if len(pairs) != 5 or len(spine) != 5 or len(grasu) != 5:
            raise ValueError(f"incomplete five-dataset differential scenario: {scenario}")
        if any(not _bool(row["cross_system_ranks_match"]) for row in pairs):
            raise ValueError(f"incorrect differential pair: {scenario}")
        spine_mups = geometric_mean(
            float(row["user_mutations_per_second_update"]) for row in spine
        ) / 1.0e6
        grasu_mups = geometric_mean(
            float(row["user_mutations_per_second_update"]) for row in grasu
        ) / 1.0e6
        spine_e2e_ms = geometric_mean(float(row["e2e_ms"]) for row in spine)
        grasu_e2e_ms = geometric_mean(float(row["e2e_ms"]) for row in grasu)
        rows.append(
            {
                "scenario": labels[scenario],
                "scenario_id": scenario,
                "pairs": len(pairs),
                "physical_records_per_user_mutation": fmean(
                    float(row["physical_records"]) / float(row["user_mutations"])
                    for row in spine
                ),
                "spine_mups": spine_mups,
                "grasu_mups": grasu_mups,
                "spine_update_speedup": spine_mups / grasu_mups,
                "spine_e2e_ms": spine_e2e_ms,
                "grasu_e2e_ms": grasu_e2e_ms,
                "spine_e2e_norm": spine_e2e_ms / grasu_e2e_ms,
                "grasu_e2e_norm": 1.0,
                "spine_e2e_speedup": grasu_e2e_ms / spine_e2e_ms,
            }
        )
    return rows


def _validated_baseline_differential_rows(
    evidence_dir: Path,
    expected_runs: set[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    manifest_path = evidence_dir / "analysis_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    system_path = evidence_dir / "system_rows_enriched.csv"
    pair_path = evidence_dir / "pairs_enriched.csv"
    if (
        manifest.get("status") != "PASS"
        or manifest.get("all_correct") is not True
        or set(manifest.get("scenarios", [])) != EXPECTED_SCENARIOS
        or int(manifest.get("batch_size", -1)) != EXPECTED_BATCH
    ):
        raise ValueError("baseline differential evidence did not pass")
    outputs = manifest.get("outputs", {})
    if not isinstance(outputs, dict) or (
        outputs.get(system_path.name) != sha256_file(system_path)
        or outputs.get(pair_path.name) != sha256_file(pair_path)
    ):
        raise ValueError("baseline differential evidence hash mismatch")
    systems = [dict(row) for row in _read_csv(system_path)]
    pairs = [dict(row) for row in _read_csv(pair_path)]
    if (
        {str(row["run_id"]) for row in pairs} != expected_runs
        or len(pairs) != 15
        or len(systems) != 30
    ):
        raise ValueError("baseline differential evidence coverage mismatch")
    if any(int(row["correctness_mismatches"]) != 0 for row in systems):
        raise ValueError("incorrect baseline differential system row")
    if any(not _bool(row["cross_system_ranks_match"]) for row in pairs):
        raise ValueError("incorrect baseline differential pair")
    return systems, pairs, manifest


def analyze_temporal_differential_pagerank(
    *,
    baseline_evidence_dir: Path,
    weight_change_matrix_dir: Path,
    input_manifest_path: Path,
    out_dir: Path,
    paper_data_dir: Path | None = None,
) -> dict[str, object]:
    baseline_evidence_dir = baseline_evidence_dir.resolve()
    weight_change_matrix_dir = weight_change_matrix_dir.resolve()
    input_manifest_path = input_manifest_path.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    input_manifest = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    expected = {
        scenario: {
            str(run["run_id"])
            for run in input_manifest["runs"]
            if str(run["scenario"]) == scenario
            and int(run["batch_size"]) == EXPECTED_BATCH
        }
        for scenario in DIFFERENTIAL_SCENARIOS
    }
    if any(len(run_ids) != 5 for run_ids in expected.values()):
        raise ValueError("input manifest lacks five runs for each differential scenario")

    baseline_runs = set().union(*(expected[item] for item in EXPECTED_SCENARIOS))
    baseline_systems, baseline_pairs, baseline_manifest = (
        _validated_baseline_differential_rows(
            baseline_evidence_dir, baseline_runs
        )
    )

    matrix_manifest_path = weight_change_matrix_dir / "matrix_manifest.json"
    matrix_manifest = json.loads(matrix_manifest_path.read_text(encoding="utf-8"))
    system_path = weight_change_matrix_dir / "system_rows.csv"
    pair_path = weight_change_matrix_dir / "pairs.csv"
    if matrix_manifest.get("status") != "PASS" or matrix_manifest.get("all_correct") is not True:
        raise ValueError("weight-change source matrix did not pass correctness")
    if (
        matrix_manifest.get("system_rows_sha256") != sha256_file(system_path)
        or matrix_manifest.get("pairs_sha256") != sha256_file(pair_path)
    ):
        raise ValueError("weight-change source matrix hash mismatch")
    weight_run_ids = expected["weight_change"]
    weight_systems_raw = [
        row for row in _read_csv(system_path) if row["run_id"] in weight_run_ids
    ]
    weight_pairs_raw = [
        row for row in _read_csv(pair_path) if row["run_id"] in weight_run_ids
    ]
    if (
        {row["run_id"] for row in weight_pairs_raw} != weight_run_ids
        or len(weight_pairs_raw) != 5
        or len(weight_systems_raw) != 10
    ):
        raise ValueError("weight-change five-dataset coverage mismatch")
    if any(int(row["correctness_mismatches"]) != 0 for row in weight_systems_raw):
        raise ValueError("incorrect weight-change system row")
    if any(not _bool(row["cross_system_ranks_match"]) for row in weight_pairs_raw):
        raise ValueError("incorrect weight-change pair")

    weight_systems = _enrich_system_rows(
        weight_change_matrix_dir, weight_systems_raw
    )
    weight_pairs = _pair_enriched_rows(weight_pairs_raw, weight_systems)
    systems = [*baseline_systems, *weight_systems]
    pairs = [*baseline_pairs, *weight_pairs]
    expected_all = set().union(*expected.values())
    if {str(row["run_id"]) for row in pairs} != expected_all or len(pairs) != 20:
        raise ValueError("combined differential matrix is incomplete")
    for row in systems:
        _validate_update_shape(row)
    scenario_rows = _differential_scenario_rows(systems, pairs)

    system_output = out_dir / "differential_system_rows.csv"
    pair_output = out_dir / "differential_pairs.csv"
    weight_system_output = out_dir / "weight_change_system_rows.csv"
    weight_pair_output = out_dir / "weight_change_pairs.csv"
    scenario_output = out_dir / "differential_by_scenario.csv"
    _write_csv(system_output, systems)
    _write_csv(pair_output, pairs)
    _write_csv(weight_system_output, weight_systems)
    _write_csv(weight_pair_output, weight_pairs)
    _write_csv(scenario_output, scenario_rows)
    if paper_data_dir is not None:
        _write_csv(
            paper_data_dir.resolve() / "differential_by_scenario.csv",
            scenario_rows,
        )
    raw_archive = out_dir / "weight_change_raw_results.tar.gz"
    _archive_raw(weight_change_matrix_dir, raw_archive, weight_run_ids)
    outputs = (
        system_output,
        pair_output,
        weight_system_output,
        weight_pair_output,
        scenario_output,
        raw_archive,
    )
    report = {
        "schema_version": 1,
        "analysis_id": "candidate10_temporal_full_pr_differential_u8_v1_20260727",
        "status": "PASS",
        "algorithm": EXPECTED_ALGORITHM,
        "batch_size": EXPECTED_BATCH,
        "scenarios": list(DIFFERENTIAL_SCENARIOS),
        "datasets": sorted({str(row["dataset_id"]) for row in pairs}),
        "pairs": len(pairs),
        "system_rows": len(systems),
        "all_correct": True,
        "all_update_shapes_valid": True,
        "dram_request_ledgers_closed": True,
        "input_manifest_sha256": sha256_file(input_manifest_path),
        "baseline_analysis_manifest_sha256": sha256_file(
            baseline_evidence_dir / "analysis_manifest.json"
        ),
        "baseline_outputs": baseline_manifest["outputs"],
        "weight_change_matrix_manifest_sha256": sha256_file(matrix_manifest_path),
        "outputs": {path.name: sha256_file(path) for path in outputs},
        "limitations": [
            "Inputs are compact slices, not complete GraSU datasets.",
            "Delete, mixed, and weight-change batches are derived from real topology.",
            "Weight changes are lowered into exact delete-old then insert-new records.",
            "Reported update throughput counts successful user mutations, not lowered physical records.",
        ],
    }
    (out_dir / "analysis_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
