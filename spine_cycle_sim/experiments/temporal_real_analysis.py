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
EXPECTED_ALGORITHM = "full_pagerank"
EXPECTED_BATCH = 8


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
