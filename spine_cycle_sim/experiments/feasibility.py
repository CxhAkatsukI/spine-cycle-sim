"""Fail-closed HLS feasibility and publication-claim gates.

The normalized simulator profiles are useful before matching hardware exists,
but that does not make every result publication eligible.  This module binds a
normalized profile set to its closest HLS evidence and makes that distinction
machine-checkable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from spine_cycle_sim.profiles import load_architecture_profile


DEFAULT_FEASIBILITY_CONTRACT = (
    Path("configs")
    / "contracts"
    / "candidate10_normalized_hls_feasibility_v1.json"
)

CLAIM_SCOPES = (
    "correctness",
    "structural_exploratory",
    "headline_normalized_performance",
    "iso_resource_performance",
    "fpga_measured_performance",
)


class FeasibilityError(ValueError):
    """Raised when evidence drifts or a requested claim is not supported."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _exact_fields(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise FeasibilityError(
            f"{context} fields differ: missing={missing}, extra={extra}"
        )


def _artifact_path(root: Path, artifact: Mapping[str, Any], context: str) -> Path:
    _exact_fields(artifact, {"path", "sha256"}, context)
    path = Path(str(artifact["path"]))
    path = path if path.is_absolute() else root / path
    if not path.is_file():
        raise FeasibilityError(f"{context} is missing: {path}")
    actual = _sha256(path)
    if actual != artifact["sha256"]:
        raise FeasibilityError(
            f"{context} SHA-256 mismatch: expected {artifact['sha256']}, got {actual}"
        )
    return path


def _profile_artifact(
    root: Path, artifact: Mapping[str, Any], context: str
) -> tuple[Path, dict[str, Any]]:
    _exact_fields(artifact, {"path", "profile_id", "sha256"}, context)
    path = Path(str(artifact["path"]))
    path = path if path.is_absolute() else root / path
    if not path.is_file():
        raise FeasibilityError(f"{context} is missing: {path}")
    actual = _sha256(path)
    if actual != artifact["sha256"]:
        raise FeasibilityError(
            f"{context} SHA-256 mismatch: expected {artifact['sha256']}, got {actual}"
        )
    profile = load_architecture_profile(path)
    if profile.profile_id != artifact["profile_id"]:
        raise FeasibilityError(
            f"{context} profile ID mismatch: expected {artifact['profile_id']}, "
            f"got {profile.profile_id}"
        )
    return path, json.loads(path.read_text(encoding="ascii"))


