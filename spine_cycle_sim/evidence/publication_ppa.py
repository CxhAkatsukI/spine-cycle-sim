"""Fail-closed Candidate10 routed-HLS feasibility evidence ledger."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
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
        "connectivity",
        "link_kernels",
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
    kernels_path = _evidence_path(
        root, evidence["link_kernels"], f"{build_id}.link_kernels"
    )
    connectivity_path = _evidence_path(
        root, evidence["connectivity"], f"{build_id}.connectivity"
    )

    used_rows = [
        row
        for row in _read_tsv(utilization_path)
        if row.get("name") == "Used Resources"
    ]
    used = _single_row(used_rows, f"{build_id}.Used Resources")
    if used.get("stage") != "routed":
        raise PublicationPpaError(f"{build_id}: utilization is not routed")
    resources = {
        resource: _as_int(used.get(resource, ""), f"{build_id}.{resource}")
        for resource in RESOURCE_KEYS
    }

    kernels: dict[str, int] = {}
    for row in _read_tsv(kernels_path):
        kernel = row.get("kernel", "")
        if not kernel or kernel in kernels:
            raise PublicationPpaError(f"{build_id}: invalid or duplicate kernel")
        if row.get("target") != "TT_HW":
            raise PublicationPpaError(f"{build_id}.{kernel}: target is not TT_HW")
        kernels[kernel] = _as_int(row.get("cu_count", ""), f"{build_id}.{kernel}")
        if kernels[kernel] == 0:
            raise PublicationPpaError(f"{build_id}.{kernel}: CU count is zero")

    connectivity_rows = _read_tsv(connectivity_path)
    hbm_bindings = {
        (row.get("cu", ""), row.get("port", ""), row.get("target", ""))
        for row in connectivity_rows
        if row.get("kind") == "sp"
        and re.fullmatch(r"HBM\[\d+\]", row.get("target", ""))
    }
    hbm_channels = sorted(
        {
            int(target.removeprefix("HBM[").removesuffix("]"))
            for _, _, target in hbm_bindings
        }
    )
    stream_connections = {
        row.get("connections", "") or row.get("raw", "")
        for row in connectivity_rows
        if row.get("kind") in {"stream_connect", "sc"}
    }
    stream_connections.discard("")
    slr_assignments = {
        (row.get("cu", ""), row.get("target", ""))
        for row in connectivity_rows
        if row.get("kind") == "slr"
    }
    if not hbm_bindings or not slr_assignments:
        raise PublicationPpaError(f"{build_id}: incomplete routed connectivity")

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
    expected_topology = expected.get("topology")
    topology = {
        "kernels": kernels,
        "hbm_channels": hbm_channels,
        "hbm_port_bindings": len(hbm_bindings),
        "stream_connections": len(stream_connections),
        "slr_assignments": len(slr_assignments),
    }
    if expected_topology != topology:
        raise PublicationPpaError(
            f"{build_id}: topology differs from frozen expectation: "
            f"expected {expected_topology}, got {topology}"
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
        "topology": topology,
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
    grasu_builds = [build for build in builds if build["system"] == "grasu_regraph"]
    if any(build["target_mhz"] != 150.0 for build in grasu_builds):
        raise PublicationPpaError(
            "Candidate10 GraSU+ReGraph PPA evidence must target 150 MHz"
        )
    if spine_builds[0]["target_mhz"] < 150.0:
        raise PublicationPpaError(
            "Candidate10 native Spine baseline must target at least 150 MHz"
        )

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
