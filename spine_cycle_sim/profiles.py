"""Versioned architecture profiles for reproducible simulator runs.

Profiles separate measured hardware baselines from normalized comparison
configurations and proposed architectures.  A run must name one profile; the
profile identity is copied into every result manifest.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
from typing import Any


class ProfileError(ValueError):
    """Raised when an architecture profile violates the schema."""


class ProfileStatus(str, Enum):
    HISTORICAL = "historical"
    STABLE = "stable"
    EXPERIMENTAL = "experimental"
    PROJECTED = "projected"


class EvidenceTier(str, Enum):
    HARDWARE_VALIDATED = "hardware_validated"
    EMULATION_VALIDATED = "emulation_validated"
    SYNTHESIS_ONLY = "synthesis_only"
    SIMULATION_ONLY = "simulation_only"


@dataclass(frozen=True)
class SourceIdentity:
    repository: str
    revision: str
    branch: str
    dirty: bool


@dataclass(frozen=True)
class ClockProfile:
    name: str
    requested_mhz: float
    achieved_mhz: float


@dataclass(frozen=True)
class MemoryProfile:
    backend: str
    channels: int
    channel_capacity_bytes: int
    data_width_bits: int
    max_burst_bytes: int
    max_outstanding_per_port: int


@dataclass(frozen=True)
class EvidenceArtifact:
    kind: str
    path: str
    sha256: str | None = None


@dataclass(frozen=True)
class ArchitectureProfile:
    schema_version: int
    profile_id: str
    architecture: str
    status: ProfileStatus
    evidence_tier: EvidenceTier
    source: SourceIdentity
    clocks: tuple[ClockProfile, ...]
    memory: MemoryProfile
    parameters: dict[str, int | float | bool | str]
    features: tuple[str, ...]
    evidence: tuple[EvidenceArtifact, ...]
    limitations: tuple[str, ...]
    manifest_sha256: str

    def clock(self, name: str) -> ClockProfile:
        for clock in self.clocks:
            if clock.name == name:
                return clock
        raise KeyError(f"profile {self.profile_id!r} has no clock {name!r}")


_ROOT_FIELDS = {
    "schema_version",
    "profile_id",
    "architecture",
    "status",
    "evidence_tier",
    "source",
    "clocks",
    "memory",
    "parameters",
    "features",
    "evidence",
    "limitations",
}


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProfileError(f"{field} must be an object")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileError(f"{field} must be a non-empty string")
    return value


def _positive_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ProfileError(f"{field} must be positive")
    return float(value)


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProfileError(f"{field} must be a positive integer")
    return value


def _exact_fields(value: dict[str, Any], expected: set[str], field: str) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing or unknown:
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unknown:
            details.append(f"unknown={','.join(unknown)}")
        raise ProfileError(f"{field} fields invalid ({'; '.join(details)})")


def _string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProfileError(f"{field} must be a list")
    return tuple(_string(item, f"{field}[]") for item in value)


def load_architecture_profile(path: str | Path) -> ArchitectureProfile:
    """Load and strictly validate a JSON architecture profile."""

    profile_path = Path(path)
    raw_bytes = profile_path.read_bytes()
    try:
        root = _mapping(json.loads(raw_bytes), "profile")
    except json.JSONDecodeError as exc:
        raise ProfileError(f"invalid JSON in {profile_path}: {exc}") from exc
    _exact_fields(root, _ROOT_FIELDS, "profile")

    if root["schema_version"] != 1:
        raise ProfileError("only architecture profile schema_version=1 is supported")

    source = _mapping(root["source"], "source")
    _exact_fields(source, {"repository", "revision", "branch", "dirty"}, "source")
    if not isinstance(source["dirty"], bool):
        raise ProfileError("source.dirty must be boolean")
    revision = _string(source["revision"], "source.revision")
    if revision != "uncommitted" and (
        len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision)
    ):
        raise ProfileError("source.revision must be a 40-character lowercase git hash")
    source_identity = SourceIdentity(
        repository=_string(source["repository"], "source.repository"),
        revision=revision,
        branch=_string(source["branch"], "source.branch"),
        dirty=source["dirty"],
    )

    clocks_raw = root["clocks"]
    if not isinstance(clocks_raw, list) or not clocks_raw:
        raise ProfileError("clocks must be a non-empty list")
    clocks = []
    names: set[str] = set()
    for index, item in enumerate(clocks_raw):
        clock = _mapping(item, f"clocks[{index}]")
        _exact_fields(clock, {"name", "requested_mhz", "achieved_mhz"}, f"clocks[{index}]")
        name = _string(clock["name"], f"clocks[{index}].name")
        if name in names:
            raise ProfileError(f"duplicate clock name {name!r}")
        names.add(name)
        clocks.append(
            ClockProfile(
                name=name,
                requested_mhz=_positive_number(
                    clock["requested_mhz"], f"clocks[{index}].requested_mhz"
                ),
                achieved_mhz=_positive_number(
                    clock["achieved_mhz"], f"clocks[{index}].achieved_mhz"
                ),
            )
        )

    memory = _mapping(root["memory"], "memory")
    _exact_fields(
        memory,
        {
            "backend",
            "channels",
            "channel_capacity_bytes",
            "data_width_bits",
            "max_burst_bytes",
            "max_outstanding_per_port",
        },
        "memory",
    )
    memory_profile = MemoryProfile(
        backend=_string(memory["backend"], "memory.backend"),
        channels=_positive_int(memory["channels"], "memory.channels"),
        channel_capacity_bytes=_positive_int(
            memory["channel_capacity_bytes"], "memory.channel_capacity_bytes"
        ),
        data_width_bits=_positive_int(memory["data_width_bits"], "memory.data_width_bits"),
        max_burst_bytes=_positive_int(memory["max_burst_bytes"], "memory.max_burst_bytes"),
        max_outstanding_per_port=_positive_int(
            memory["max_outstanding_per_port"], "memory.max_outstanding_per_port"
        ),
    )

    parameters = _mapping(root["parameters"], "parameters")
    for key, value in parameters.items():
        _string(key, "parameters key")
        if not isinstance(value, (int, float, bool, str)):
            raise ProfileError(f"parameters.{key} must be scalar")

    evidence_raw = root["evidence"]
    if not isinstance(evidence_raw, list):
        raise ProfileError("evidence must be a list")
    artifacts = []
    for index, item in enumerate(evidence_raw):
        artifact = _mapping(item, f"evidence[{index}]")
        allowed = {"kind", "path", "sha256"}
        unknown = set(artifact) - allowed
        missing = {"kind", "path"} - set(artifact)
        if missing or unknown:
            raise ProfileError(f"evidence[{index}] fields invalid")
        digest = artifact.get("sha256")
        if digest is not None:
            digest = _string(digest, f"evidence[{index}].sha256")
            if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
                raise ProfileError(f"evidence[{index}].sha256 must be lowercase SHA-256")
        artifacts.append(
            EvidenceArtifact(
                kind=_string(artifact["kind"], f"evidence[{index}].kind"),
                path=_string(artifact["path"], f"evidence[{index}].path"),
                sha256=digest,
            )
        )

    try:
        status = ProfileStatus(root["status"])
    except ValueError as exc:
        raise ProfileError(f"unsupported profile status {root['status']!r}") from exc
    try:
        evidence_tier = EvidenceTier(root["evidence_tier"])
    except ValueError as exc:
        raise ProfileError(f"unsupported evidence tier {root['evidence_tier']!r}") from exc

    return ArchitectureProfile(
        schema_version=1,
        profile_id=_string(root["profile_id"], "profile_id"),
        architecture=_string(root["architecture"], "architecture"),
        status=status,
        evidence_tier=evidence_tier,
        source=source_identity,
        clocks=tuple(clocks),
        memory=memory_profile,
        parameters=dict(parameters),
        features=_string_list(root["features"], "features"),
        evidence=tuple(artifacts),
        limitations=_string_list(root["limitations"], "limitations"),
        manifest_sha256=hashlib.sha256(raw_bytes).hexdigest(),
    )


def verify_profile_artifacts(profile: ArchitectureProfile) -> list[str]:
    """Return artifact problems without mutating or silently skipping evidence."""

    problems: list[str] = []
    for artifact in profile.evidence:
        path = Path(artifact.path)
        if not path.exists():
            problems.append(f"missing: {path}")
            continue
        if artifact.sha256 and path.is_file():
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != artifact.sha256:
                problems.append(
                    f"sha256 mismatch: {path} expected={artifact.sha256} actual={actual}"
                )
    return problems
