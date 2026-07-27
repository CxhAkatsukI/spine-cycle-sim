"""Normalize real-matrix memory evidence across algorithms and systems."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Mapping, Sequence


ALGORITHMS = (
    "weighted_sssp",
    "full_pagerank",
    "thresholded_residual_pagerank",
)
ALGORITHM_LABELS = {
    "weighted_sssp": "SSSP",
    "full_pagerank": "Full PR",
    "thresholded_residual_pagerank": "Residual PR",
}
SYSTEMS = ("spine", "grasu_regraph")
LOCALITY_CATEGORIES = ("first", "contiguous", "repeated", "discontinuous")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integer(row: Mapping[str, str], key: str) -> int:
    raw = row.get(key, "")
    if raw == "":
        raise ValueError(f"missing integer field: {key}")
    value = int(raw)
    if value < 0:
        raise ValueError(f"negative integer field: {key}")
    return value


def _float(row: Mapping[str, str], key: str) -> float:
    raw = row.get(key, "")
    if raw == "":
        raise ValueError(f"missing float field: {key}")
    value = float(raw)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"invalid float field: {key}")
    return value


def _prefix_metrics(
    row: Mapping[str, str], prefix: str
) -> dict[str, int | float]:
    metrics: dict[str, int | float] = {
        "requests": _integer(row, f"{prefix}_requests"),
        "bytes": _integer(row, f"{prefix}_bytes"),
        "nominal_64b_bytes": _integer(row, f"{prefix}_nominal_64b_bytes"),
        "read_requests": _integer(row, f"{prefix}_read_requests"),
        "read_bytes": _integer(row, f"{prefix}_read_bytes"),
        "write_requests": _integer(row, f"{prefix}_write_requests"),
        "write_bytes": _integer(row, f"{prefix}_write_bytes"),
    }
    for category in LOCALITY_CATEGORIES:
        metrics[f"{category}_requests"] = _integer(
            row, f"{prefix}_{category}_requests"
        )
        metrics[f"{category}_bytes"] = _integer(
            row, f"{prefix}_{category}_bytes"
        )
    for category in ("contiguous", "repeated", "discontinuous"):
        metrics[f"{category}_request_ratio"] = _float(
            row, f"{prefix}_{category}_request_ratio"
        )
        metrics[f"{category}_byte_ratio"] = _float(
            row, f"{prefix}_{category}_byte_ratio"
        )

    if metrics["requests"] != (
        metrics["read_requests"] + metrics["write_requests"]
    ) or metrics["bytes"] != metrics["read_bytes"] + metrics["write_bytes"]:
        raise ValueError(f"{prefix} read/write traffic does not close")
    if metrics["requests"] != sum(
        int(metrics[f"{category}_requests"])
        for category in LOCALITY_CATEGORIES
    ) or metrics["bytes"] != sum(
        int(metrics[f"{category}_bytes"])
        for category in LOCALITY_CATEGORIES
    ):
        raise ValueError(f"{prefix} locality traffic does not close")
    if metrics["nominal_64b_bytes"] != metrics["requests"] * 64:
        raise ValueError(f"{prefix} nominal-byte ledger does not close")
    return metrics


def normalize_system_row(
    algorithm: str, row: Mapping[str, str]
) -> dict[str, object]:
    if algorithm not in ALGORITHMS:
        raise ValueError(f"unsupported algorithm: {algorithm}")
    system = row.get("system")
    if system not in SYSTEMS:
        raise ValueError(f"unsupported system: {system}")

    if algorithm == "weighted_sssp":
        e2e_ms = _float(row, "aligned_e2e_ms")
        total_prefix = "aligned_backend" if system == "spine" else "backend"
        phase_split = "aligned_total_only" if system == "spine" else "update_compute"
    else:
        e2e_ms = _float(row, "e2e_ms")
        total_prefix = "backend"
        phase_split = "update_compute"

    normalized: dict[str, object] = {
        "algorithm": algorithm,
        "run_id": row["run_id"],
        "dataset_id": row["dataset_id"],
        "scenario": row["scenario"],
        "system": system,
        "e2e_ms": e2e_ms,
        "timed_memory_scope": (
            "dynamic_update_and_compute_excluding_cold"
            if algorithm == "weighted_sssp"
            else "dynamic_update_and_compute"
        ),
        "phase_split": phase_split,
        **_prefix_metrics(row, total_prefix),
    }

    if phase_split == "update_compute":
        for phase in ("update", "compute"):
            phase_metrics = _prefix_metrics(row, f"{phase}_backend")
            normalized.update(
                {f"{phase}_{key}": value for key, value in phase_metrics.items()}
            )
        for field in ("requests", "bytes", "read_bytes", "write_bytes"):
            if normalized[field] != (
                normalized[f"update_{field}"] + normalized[f"compute_{field}"]
            ):
                raise ValueError(f"{algorithm}/{system} phase {field} does not close")
    return normalized


def load_matrix(
    algorithm: str, directory: Path
) -> tuple[dict[str, object], list[dict[str, object]]]:
    manifest_path = directory / "matrix_manifest.json"
    rows_path = directory / "system_rows.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("status") != "PASS"
        or manifest.get("complete_matrix") is not True
        or manifest.get("all_correct") is not True
    ):
        raise ValueError(f"matrix is not complete and correct: {directory}")
    if manifest.get("system_rows_sha256") != sha256_file(rows_path):
        raise ValueError(f"system-row hash mismatch: {directory}")
    with rows_path.open(encoding="utf-8", newline="") as stream:
        rows = [normalize_system_row(algorithm, row) for row in csv.DictReader(stream)]
    if len(rows) != int(manifest["system_rows"]):
        raise ValueError(f"system-row count mismatch: {directory}")
    return manifest, rows


def _bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() == "true"


def _pair_correct(algorithm: str, row: Mapping[str, str]) -> bool:
    key = {
        "weighted_sssp": "cross_system_distances_match",
        "full_pagerank": "cross_system_ranks_match",
        "thresholded_residual_pagerank": "cross_system_state_match",
    }[algorithm]
    return _bool(row.get(key, False))


def load_selected_matrix(
    algorithm: str,
    directory: Path,
    expected_run_ids: set[str],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Load an explicitly frozen correct subset from a larger PASS matrix."""

    if algorithm not in ALGORITHMS:
        raise ValueError(f"unsupported algorithm: {algorithm}")
    if not expected_run_ids:
        raise ValueError("expected run IDs must not be empty")
    manifest_path = directory / "matrix_manifest.json"
    rows_path = directory / "system_rows.csv"
    pairs_path = directory / "pairs.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "PASS" or manifest.get("all_correct") is not True:
        raise ValueError(f"matrix did not pass correctness: {directory}")
    if manifest.get("system_rows_sha256") != sha256_file(rows_path):
        raise ValueError(f"system-row hash mismatch: {directory}")
    if manifest.get("pairs_sha256") != sha256_file(pairs_path):
        raise ValueError(f"pair-row hash mismatch: {directory}")

    with rows_path.open(encoding="utf-8", newline="") as stream:
        source_rows = [
            row for row in csv.DictReader(stream) if row["run_id"] in expected_run_ids
        ]
    observed_keys = [(row["run_id"], row["system"]) for row in source_rows]
    expected_keys = {
        (run_id, system) for run_id in expected_run_ids for system in SYSTEMS
    }
    if len(observed_keys) != len(set(observed_keys)):
        raise ValueError(f"duplicate selected system row: {directory}")
    if set(observed_keys) != expected_keys:
        raise ValueError(f"selected system-row coverage mismatch: {directory}")
    if any(int(row.get("correctness_mismatches", "0")) != 0 for row in source_rows):
        raise ValueError(f"incorrect selected system row: {directory}")

    with pairs_path.open(encoding="utf-8", newline="") as stream:
        pair_rows = [
            row for row in csv.DictReader(stream) if row["run_id"] in expected_run_ids
        ]
    if len(pair_rows) != len(expected_run_ids) or {
        row["run_id"] for row in pair_rows
    } != expected_run_ids:
        raise ValueError(f"selected pair coverage mismatch: {directory}")
    if any(not _pair_correct(algorithm, row) for row in pair_rows):
        raise ValueError(f"selected cross-system result mismatch: {directory}")

    rows = [normalize_system_row(algorithm, row) for row in source_rows]
    return manifest, rows


