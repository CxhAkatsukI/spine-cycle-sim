"""Fail-closed evidence for host-runtime-only SST plugin replacements."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


HOST_RUNTIME_IGNORED_TOP_LEVEL_FIELDS = (
    "sst_host_wall_seconds",
    "sst_library_binding",
    "sst_plugin_sha256",
)
HOST_RUNTIME_EQUIVALENCE_CLASS = (
    "spine_host_runtime_only_no_simulated_timing_change"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def canonical_host_runtime_summary(payload: Mapping[str, Any]) -> bytes:
    canonical = dict(payload)
    for field in HOST_RUNTIME_IGNORED_TOP_LEVEL_FIELDS:
        canonical.pop(field, None)
    return json.dumps(
        canonical, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def compare_host_runtime_summaries(
    baseline_path: Path, candidate_path: Path, *, label: str
) -> dict[str, Any]:
    if not label:
        raise ValueError("plugin-equivalence evidence label must be nonempty")
    paths = (baseline_path.resolve(), candidate_path.resolve())
    payloads = [
        json.loads(path.read_text(encoding="ascii")) for path in paths
    ]
    for payload in payloads:
        if payload.get("status") != "PASS" or payload.get("success") is not True:
            raise ValueError("plugin-equivalence input is not a passing SST summary")
        if not _valid_sha256(payload.get("sst_plugin_sha256")):
            raise ValueError("plugin-equivalence input lacks a valid plugin hash")
    plugin_hashes = [str(payload["sst_plugin_sha256"]) for payload in payloads]
    if plugin_hashes[0] == plugin_hashes[1]:
        raise ValueError("plugin-equivalence inputs use the same plugin")
    canonical = [canonical_host_runtime_summary(payload) for payload in payloads]
    canonical_hashes = [hashlib.sha256(value).hexdigest() for value in canonical]
    if canonical[0] != canonical[1]:
        changed_fields = sorted(
            key
            for key in set(payloads[0]) | set(payloads[1])
            if payloads[0].get(key) != payloads[1].get(key)
            and key not in HOST_RUNTIME_IGNORED_TOP_LEVEL_FIELDS
        )
        raise ValueError(
            "candidate plugin changed simulated evidence fields: "
            + ", ".join(changed_fields)
        )
    return {
        "schema_version": 1,
        "status": "pass",
        "label": label,
        "classification": HOST_RUNTIME_EQUIVALENCE_CLASS,
        "ignored_top_level_fields": list(HOST_RUNTIME_IGNORED_TOP_LEVEL_FIELDS),
        "canonical_summary_sha256": canonical_hashes[0],
        "baseline": {
            "summary_path": str(paths[0]),
            "summary_sha256": sha256_file(paths[0]),
            "plugin_sha256": plugin_hashes[0],
        },
        "candidate": {
            "summary_path": str(paths[1]),
            "summary_sha256": sha256_file(paths[1]),
            "plugin_sha256": plugin_hashes[1],
        },
        "simulated_metrics": {
            "cycles": int(payloads[0]["cycles"]),
            "backend_requests": int(payloads[0]["backend_requests"]),
            "architecture_correctness_mismatches": int(
                payloads[0].get("architecture_correctness_mismatches", 0)
            ),
            "mathematical_correctness_mismatches": int(
                payloads[0].get("mathematical_correctness_mismatches", 0)
            ),
        },
    }


def verify_spine_plugin_admission(
    contract: Mapping[str, Any],
    plugin_path: Path,
    *,
    system: str,
    repository_root: Path,
) -> dict[str, Any]:
    """Admit the frozen plugin or a Spine-only host-runtime equivalent."""

    plugin = plugin_path.resolve()
    if not plugin.is_file():
        raise ValueError("formal SST plugin is missing")
    observed = sha256_file(plugin)
    simulator = contract["architecture_baselines"]["simulator_baseline"]
    baseline = str(simulator["plugin_sha256"])
    if observed == baseline:
        return {
            "classification": "frozen_simulator_baseline",
            "baseline_plugin_sha256": baseline,
            "observed_plugin_sha256": observed,
        }
    if system != "spine":
        raise ValueError(
            "host-runtime-equivalent plugins are admitted only for Spine"
        )
    entries = simulator.get("spine_host_runtime_equivalent_plugins", [])
    matches = [
        entry
        for entry in entries
        if isinstance(entry, Mapping)
        and entry.get("plugin_sha256") == observed
    ]
    if len(matches) != 1:
        raise ValueError("formal SST plugin differs from the frozen baseline")
    entry = matches[0]
    if (
        entry.get("baseline_plugin_sha256") != baseline
        or entry.get("classification") != HOST_RUNTIME_EQUIVALENCE_CLASS
        or not isinstance(entry.get("source_commit"), str)
        or len(str(entry["source_commit"])) != 40
    ):
        raise ValueError("invalid Spine host-runtime plugin equivalence entry")
    reports = entry.get("evidence_reports")
    if not isinstance(reports, list) or len(reports) < 2:
        raise ValueError("Spine plugin equivalence requires at least two reports")
    verified_reports = []
    labels = set()
    root = repository_root.resolve()
    for identity in reports:
        if not isinstance(identity, list) or len(identity) != 2:
            raise ValueError("invalid plugin-equivalence report identity")
        relative_path, expected_sha256 = map(str, identity)
        path = Path(relative_path)
        if path.is_absolute() or ".." in path.parts or not _valid_sha256(
            expected_sha256
        ):
            raise ValueError("unsafe plugin-equivalence report identity")
        resolved = root / path
        if not resolved.is_file() or sha256_file(resolved) != expected_sha256:
            raise ValueError("plugin-equivalence report is missing or changed")
        report = json.loads(resolved.read_text(encoding="ascii"))
        if (
            report.get("schema_version") != 1
            or report.get("status") != "pass"
            or report.get("classification") != HOST_RUNTIME_EQUIVALENCE_CLASS
            or report.get("baseline", {}).get("plugin_sha256") != baseline
            or report.get("candidate", {}).get("plugin_sha256") != observed
            or report.get("ignored_top_level_fields")
            != list(HOST_RUNTIME_IGNORED_TOP_LEVEL_FIELDS)
            or not _valid_sha256(report.get("canonical_summary_sha256"))
        ):
            raise ValueError("plugin-equivalence report content is invalid")
        label = str(report.get("label", ""))
        if not label or label in labels:
            raise ValueError("plugin-equivalence report labels are invalid")
        labels.add(label)
        verified_reports.append(
            {"path": relative_path, "sha256": expected_sha256, "label": label}
        )
    required_labels = set(map(str, entry.get("required_report_labels", [])))
    if not required_labels or labels != required_labels:
        raise ValueError("plugin-equivalence report set is incomplete")
    return {
        "classification": HOST_RUNTIME_EQUIVALENCE_CLASS,
        "baseline_plugin_sha256": baseline,
        "observed_plugin_sha256": observed,
        "source_commit": entry["source_commit"],
        "evidence_reports": verified_reports,
    }