def _pointer(document: Any, pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise FeasibilityError(f"invalid JSON pointer: {pointer}")
    value = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        try:
            value = value[int(token)] if isinstance(value, list) else value[token]
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise FeasibilityError(f"profile field does not exist: {pointer}") from error
    return value


def load_normalized_hls_feasibility(
    root: str | Path,
    contract_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate profile/evidence identities and derive allowed claim scopes."""

    repository_root = Path(root).resolve()
    path = (
        Path(contract_path).resolve()
        if contract_path is not None
        else repository_root / DEFAULT_FEASIBILITY_CONTRACT
    )
    raw_bytes = path.read_bytes()
    try:
        contract = json.loads(raw_bytes)
    except json.JSONDecodeError as error:
        raise FeasibilityError(f"invalid feasibility contract: {path}") from error
    _exact_fields(
        contract,
        {
            "schema_version",
            "contract_id",
            "claim_class",
            "shared_platform_status",
            "spine",
            "algorithms",
            "evidence",
            "claim_gates",
        },
        "feasibility contract",
    )
    if contract["schema_version"] != 1:
        raise FeasibilityError("only feasibility schema_version=1 is supported")
    if contract["shared_platform_status"] != "pass":
        raise FeasibilityError("normalized shared-platform gate is not passing")

    _artifact_path(repository_root, contract["evidence"], "feasibility evidence")

    spine = contract["spine"]
    _exact_fields(
        spine,
        {
            "normalized_profile",
            "native_parent_profile",
            "equivalence_status",
            "matching_hls",
            "evidence_status",
        },
        "Spine feasibility entry",
    )
    _, spine_normalized = _profile_artifact(
        repository_root, spine["normalized_profile"], "Spine normalized profile"
    )
    _, spine_parent = _profile_artifact(
        repository_root, spine["native_parent_profile"], "Spine native parent"
    )
    if (
        spine_normalized["parameters"].get("native_parent_profile")
        != spine_parent["profile_id"]
    ):
        raise FeasibilityError("Spine normalized profile does not name its native parent")
    if spine_parent["evidence_tier"] != "hardware_validated":
        raise FeasibilityError("Spine native parent is not hardware validated")
    if not spine["matching_hls"]:
        raise FeasibilityError("Candidate10 Spine must retain its routed native anchor")

    algorithms = contract["algorithms"]
    expected_algorithms = {
        "weighted_sssp",
        "full_pagerank",
        "thresholded_residual_pagerank",
    }
    if set(algorithms) != expected_algorithms:
        raise FeasibilityError(
            f"algorithm feasibility set differs: {sorted(algorithms)}"
        )

    algorithm_summary: dict[str, Any] = {}
    matching_algorithms = 0
    publication_blockers: list[str] = []
    for algorithm, entry in algorithms.items():
        _exact_fields(
            entry,
            {
                "normalized_profile",
                "closest_hls_profile",
                "functional_evidence_status",
                "whole_system_hls_status",
                "matching_hls",
                "parameter_crosswalk",
                "missing_gates",
            },
            f"{algorithm} feasibility entry",
        )
        _, normalized = _profile_artifact(
            repository_root,
            entry["normalized_profile"],
            f"{algorithm} normalized profile",
        )
        _, closest = _profile_artifact(
            repository_root,
            entry["closest_hls_profile"],
            f"{algorithm} closest HLS profile",
        )
        mismatch_blockers = 0
        for index, item in enumerate(entry["parameter_crosswalk"]):
            _exact_fields(
                item,
                {
                    "field",
                    "normalized_value",
                    "closest_hls_value",
                    "difference_class",
                    "publication_blocker",
                    "reason",
                },
                f"{algorithm} crosswalk[{index}]",
            )
            normalized_value = _pointer(normalized, item["field"])
            closest_value = _pointer(closest, item["field"])
            if normalized_value != item["normalized_value"]:
                raise FeasibilityError(
                    f"{algorithm} normalized crosswalk is stale at {item['field']}"
                )
            if closest_value != item["closest_hls_value"]:
                raise FeasibilityError(
                    f"{algorithm} HLS crosswalk is stale at {item['field']}"
                )
            if normalized_value == closest_value:
                raise FeasibilityError(
                    f"{algorithm} crosswalk records a non-difference at {item['field']}"
                )
            if not isinstance(item["publication_blocker"], bool):
                raise FeasibilityError("publication_blocker must be boolean")
            mismatch_blockers += int(item["publication_blocker"])

        missing_gates = entry["missing_gates"]
        if not isinstance(missing_gates, list) or not all(
            isinstance(item, str) and item for item in missing_gates
        ):
            raise FeasibilityError(f"{algorithm} missing_gates must be strings")
        matching = bool(entry["matching_hls"])
        matching_algorithms += int(matching)
        if matching and (mismatch_blockers or missing_gates):
            raise FeasibilityError(
                f"{algorithm} cannot be matching HLS while blockers remain"
            )
        if matching and closest["evidence_tier"] not in {
            "synthesis_only",
            "hardware_validated",
        }:
            raise FeasibilityError(
                f"{algorithm} matching HLS lacks synthesis evidence"
            )
        timing_status = entry["whole_system_hls_status"]
        if matching and not any(
            marker in timing_status for marker in ("timing_closed", "timing_reported")
        ):
            raise FeasibilityError(
                f"{algorithm} matching HLS lacks whole-system timing evidence"
            )
        if matching and "pass" not in entry["functional_evidence_status"]:
            raise FeasibilityError(
                f"{algorithm} matching HLS lacks functional pass evidence"
            )
        if not matching:
            publication_blockers.extend(
                [f"{algorithm}: {item}" for item in missing_gates]
            )
            publication_blockers.extend(
                f"{algorithm}: {item['field']}"
                for item in entry["parameter_crosswalk"]
                if item["publication_blocker"]
            )
        algorithm_summary[algorithm] = {
            "normalized_profile_id": normalized["profile_id"],
            "closest_hls_profile_id": closest["profile_id"],
            "matching_hls": matching,
            "parameter_differences": len(entry["parameter_crosswalk"]),
            "parameter_blockers": mismatch_blockers,
            "missing_gates": list(missing_gates),
            "functional_evidence_status": entry["functional_evidence_status"],
            "whole_system_hls_status": entry["whole_system_hls_status"],
        }

    all_matching = matching_algorithms == len(expected_algorithms)
    claim_gates = contract["claim_gates"]
    if set(claim_gates) != set(CLAIM_SCOPES):
        raise FeasibilityError("claim gate set does not match supported scopes")
    expected_eligibility = {
        "correctness": True,
        "structural_exploratory": True,
        "headline_normalized_performance": all_matching,
        # Structural HLS matching does not prove equal resource allocation.
        "iso_resource_performance": False,
        "fpga_measured_performance": False,
    }
    for scope, gate in claim_gates.items():
        _exact_fields(gate, {"eligible", "label", "reason"}, f"claim gate {scope}")
        if gate["eligible"] is not expected_eligibility[scope]:
            raise FeasibilityError(f"claim gate {scope} is inconsistent with evidence")

    return {
        "contract_id": contract["contract_id"],
        "contract_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "claim_class": contract["claim_class"],
        "shared_platform_status": contract["shared_platform_status"],
        "spine_matching_hls": True,
        "grasu_matching_hls_algorithms": matching_algorithms,
        "grasu_required_algorithms": len(expected_algorithms),
        "all_matching_hls": all_matching,
        "algorithms": algorithm_summary,
        "publication_blockers": publication_blockers,
        "claim_gates": claim_gates,
    }


def require_claim_eligibility(
    feasibility: Mapping[str, Any], claim_scope: str
) -> dict[str, Any]:
    """Return an eligible gate or fail before an unsupported experiment runs."""

    if claim_scope not in CLAIM_SCOPES:
        raise FeasibilityError(f"unknown comparison claim scope: {claim_scope}")
    gate = feasibility["claim_gates"][claim_scope]
    if not gate["eligible"]:
        blockers = feasibility.get("publication_blockers", [])
        detail = "; ".join(str(item) for item in blockers[:8])
        if len(blockers) > 8:
            detail += f"; and {len(blockers) - 8} more"
        raise FeasibilityError(
            f"claim scope {claim_scope} is blocked: {gate['reason']}"
            + (f" ({detail})" if detail else "")
        )
    return dict(gate)