def pair_memory_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], dict[str, Mapping[str, object]]] = {}
    for row in rows:
        key = (str(row["algorithm"]), str(row["run_id"]))
        grouped.setdefault(key, {})[str(row["system"])] = row

    pairs: list[dict[str, object]] = []
    for (algorithm, run_id), systems in sorted(grouped.items()):
        if set(systems) != set(SYSTEMS):
            raise ValueError(f"incomplete architecture pair: {algorithm}/{run_id}")
        spine = systems["spine"]
        grasu = systems["grasu_regraph"]
        pairs.append(
            {
                "algorithm": algorithm,
                "run_id": run_id,
                "dataset_id": spine["dataset_id"],
                "scenario": spine["scenario"],
                "spine_e2e_ms": spine["e2e_ms"],
                "grasu_e2e_ms": grasu["e2e_ms"],
                "spine_speedup_over_grasu": float(grasu["e2e_ms"])
                / float(spine["e2e_ms"]),
                "grasu_to_spine_request_ratio": int(grasu["requests"])
                / int(spine["requests"]),
                "grasu_to_spine_byte_ratio": int(grasu["bytes"])
                / int(spine["bytes"]),
                "spine_bytes": spine["bytes"],
                "grasu_bytes": grasu["bytes"],
                "spine_classified_bytes": int(spine["bytes"])
                - int(spine["first_bytes"]),
                "grasu_classified_bytes": int(grasu["bytes"])
                - int(grasu["first_bytes"]),
                "spine_contiguous_bytes": spine["contiguous_bytes"],
                "grasu_contiguous_bytes": grasu["contiguous_bytes"],
                "spine_repeated_bytes": spine["repeated_bytes"],
                "grasu_repeated_bytes": grasu["repeated_bytes"],
                "spine_discontinuous_bytes": spine["discontinuous_bytes"],
                "grasu_discontinuous_bytes": grasu["discontinuous_bytes"],
                "spine_contiguous_byte_ratio": spine[
                    "contiguous_byte_ratio"
                ],
                "spine_discontinuous_byte_ratio": spine[
                    "discontinuous_byte_ratio"
                ],
                "grasu_contiguous_byte_ratio": grasu[
                    "contiguous_byte_ratio"
                ],
                "grasu_discontinuous_byte_ratio": grasu[
                    "discontinuous_byte_ratio"
                ],
            }
        )
    return pairs


