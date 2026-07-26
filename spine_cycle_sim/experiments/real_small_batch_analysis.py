"""Cross-algorithm analysis for frozen Candidate10 real small-batch matrices."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import median
from typing import Iterable, Mapping

from .comparison_analysis import geometric_mean, sha256_file


ALGORITHMS = (
    "weighted_sssp",
    "full_pagerank",
    "thresholded_residual_pagerank",
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty table: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _float(row: Mapping[str, object], key: str) -> float:
    return float(row[key])


def normalize_system_row(
    row: Mapping[str, object], algorithm: str
) -> dict[str, object]:
    if algorithm not in ALGORITHMS:
        raise ValueError(f"unsupported algorithm: {algorithm}")
    core_mhz = _float(row, "core_mhz")
    if algorithm == "weighted_sssp":
        e2e_ms = _float(row, "aligned_e2e_ms")
        update_ms = _float(row, "structure_update_cycles") / (core_mhz * 1_000.0)
        backend_requests = int(row["aligned_backend_requests"])
        backend_bytes = int(row["aligned_backend_bytes"])
        discontinuous_ratio = float(
            row.get("aligned_backend_discontinuous_request_ratio", 0.0) or 0.0
        )
    else:
        e2e_ms = _float(row, "e2e_ms")
        update_ms = _float(row, "update_ms")
        backend_requests = int(row["backend_requests"])
        backend_bytes = int(row["backend_bytes"])
        discontinuous_ratio = float(
            row.get("backend_discontinuous_request_ratio", 0.0) or 0.0
        )
    compute_ms = e2e_ms - update_ms
    if e2e_ms <= 0.0 or update_ms <= 0.0 or compute_ms <= 0.0:
        raise ValueError(f"invalid phase window for {row['run_id']}/{row['system']}")
    mismatches = int(row["correctness_mismatches"])
    if mismatches:
        raise ValueError(f"correctness mismatch for {row['run_id']}/{row['system']}")
    user_mutations = int(row["user_mutations"])
    physical_records = int(row["physical_records"])
    return {
        "run_id": row["run_id"],
        "dataset_id": row["dataset_id"],
        "scenario": row["scenario"],
        "algorithm": algorithm,
        "system": row["system"],
        "profile_id": row["profile_id"],
        "core_mhz": core_mhz,
        "vertices": int(row["vertices"]),
        "initial_edges": int(row["initial_edges"]),
        "user_mutations": user_mutations,
        "physical_records": physical_records,
        "e2e_ms": e2e_ms,
        "update_ms": update_ms,
        "compute_ms": compute_ms,
        "user_mutations_per_second_update": user_mutations / (update_ms / 1_000.0),
        "physical_records_per_second_update": physical_records
        / (update_ms / 1_000.0),
        "backend_requests": backend_requests,
        "backend_bytes": backend_bytes,
        "backend_discontinuous_request_ratio": discontinuous_ratio,
        "correctness_mismatches": mismatches,
        "claim_class": "candidate10_hls_v3_normalized_execution_driven",
    }


def build_pair_rows(
    system_rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    by_identity: dict[tuple[str, str], dict[str, Mapping[str, object]]] = {}
    for row in system_rows:
        identity = (str(row["run_id"]), str(row["algorithm"]))
        by_identity.setdefault(identity, {})[str(row["system"])] = row
    pairs: list[dict[str, object]] = []
    for (run_id, algorithm), systems in sorted(by_identity.items()):
        if set(systems) != {"spine", "grasu_regraph"}:
            raise ValueError(f"unpaired system rows: {run_id}/{algorithm}")
        spine = systems["spine"]
        grasu = systems["grasu_regraph"]
        if any(
            spine[key] != grasu[key]
            for key in ("dataset_id", "scenario", "user_mutations", "physical_records")
        ):
            raise ValueError(f"pair contract mismatch: {run_id}/{algorithm}")
        pairs.append(
            {
                "run_id": run_id,
                "dataset_id": spine["dataset_id"],
                "scenario": spine["scenario"],
                "algorithm": algorithm,
                "user_mutations": spine["user_mutations"],
                "physical_records": spine["physical_records"],
                "spine_e2e_ms": spine["e2e_ms"],
                "grasu_regraph_e2e_ms": grasu["e2e_ms"],
                "spine_speedup_over_grasu_e2e": _float(grasu, "e2e_ms")
                / _float(spine, "e2e_ms"),
                "spine_update_ms": spine["update_ms"],
                "grasu_regraph_update_ms": grasu["update_ms"],
                "spine_speedup_over_grasu_update": _float(grasu, "update_ms")
                / _float(spine, "update_ms"),
                "spine_compute_ms": spine["compute_ms"],
                "grasu_regraph_compute_ms": grasu["compute_ms"],
                "spine_speedup_over_grasu_compute": _float(grasu, "compute_ms")
                / _float(spine, "compute_ms"),
                "grasu_to_spine_backend_request_ratio": _float(
                    grasu, "backend_requests"
                )
                / _float(spine, "backend_requests"),
                "grasu_to_spine_backend_byte_ratio": _float(grasu, "backend_bytes")
                / _float(spine, "backend_bytes"),
                "correctness": "dual_oracle_and_cross_system_pass",
                "claim_class": "candidate10_hls_v3_normalized_execution_driven",
            }
        )
    return pairs


def summarize_pairs(pairs: list[Mapping[str, object]]) -> list[dict[str, object]]:
    groups = [("overall", "all")]
    for key in ("algorithm", "dataset_id", "scenario"):
        groups.extend((key, value) for value in sorted({str(row[key]) for row in pairs}))
    summaries: list[dict[str, object]] = []
    for group_type, group_value in groups:
        selected = (
            pairs
            if group_type == "overall"
            else [row for row in pairs if str(row[group_type]) == group_value]
        )
        e2e = [_float(row, "spine_speedup_over_grasu_e2e") for row in selected]
        update = [_float(row, "spine_speedup_over_grasu_update") for row in selected]
        compute = [_float(row, "spine_speedup_over_grasu_compute") for row in selected]
        requests = [
            _float(row, "grasu_to_spine_backend_request_ratio") for row in selected
        ]
        summaries.append(
            {
                "group_type": group_type,
                "group_value": group_value,
                "pairs": len(selected),
                "spine_e2e_wins": sum(value > 1.0 for value in e2e),
                "spine_speedup_over_grasu_e2e_geomean": geometric_mean(e2e),
                "spine_speedup_over_grasu_e2e_median": median(e2e),
                "spine_speedup_over_grasu_update_geomean": geometric_mean(update),
                "spine_speedup_over_grasu_compute_geomean": geometric_mean(compute),
                "grasu_to_spine_backend_request_ratio_geomean": geometric_mean(
                    requests
                ),
            }
        )
    return summaries


def analyze_real_small_batches(
    matrix_dirs: Mapping[str, Path], output_dir: Path
) -> dict[str, object]:
    if set(matrix_dirs) != set(ALGORITHMS):
        raise ValueError("one matrix directory is required for each algorithm")
    system_rows: list[dict[str, object]] = []
    source_evidence: dict[str, object] = {}
    for algorithm in ALGORITHMS:
        matrix_dir = matrix_dirs[algorithm].resolve()
        manifest_path = matrix_dir / "matrix_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not (
            manifest.get("status") == "PASS"
            and manifest.get("complete_matrix") is True
            and manifest.get("all_correct") is True
            and manifest.get("profile_set") == "candidate10_hls_v3"
            and int(manifest.get("system_rows", 0)) == 18
            and int(manifest.get("pairs", 0)) == 9
        ):
            raise ValueError(f"incomplete Candidate10 v3 matrix: {algorithm}")
        for name in ("system_rows.csv", "pairs.csv"):
            if sha256_file(matrix_dir / name) != manifest[f"{name[:-4]}_sha256"]:
                raise ValueError(f"matrix output hash mismatch: {algorithm}/{name}")
        rows = _read_csv(matrix_dir / "system_rows.csv")
        system_rows.extend(normalize_system_row(row, algorithm) for row in rows)
        pair_rows = _read_csv(matrix_dir / "pairs.csv")
        cross_keys = {
            "weighted_sssp": "cross_system_distances_match",
            "full_pagerank": "cross_system_ranks_match",
            "thresholded_residual_pagerank": "cross_system_state_match",
        }
        if not all(row[cross_keys[algorithm]] == "True" for row in pair_rows):
            raise ValueError(f"cross-system correctness failed: {algorithm}")
        source_evidence[algorithm] = {
            "matrix_manifest": str(manifest_path),
            "matrix_manifest_sha256": sha256_file(manifest_path),
            "matrix_wall_seconds": float(manifest["matrix_wall_seconds"]),
        }
    pairs = build_pair_rows(system_rows)
    summaries = summarize_pairs(pairs)
    if len(system_rows) != 54 or len(pairs) != 27:
        raise ValueError("combined matrix does not contain 54 rows and 27 pairs")
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(output_dir / "system_rows.csv", system_rows)
    _write_csv(output_dir / "pair_rows.csv", pairs)
    _write_csv(output_dir / "group_summary.csv", summaries)
    result = {
        "schema_version": 1,
        "status": "PASS",
        "profile_set": "candidate10_hls_v3",
        "algorithms": list(ALGORITHMS),
        "system_rows": len(system_rows),
        "pairs": len(pairs),
        "all_correct": True,
        "correctness": "dual_oracle_and_cross_system_pass_for_every_pair",
        "timing_claim": "normalized_execution_driven_simulator_cycles",
        "throughput_scope": "eight_user_mutation_small_batches",
        "source_evidence": source_evidence,
        "group_summary": summaries,
        "outputs": {
            name: sha256_file(output_dir / name)
            for name in ("system_rows.csv", "pair_rows.csv", "group_summary.csv")
        },
    }
    (output_dir / "analysis_manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
