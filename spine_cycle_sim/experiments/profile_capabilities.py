"""Fail-closed algorithm capabilities for versioned architecture profiles."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any

from spine_cycle_sim.profiles import load_architecture_profile


class CapabilityError(ValueError):
    """Raised when a profile capability claim is absent or inconsistent."""


class ImplementationStatus(str, Enum):
    EXECUTABLE = "executable"
    PROFILE_ONLY = "profile_only"


@dataclass(frozen=True)
class AlgorithmCapability:
    algorithm: str
    implementation_status: ImplementationStatus
    claim_class: str
    edge_semantics: str
    update_semantics: str
    convergence: str
    evidence_tier: str

    def manifest_record(self) -> dict[str, str]:
        record = asdict(self)
        record["implementation_status"] = self.implementation_status.value
        return record


@dataclass(frozen=True)
class ProfileCapability:
    profile_id: str
    profile_path: Path
    profile_sha256: str
    comparison_role: str
    handoff: str
    conversion_cost: str
    supported_algorithms: dict[str, AlgorithmCapability]
    unsupported_algorithms: tuple[str, ...]

    def require(self, algorithm: str, *, executable: bool = True) -> AlgorithmCapability:
        capability = self.supported_algorithms.get(algorithm)
        if capability is None:
            raise CapabilityError(
                f"profile {self.profile_id!r} does not support algorithm {algorithm!r}"
            )
        if executable and capability.implementation_status is not ImplementationStatus.EXECUTABLE:
            raise CapabilityError(
                f"profile {self.profile_id!r} algorithm {algorithm!r} is "
                f"{capability.implementation_status.value}, not executable"
            )
        return capability


@dataclass(frozen=True)
class CapabilityCatalog:
    catalog_id: str
    manifest_path: Path
    manifest_sha256: str
    algorithms: tuple[str, ...]
    profiles: dict[str, ProfileCapability]

    def profile(self, profile_id: str) -> ProfileCapability:
        try:
            return self.profiles[profile_id]
        except KeyError as exc:
            raise CapabilityError(
                f"profile {profile_id!r} is absent from capability catalog"
            ) from exc


_ROOT_FIELDS = {"schema_version", "catalog_id", "algorithms", "profiles"}
_PROFILE_FIELDS = {
    "profile_id",
    "profile_path",
    "profile_sha256",
    "comparison_role",
    "handoff",
    "conversion_cost",
    "supported_algorithms",
    "unsupported_algorithms",
}
_ALGORITHM_FIELDS = {
    "implementation_status",
    "claim_class",
    "edge_semantics",
    "update_semantics",
    "convergence",
    "evidence_tier",
}


def _exact_fields(value: dict[str, Any], expected: set[str], context: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        raise CapabilityError(
            f"{context} fields invalid: missing={missing}, unknown={unknown}"
        )


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise CapabilityError(f"{context} must be a non-empty string")
    return value


def _string_list(value: Any, context: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise CapabilityError(f"{context} must be a list")
    result = tuple(_string(item, f"{context}[]") for item in value)
    if len(set(result)) != len(result):
        raise CapabilityError(f"{context} contains duplicates")
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_capability_catalog(
    path: str | Path, *, repository_root: str | Path | None = None
) -> CapabilityCatalog:
    manifest_path = Path(path).resolve()
    root = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(root, dict):
        raise CapabilityError("capability catalog must be an object")
    _exact_fields(root, _ROOT_FIELDS, "catalog")
    if root["schema_version"] != 1:
        raise CapabilityError("only capability schema_version=1 is supported")
    algorithms = _string_list(root["algorithms"], "algorithms")
    algorithm_set = set(algorithms)
    if not algorithm_set:
        raise CapabilityError("algorithms must not be empty")
    entries = root["profiles"]
    if not isinstance(entries, list) or not entries:
        raise CapabilityError("profiles must be a non-empty list")
    repo = (
        Path(repository_root).resolve()
        if repository_root is not None
        else manifest_path.parents[2]
    )
    profiles: dict[str, ProfileCapability] = {}
    for index, raw in enumerate(entries):
        if not isinstance(raw, dict):
            raise CapabilityError(f"profiles[{index}] must be an object")
        _exact_fields(raw, _PROFILE_FIELDS, f"profiles[{index}]")
        profile_id = _string(raw["profile_id"], f"profiles[{index}].profile_id")
        if profile_id in profiles:
            raise CapabilityError(f"duplicate profile capability {profile_id!r}")
        profile_path = (repo / _string(raw["profile_path"], "profile_path")).resolve()
        expected_hash = _string(raw["profile_sha256"], "profile_sha256")
        if len(expected_hash) != 64 or _sha256(profile_path) != expected_hash:
            raise CapabilityError(f"profile hash mismatch: {profile_path}")
        profile = load_architecture_profile(profile_path)
        if profile.profile_id != profile_id:
            raise CapabilityError(f"profile ID mismatch: {profile_path}")
        comparison_role = _string(raw["comparison_role"], "comparison_role")
        if profile.parameters.get("comparison_role") != comparison_role:
            raise CapabilityError(f"comparison role mismatch for {profile_id}")
        conversion_cost = _string(raw["conversion_cost"], "conversion_cost")
        expected_conversion = (
            "included"
            if profile.parameters.get("conversion_cost_included") is True
            else "absent"
        )
        if conversion_cost != expected_conversion:
            raise CapabilityError(f"conversion contract mismatch for {profile_id}")
        handoff = _string(raw["handoff"], "handoff")
        if (handoff == "pma_to_compact_edge_array") == bool(
            profile.parameters.get("pma_native_compute")
        ):
            raise CapabilityError(f"handoff contract mismatch for {profile_id}")

        supported_raw = raw["supported_algorithms"]
        if not isinstance(supported_raw, dict) or not supported_raw:
            raise CapabilityError(
                f"supported_algorithms must be non-empty for {profile_id}"
            )
        supported: dict[str, AlgorithmCapability] = {}
        for algorithm, capability_raw in supported_raw.items():
            if algorithm not in algorithm_set or not isinstance(capability_raw, dict):
                raise CapabilityError(f"invalid supported algorithm {algorithm!r}")
            _exact_fields(
                capability_raw,
                _ALGORITHM_FIELDS,
                f"profiles[{index}].supported_algorithms.{algorithm}",
            )
            try:
                status = ImplementationStatus(capability_raw["implementation_status"])
            except ValueError as exc:
                raise CapabilityError(
                    f"invalid implementation status for {profile_id}/{algorithm}"
                ) from exc
            supported[algorithm] = AlgorithmCapability(
                algorithm=algorithm,
                implementation_status=status,
                claim_class=_string(capability_raw["claim_class"], "claim_class"),
                edge_semantics=_string(capability_raw["edge_semantics"], "edge_semantics"),
                update_semantics=_string(capability_raw["update_semantics"], "update_semantics"),
                convergence=_string(capability_raw["convergence"], "convergence"),
                evidence_tier=_string(capability_raw["evidence_tier"], "evidence_tier"),
            )
        unsupported = _string_list(
            raw["unsupported_algorithms"],
            f"profiles[{index}].unsupported_algorithms",
        )
        if set(supported) & set(unsupported) or set(supported) | set(unsupported) != algorithm_set:
            raise CapabilityError(
                f"algorithm capability partition is incomplete for {profile_id}"
            )
        profiles[profile_id] = ProfileCapability(
            profile_id=profile_id,
            profile_path=profile_path,
            profile_sha256=expected_hash,
            comparison_role=comparison_role,
            handoff=handoff,
            conversion_cost=conversion_cost,
            supported_algorithms=supported,
            unsupported_algorithms=unsupported,
        )
    return CapabilityCatalog(
        catalog_id=_string(root["catalog_id"], "catalog_id"),
        manifest_path=manifest_path,
        manifest_sha256=_sha256(manifest_path),
        algorithms=algorithms,
        profiles=profiles,
    )