def geometric_mean(values: Sequence[float]) -> float:
    if not values or any(value <= 0.0 or not math.isfinite(value) for value in values):
        raise ValueError("geometric mean requires finite positive values")
    return math.exp(sum(math.log(value) for value in values) / len(values))


def summarize_pairs(pairs: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for algorithm in ALGORITHMS:
        selected = [row for row in pairs if row["algorithm"] == algorithm]
        if not selected:
            continue
        spine_classified_bytes = sum(
            int(row["spine_classified_bytes"]) for row in selected
        )
        grasu_classified_bytes = sum(
            int(row["grasu_classified_bytes"]) for row in selected
        )
        if spine_classified_bytes <= 0 or grasu_classified_bytes <= 0:
            raise ValueError(f"{algorithm} has no classified locality bytes")
        summaries.append(
            {
                "algorithm": algorithm,
                "pairs": len(selected),
                "spine_e2e_wins": sum(
                    float(row["spine_speedup_over_grasu"]) > 1.0
                    for row in selected
                ),
                "spine_speedup_geomean": geometric_mean(
                    [float(row["spine_speedup_over_grasu"]) for row in selected]
                ),
                "grasu_to_spine_request_ratio_geomean": geometric_mean(
                    [float(row["grasu_to_spine_request_ratio"]) for row in selected]
                ),
                "grasu_to_spine_byte_ratio_geomean": geometric_mean(
                    [float(row["grasu_to_spine_byte_ratio"]) for row in selected]
                ),
                "spine_requested_bytes": sum(
                    int(row["spine_bytes"]) for row in selected
                ),
                "grasu_requested_bytes": sum(
                    int(row["grasu_bytes"]) for row in selected
                ),
                "spine_contiguous_byte_ratio_aggregate": sum(
                    int(row["spine_contiguous_bytes"]) for row in selected
                )
                / spine_classified_bytes,
                "spine_repeated_byte_ratio_aggregate": sum(
                    int(row["spine_repeated_bytes"]) for row in selected
                )
                / spine_classified_bytes,
                "spine_discontinuous_byte_ratio_aggregate": sum(
                    int(row["spine_discontinuous_bytes"]) for row in selected
                )
                / spine_classified_bytes,
                "grasu_contiguous_byte_ratio_aggregate": sum(
                    int(row["grasu_contiguous_bytes"]) for row in selected
                )
                / grasu_classified_bytes,
                "grasu_repeated_byte_ratio_aggregate": sum(
                    int(row["grasu_repeated_bytes"]) for row in selected
                )
                / grasu_classified_bytes,
                "grasu_discontinuous_byte_ratio_aggregate": sum(
                    int(row["grasu_discontinuous_bytes"]) for row in selected
                )
                / grasu_classified_bytes,
            }
        )
    return summaries


def paper_memory_rows(
    summaries: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Produce compact, explicitly logical request metrics for paper plots."""

    indexed = {str(row["algorithm"]): row for row in summaries}
    if set(indexed) != set(ALGORITHMS):
        raise ValueError("paper memory table requires all three algorithms")
    rows: list[dict[str, object]] = []
    for algorithm in ALGORITHMS:
        summary = indexed[algorithm]
        pairs = int(summary["pairs"])
        if pairs <= 0:
            raise ValueError(f"{algorithm} has no memory pairs")
        rows.append(
            {
                "algorithm": ALGORITHM_LABELS[algorithm],
                "spine_bytes": float(summary["spine_requested_bytes"]) / pairs,
                "grasu_bytes": float(summary["grasu_requested_bytes"]) / pairs,
                "spine_discontinuous": summary[
                    "spine_discontinuous_byte_ratio_aggregate"
                ],
                "grasu_discontinuous": summary[
                    "grasu_discontinuous_byte_ratio_aggregate"
                ],
                "spine_contiguous": summary[
                    "spine_contiguous_byte_ratio_aggregate"
                ],
                "grasu_contiguous": summary[
                    "grasu_contiguous_byte_ratio_aggregate"
                ],
            }
        )
    return rows
