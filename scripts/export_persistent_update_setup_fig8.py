#!/usr/bin/env python3
"""Export setup-inclusive update-only rows for evaluation-refresh Fig. 8."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs" / "evidence" / "persistent_update_campaign_20260731"
CROSS_FILENAME = "persistent_update_setup_cross_dataset.csv"
BATCH_FILENAME = "persistent_update_setup_batch_sensitivity.csv"
MANIFEST_FILENAME = "persistent_update_setup_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="") as sink:
        writer = csv.DictWriter(sink, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_mapping(values: list[str], default: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    if not values:
        return default
    parsed = []
    for value in values:
        if ":" not in value:
            raise ValueError(f"mapping must be key:label, got {value!r}")
        key, label = value.split(":", 1)
        if not key or not label:
            raise ValueError(f"mapping must be key:label, got {value!r}")
        parsed.append((key, label))
    return tuple(parsed)


def systems(comparison: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if comparison.get("experiment") != "persistent_trace_aware_update_only":
        raise ValueError("comparison is not persistent update-only evidence")
    if comparison.get("correctness") != "pass":
        raise ValueError("comparison did not pass correctness")
    by_system = {row["system"]: row for row in comparison["rows"]}
    return by_system["spine"], by_system["grasu_regraph"]


def kups(row: dict[str, Any]) -> float:
    return float(row["modeled_host_inclusive_updates_per_second"]) / 1_000.0


def cross_rows(evidence_root: Path, mapping: tuple[tuple[str, str], ...]) -> tuple[list[dict[str, Any]], list[Path]]:
    rows = []
    sources = []
    for key, label in mapping:
        path = evidence_root / "cross_dataset" / key / "comparison.json"
        comparison = load_json(path)
        spine, grasu = systems(comparison)
        rows.append(
            {
                "dataset": label,
                "logical_updates": int(comparison["logical_updates"]),
                "batch_count": int(comparison["batch_count"]),
                "spine_kups": kups(spine),
                "grasu_kups": kups(grasu),
                "spine_speedup": float(
                    comparison["spine_speedup"]["modeled_host_inclusive"]
                ),
            }
        )
        sources.append(path)
    return rows, sources


def batch_rows(evidence_root: Path, batch_counts: tuple[int, ...]) -> tuple[list[dict[str, Any]], list[Path]]:
    rows = []
    sources = []
    for batch_count in batch_counts:
        path = evidence_root / "batch_sensitivity" / f"b{batch_count}" / "comparison.json"
        comparison = load_json(path)
        spine, grasu = systems(comparison)
        logical_updates = int(comparison["logical_updates"])
        actual_batch_count = int(comparison["batch_count"])
        rows.append(
            {
                "batch_count": actual_batch_count,
                "updates_per_batch": logical_updates / actual_batch_count,
                "logical_updates": logical_updates,
                "spine_kups": kups(spine),
                "grasu_kups": kups(grasu),
                "spine_speedup": float(
                    comparison["spine_speedup"]["modeled_host_inclusive"]
                ),
            }
        )
        sources.append(path)
    return rows, sources


def validate_current_case_manifests(
    comparison_paths: list[Path],
) -> tuple[list[Path], dict[str, str]]:
    manifests: list[Path] = []
    identities: set[tuple[str, ...]] = set()
    for comparison_path in comparison_paths:
        manifest_path = comparison_path.with_name("manifest.json")
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"current Fig. 8 case manifest is missing: {manifest_path}"
            )
        manifest = load_json(manifest_path)
        if manifest.get("status") != "PASS":
            raise ValueError(f"current Fig. 8 case did not pass: {manifest_path}")
        if manifest.get("timing_boundary") != (
            "measured_host_preprocessing_plus_explicit_transfer_launch_model_"
            "plus_frozen_calibrated_persistent_device_cycles"
        ):
            raise ValueError(
                f"current Fig. 8 timing boundary mismatch: {manifest_path}"
            )
        identity = tuple(
            str(manifest.get(field, ""))
            for field in (
                "spine_sst_plugin_sha256",
                "grasu_sst_plugin_sha256",
                "case_contract_sha256",
                "spine_calibration_contract_sha256",
                "grasu_calibration_contract_sha256",
                "spine_frozen_mechanism_model_sha256",
                "grasu_frozen_persistent_update_model_sha256",
            )
        )
        if not all(identity):
            raise ValueError(
                f"current Fig. 8 case has incomplete frozen identity: {manifest_path}"
            )
        identities.add(identity)
        manifests.append(manifest_path)
    if len(identities) != 1:
        raise ValueError("current Fig. 8 cases do not share one frozen identity")
    (
        spine_plugin,
        grasu_plugin,
        cases,
        spine_calibration,
        grasu_calibration,
        spine_frozen_model,
        grasu_frozen_model,
    ) = next(iter(identities))
    return list(dict.fromkeys(manifests)), {
        "spine_sst_plugin_sha256": spine_plugin,
        "grasu_sst_plugin_sha256": grasu_plugin,
        "case_contract_sha256": cases,
        "spine_calibration_contract_sha256": spine_calibration,
        "grasu_calibration_contract_sha256": grasu_calibration,
        "spine_frozen_mechanism_model_sha256": spine_frozen_model,
        "grasu_frozen_persistent_update_model_sha256": grasu_frozen_model,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--cross-dataset",
        action="append",
        default=[],
        help="repeat key:label entries, default au/su/wk/so/pk",
    )
    parser.add_argument(
        "--batch-count",
        action="append",
        type=int,
        default=[],
        help="repeat batch counts, default 1000/100/10",
    )
    parser.add_argument(
        "--status",
        choices=(
            "PASS_CURRENT_MODEL_DATA",
            "PARTIAL_CURRENT_MODEL_DATA",
            "INTERIM_ARCHIVED_SIMULATOR_DATA",
        ),
        default="INTERIM_ARCHIVED_SIMULATOR_DATA",
        help="evidence status to record in the generated manifest",
    )
    args = parser.parse_args()
    evidence_root = args.evidence_root.resolve()
    mapping = parse_mapping(
        args.cross_dataset,
        (("au", "AU"), ("su", "SU"), ("wk", "WK"), ("so", "SO"), ("pk", "PK")),
    )
    batches = tuple(args.batch_count) if args.batch_count else (1000, 100, 10)
    if any(batch <= 0 for batch in batches):
        raise ValueError("batch counts must be positive")

    cross, cross_sources = cross_rows(evidence_root, mapping)
    batch, batch_sources = batch_rows(evidence_root, batches)
    sources = list(dict.fromkeys(cross_sources + batch_sources))
    case_manifests: list[Path] = []
    frozen_identity: dict[str, str] | None = None
    if args.status == "PASS_CURRENT_MODEL_DATA":
        case_manifests, frozen_identity = validate_current_case_manifests(sources)
    out_dir = args.out_dir.resolve()
    write_csv(out_dir / CROSS_FILENAME, cross)
    write_csv(out_dir / BATCH_FILENAME, batch)
    manifest = {
        "schema_version": 1,
        "status": args.status,
        "metric": "setup_inclusive_update_only_throughput",
        "evidence_root": str(evidence_root),
        "cross_datasets": [
            {"key": key, "label": label} for key, label in mapping
        ],
        "batch_counts": list(batches),
        "source_files": [
            {"path": str(path), "sha256": sha256(path)} for path in sources
        ],
        "case_manifests": [
            {"path": str(path), "sha256": sha256(path)}
            for path in case_manifests
        ],
        "frozen_identity": frozen_identity,
        "output_files": {
            CROSS_FILENAME: sha256(out_dir / CROSS_FILENAME),
            BATCH_FILENAME: sha256(out_dir / BATCH_FILENAME),
        },
    }
    (out_dir / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"FIG8_UPDATE_ONLY_EXPORT status={args.status} "
        f"cross={len(cross)} batch={len(batch)} out={out_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
