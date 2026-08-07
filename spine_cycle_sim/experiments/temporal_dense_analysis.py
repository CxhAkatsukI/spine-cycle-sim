"""Dense Full PageRank analysis on three GraSU temporal real slices."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import tarfile

from .comparison_analysis import geometric_mean, sha256_file
from .temporal_real_analysis import _enrich_system_rows, _pair_enriched_rows


DENSE_BATCHES = {64, 512, 4096}
DENSE_DATASETS = {"AU", "WK", "BC"}
BASE_EDGES = 8192


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty dense table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def _dense_expected_runs(input_manifest: dict[str, object]) -> set[str]:
    return {
        str(run["run_id"])
        for run in input_manifest["runs"]  # type: ignore[index]
        if run["dataset_abbreviation"] in DENSE_DATASETS
        and run["scenario"] == "insert"
        and int(run["batch_size"]) in DENSE_BATCHES
    }


def _dense_paper_rows(
    pairs: list[dict[str, object]], abbreviation_by_dataset: dict[str, str]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for batch in sorted(DENSE_BATCHES):
        selected = [row for row in pairs if int(row["user_mutations"]) == batch]
        if len(selected) != len(DENSE_DATASETS):
            raise ValueError(f"dense batch {batch} lacks three topology pairs")
        by_abbreviation = {
            abbreviation_by_dataset[str(row["dataset_id"])]: row for row in selected
        }
        if set(by_abbreviation) != DENSE_DATASETS:
            raise ValueError(f"dense batch {batch} topology set is incomplete")
        rows.append(
            {
                "batch": batch,
                "base_edges": BASE_EDGES,
                "update_ratio": batch / BASE_EDGES,
                "AU_speedup": by_abbreviation["AU"][
                    "spine_speedup_over_grasu_e2e"
                ],
                "WK_speedup": by_abbreviation["WK"][
                    "spine_speedup_over_grasu_e2e"
                ],
                "BC_speedup": by_abbreviation["BC"][
                    "spine_speedup_over_grasu_e2e"
                ],
                "geomean_speedup": geometric_mean(
                    float(row["spine_speedup_over_grasu_e2e"])
                    for row in selected
                ),
                "spine_e2e_ms": geometric_mean(
                    float(row["spine_e2e_ms"]) for row in selected
                ),
                "grasu_e2e_ms": geometric_mean(
                    float(row["grasu_e2e_ms"]) for row in selected
                ),
            }
        )
    return rows


def _archive_raw(matrix_dir: Path, output_path: Path, run_ids: set[str]) -> None:
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
                    archive.add(
                        path,
                        arcname=(
                            f"raw/{run_id}/{system}/dram/"
                            f"{path.parent.name}/dramsim3.json"
                        ),
                    )


def analyze_temporal_dense_pagerank(
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
    expected_runs = _dense_expected_runs(input_manifest)
    system_rows = _read_csv(matrix_dir / "system_rows.csv")
    pair_rows = _read_csv(matrix_dir / "pairs.csv")
    if matrix_manifest.get("status") != "PASS" or not matrix_manifest.get("all_correct"):
        raise ValueError("source real-dense matrix did not pass correctness")
    if {row["run_id"] for row in pair_rows} != expected_runs:
        raise ValueError("real-dense pair coverage is incomplete")
    if len(expected_runs) != 9 or len(pair_rows) != 9 or len(system_rows) != 18:
        raise ValueError("real-dense matrix row count is incomplete")
    if any(int(row["correctness_mismatches"]) != 0 for row in system_rows):
        raise ValueError("incorrect row entered real-dense analysis")

    enriched_systems = _enrich_system_rows(matrix_dir, system_rows)
    enriched_pairs = _pair_enriched_rows(pair_rows, enriched_systems)
    abbreviation_by_dataset = {
        str(dataset["dataset_id"]): str(dataset["abbreviation"])
        for dataset in input_manifest["datasets"]
    }
    dense_rows = _dense_paper_rows(enriched_pairs, abbreviation_by_dataset)
    _write_csv(out_dir / "system_rows_enriched.csv", enriched_systems)
    _write_csv(out_dir / "pairs_enriched.csv", enriched_pairs)
    _write_csv(out_dir / "dense_batch.csv", dense_rows)
    if paper_data_dir is not None:
        _write_csv(paper_data_dir.resolve() / "dense_batch.csv", dense_rows)

    raw_archive = out_dir / "raw_results.tar.gz"
    _archive_raw(matrix_dir, raw_archive, expected_runs)
    outputs = [
        out_dir / "system_rows_enriched.csv",
        out_dir / "pairs_enriched.csv",
        out_dir / "dense_batch.csv",
        raw_archive,
    ]
    report = {
        "schema_version": 1,
        "analysis_id": "candidate10_grasu_temporal_real_dense_full_pr_v1_20260727",
        "status": "PASS",
        "algorithm": "full_pagerank",
        "datasets": sorted(DENSE_DATASETS),
        "batch_sizes": sorted(DENSE_BATCHES),
        "base_edges": BASE_EDGES,
        "pairs": len(enriched_pairs),
        "system_rows": len(enriched_systems),
        "all_correct": True,
        "dram_request_ledgers_closed": True,
        "input_manifest_sha256": sha256_file(input_manifest_path),
        "source_matrix_manifest_sha256": sha256_file(
            matrix_dir / "matrix_manifest.json"
        ),
        "outputs": {path.name: sha256_file(path) for path in outputs},
        "limitations": [
            "Inputs are compact real-topology slices, not full datasets.",
            "The sweep uses Full PageRank and insertion batches only.",
            "The largest batch updates 50 percent as many edges as the base graph.",
            "All inputs fit one normalized destination partition.",
        ],
    }
    (out_dir / "analysis_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
