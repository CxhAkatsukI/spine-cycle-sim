"""Fail-closed Candidate10 routed-HLS feasibility evidence ledger."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any


RESOURCE_KEYS = ("lut", "reg", "bram", "uram", "dsp")
ALGORITHMS = (
    "weighted_sssp",
    "full_pagerank",
    "thresholded_residual_pagerank",
)


class PublicationPpaError(ValueError):
    """Raised when publication PPA evidence is incomplete or inconsistent."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise PublicationPpaError(f"missing evidence file: {path}")
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    if not rows:
        raise PublicationPpaError(f"empty evidence table: {path}")
    return rows


def _evidence_path(root: Path, entry: object, label: str) -> Path:
    if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
        raise PublicationPpaError(f"{label} must contain path and sha256")
    path_value = entry["path"]
    digest = entry["sha256"]
    if not isinstance(path_value, str) or not isinstance(digest, str):
        raise PublicationPpaError(f"{label} path and sha256 must be strings")
    path = Path(path_value)
    path = path if path.is_absolute() else root / path
    if not path.is_file():
        raise PublicationPpaError(f"missing {label}: {path}")
    actual = _sha256(path)
    if actual != digest:
        raise PublicationPpaError(
            f"{label} SHA256 mismatch: expected {digest}, got {actual}"
        )
    return path


def _single_row(rows: list[dict[str, str]], label: str) -> dict[str, str]:
    if len(rows) != 1:
        raise PublicationPpaError(f"{label} must have exactly one row")
    return rows[0]


def _as_int(value: str, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise PublicationPpaError(f"{label} is not an integer: {value!r}") from error
    if result < 0:
        raise PublicationPpaError(f"{label} must be non-negative")
    return result


def _as_float(value: str, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise PublicationPpaError(f"{label} is not numeric: {value!r}") from error


def _parse_build(root: Path, build: object) -> dict[str, Any]:
    if not isinstance(build, dict):
        raise PublicationPpaError("build entry must be an object")
    build_id = build.get("build_id")
    if not isinstance(build_id, str) or not build_id:
        raise PublicationPpaError("build_id must be a non-empty string")
    system = build.get("system")
    algorithm = build.get("algorithm")
    if system not in {"spine", "grasu_regraph"}:
        raise PublicationPpaError(f"{build_id}: unsupported system {system!r}")
    if algorithm not in ALGORITHMS:
        raise PublicationPpaError(f"{build_id}: unsupported algorithm {algorithm!r}")
    target_mhz = build.get("target_mhz")
    if not isinstance(target_mhz, (int, float)) or target_mhz <= 0:
        raise PublicationPpaError(f"{build_id}: target_mhz must be positive")

    evidence = build.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != {
        "accelerator_util",
        "artifacts",
        "timing",
    }:
        raise PublicationPpaError(f"{build_id}: incomplete evidence tables")
    utilization_path = _evidence_path(
        root, evidence["accelerator_util"], f"{build_id}.accelerator_util"
    )
    timing_path = _evidence_path(root, evidence["timing"], f"{build_id}.timing")
    artifacts_path = _evidence_path(
        root, evidence["artifacts"], f"{build_id}.artifacts"
    )

    used_rows = [
        row for row in _read_tsv(utilization_path) if row.get("name") == "Used Resources"
    ]
    used = _single_row(used_rows, f"{build_id}.Used Resources")
    if used.get("stage") != "routed":
        raise PublicationPpaError(f"{build_id}: utilization is not routed")
    resources = {
        resource: _as_int(used.get(resource, ""), f"{build_id}.{resource}")
        for resource in RESOURCE_KEYS
    }

    timing = _single_row(_read_tsv(timing_path), f"{build_id}.timing")
    wns_ns = _as_float(timing.get("wns_ns", ""), f"{build_id}.wns_ns")
    tns_ns = _as_float(timing.get("tns_ns", ""), f"{build_id}.tns_ns")
    failing_endpoints = _as_int(
        timing.get("tns_failing_endpoints", ""),
        f"{build_id}.tns_failing_endpoints",
    )
    timing_closed = wns_ns >= 0.0 and tns_ns >= 0.0 and failing_endpoints == 0
    timing_disposition = "target_closed" if timing_closed else "routed_target_missed"
    target_period_ns = 1000.0 / float(target_mhz)
    worst_path_period_ns = target_period_ns - wns_ns

    artifact = _single_row(_read_tsv(artifacts_path), f"{build_id}.artifacts")
    artifact_sha256 = artifact.get("sha256", "")
    expected_artifact_sha256 = build.get("artifact_sha256")
    if artifact_sha256 != expected_artifact_sha256:
        raise PublicationPpaError(
            f"{build_id}: xclbin SHA256 mismatch: expected "
            f"{expected_artifact_sha256}, got {artifact_sha256}"
        )

    expected = build.get("expected")
    if not isinstance(expected, dict):
        raise PublicationPpaError(f"{build_id}: missing expected values")
    expected_resources = expected.get("resources")
    if expected_resources != resources:
        raise PublicationPpaError(
            f"{build_id}: resources differ from frozen expectation"
        )
    if _as_float(str(expected.get("wns_ns")), f"{build_id}.expected.wns_ns") != wns_ns:
        raise PublicationPpaError(f"{build_id}: WNS differs from frozen expectation")
    if expected.get("timing_disposition") != timing_disposition:
        raise PublicationPpaError(
            f"{build_id}: timing disposition differs from frozen expectation"
        )

    claim_scope = build.get("claim_scope")
    if claim_scope not in {
        "spine_core_sssp_baseline",
        "algorithm_specific_conversion_free_whole_system",
    }:
        raise PublicationPpaError(f"{build_id}: unsafe claim_scope")
    source = build.get("source")
    if not isinstance(source, dict) or not source.get("revision"):
        raise PublicationPpaError(f"{build_id}: source revision is required")

    return {
        "build_id": build_id,
        "system": system,
        "algorithm": algorithm,
        "claim_scope": claim_scope,
        "source": source,
        "target_mhz": float(target_mhz),
        "resources": resources,
        "timing": {
            "wns_ns": wns_ns,
            "tns_ns": tns_ns,
            "failing_endpoints": failing_endpoints,
            "disposition": timing_disposition,
            "target_period_ns": target_period_ns,
            "worst_path_period_ns": worst_path_period_ns,
            "worst_path_frequency_mhz": 1000.0 / worst_path_period_ns,
        },
        "artifact": {
            "path_from_build_root": artifact.get("path_from_build_root", ""),
            "size_bytes": _as_int(
                artifact.get("size_bytes", ""), f"{build_id}.artifact.size_bytes"
            ),
            "sha256": artifact_sha256,
        },
    }


def analyze_publication_ppa_manifest(manifest_path: str | Path) -> dict[str, Any]:
    """Validate Candidate10 routed evidence without implying iso-functional PPA."""

    path = Path(manifest_path).resolve()
    manifest_bytes = path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as error:
        raise PublicationPpaError(f"invalid manifest: {path}") from error
    if manifest.get("schema_version") != 1:
        raise PublicationPpaError("only schema_version=1 is supported")
    if manifest.get("claim_class") != "candidate10_routed_hls_feasibility_non_iso_functional":
        raise PublicationPpaError("unsafe or unsupported claim_class")
    repository_root = manifest.get("repository_root")
    if not isinstance(repository_root, str) or not repository_root:
        raise PublicationPpaError("repository_root is required")
    root = (path.parent / repository_root).resolve()

    raw_builds = manifest.get("builds")
    if not isinstance(raw_builds, list) or not raw_builds:
        raise PublicationPpaError("manifest has no builds")
    builds = [_parse_build(root, build) for build in raw_builds]
    build_ids = [build["build_id"] for build in builds]
    if len(set(build_ids)) != len(build_ids):
        raise PublicationPpaError("duplicate build_id")

    grasu_algorithms = {
        build["algorithm"] for build in builds if build["system"] == "grasu_regraph"
    }
    if grasu_algorithms != set(ALGORITHMS):
        raise PublicationPpaError(
            "GraSU+ReGraph routed evidence must cover all three algorithms"
        )
    spine_builds = [build for build in builds if build["system"] == "spine"]
    if len(spine_builds) != 1 or spine_builds[0]["claim_scope"] != "spine_core_sssp_baseline":
        raise PublicationPpaError("exactly one Spine core/SSSP baseline is required")
    if any(build["target_mhz"] != 150.0 for build in builds):
        raise PublicationPpaError("Candidate10 PPA evidence must target 150 MHz")

    return {
        "schema_version": 1,
        "claim_class": manifest["claim_class"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "builds": builds,
        "coverage": {
            "grasu_regraph_algorithms": sorted(grasu_algorithms),
            "grasu_regraph_three_algorithm_routed": True,
            "spine_core_sssp_routed": True,
            "spine_three_algorithm_iso_functional": False,
        },
        "resource_ratio_eligible": False,
        "limitations": manifest.get("limitations", []),
        "status": "PASS",
    }
