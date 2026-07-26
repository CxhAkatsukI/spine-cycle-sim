"""Fail-closed importer for the frozen Spine candidate-10 hardware evidence."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shlex
from typing import Any, Iterable


class Candidate10EvidenceError(ValueError):
    """Raised when candidate-10 evidence is incomplete or inconsistent."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256_manifest(path: Path) -> int:
    """Verify every regular file named by a GNU sha256sum manifest."""

    if not path.is_file():
        raise Candidate10EvidenceError(f"missing SHA256 manifest: {path}")
    checked = 0
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            digest, file_name = raw_line.split(maxsplit=1)
        except ValueError as error:
            raise Candidate10EvidenceError(
                f"{path}:{line_number}: malformed SHA256 entry"
            ) from error
        file_name = file_name.lstrip(" *")
        artifact = Path(file_name)
        if not artifact.is_absolute():
            artifact = path.parent / artifact
        if not artifact.is_file():
            raise Candidate10EvidenceError(f"manifest artifact is missing: {artifact}")
        actual = sha256_file(artifact)
        if actual != digest:
            raise Candidate10EvidenceError(
                f"SHA256 mismatch for {artifact}: expected {digest}, got {actual}"
            )
        checked += 1
    if checked == 0:
        raise Candidate10EvidenceError("SHA256 manifest is empty")
    return checked


def _scalar(value: str) -> int | float | str:
    try:
        return int(value, 10)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def parse_metric_line(line: str, marker: str) -> dict[str, int | float | str]:
    """Parse one whitespace-delimited hardware line after its exact marker."""

    prefix = f"{marker} "
    if not line.startswith(prefix):
        raise Candidate10EvidenceError(f"line does not start with {marker!r}")
    metrics: dict[str, int | float | str] = {}
    for token in shlex.split(line[len(prefix) :]):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if not key or key in metrics:
            raise Candidate10EvidenceError(f"invalid or duplicate metric token: {token}")
        metrics[key] = _scalar(value)
    if not metrics:
        raise Candidate10EvidenceError(f"{marker} line has no metrics")
    return metrics


def _load_pass_cases(case_root: Path, evidence_category: str) -> list[dict[str, Any]]:
    if not case_root.is_dir():
        raise Candidate10EvidenceError(f"missing evidence directory: {case_root}")
    rows: list[dict[str, Any]] = []
    for case_dir in sorted(path for path in case_root.iterdir() if path.is_dir()):
        status_path = case_dir / "exit.status"
        console_path = case_dir / "console.log"
        if not status_path.is_file() or not console_path.is_file():
            raise Candidate10EvidenceError(f"incomplete correctness case: {case_dir}")
        try:
            exit_status = int(status_path.read_text(encoding="ascii").strip())
        except ValueError as error:
            raise Candidate10EvidenceError(
                f"invalid exit status for {case_dir.name}"
            ) from error
        batches: list[dict[str, int | float | str]] = []
        passes: list[tuple[str, dict[str, int | float | str]]] = []
        for line in console_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("PARTITIONED_CSR_E2E_BATCH "):
                batches.append(parse_metric_line(line, "PARTITIONED_CSR_E2E_BATCH"))
            elif (
                line.startswith("PARTITIONED_") or evidence_category == "focused"
            ) and (" PASS " in line or line.endswith(" PASS")):
                marker_end = line.index(" PASS") + len(" PASS")
                marker = line[:marker_end]
                metrics = (
                    parse_metric_line(line, marker)
                    if len(line) > marker_end
                    else {}
                )
                passes.append((marker, metrics))
        if exit_status != 0 or not passes:
            raise Candidate10EvidenceError(
                f"case {case_dir.name} is not a clean PASS: "
                f"exit={exit_status}, passes={len(passes)}"
            )
        for marker, passed in passes:
            if "errors" in passed and int(passed["errors"]) != 0:
                raise Candidate10EvidenceError(
                    f"case {case_dir.name} marker {marker} reports "
                    f"errors={passed['errors']}"
                )
        primary_marker, primary = next(
            (
                entry
                for entry in passes
                if entry[0] == "PARTITIONED_CSR_E2E_SMOKE PASS"
            ),
            passes[-1],
        )
        rows.append(
            {
                "evidence_case": case_dir.name,
                "evidence_category": evidence_category,
                "exit_status": exit_status,
                "batch_count": len(batches),
                "batch_ledgers_json": json.dumps(batches, separators=(",", ":")),
                "pass_count": len(passes),
                "primary_pass_marker": primary_marker,
                "pass_markers_json": json.dumps(
                    [marker for marker, _ in passes], separators=(",", ":")
                ),
                "pass_ledgers_json": json.dumps(
                    [metrics for _, metrics in passes], separators=(",", ":")
                ),
                **primary,
            }
        )
    if not rows:
        raise Candidate10EvidenceError(
            f"candidate {evidence_category} evidence has no cases"
        )
    return rows


def load_correctness_cases(root: Path) -> list[dict[str, Any]]:
    """Load every correctness case and require an explicit clean PASS."""

    return _load_pass_cases(root / "correctness", "correctness")


def load_focused_cases(root: Path) -> list[dict[str, Any]]:
    """Load every focused benchmark group and require a clean PASS marker."""

    return _load_pass_cases(root / "focused", "focused")


def load_focused_trials(root: Path) -> list[dict[str, str]]:
    """Concatenate focused trial matrices while retaining their evidence group."""

    focused = root / "focused"
    if not focused.is_dir():
        raise Candidate10EvidenceError(f"missing focused directory: {focused}")
    rows: list[dict[str, str]] = []
    for path in sorted(focused.glob("*/trials.csv")):
        with path.open("r", encoding="utf-8", newline="") as stream:
            for trial in csv.DictReader(stream):
                if not trial:
                    continue
                if trial.get("errors") != "0":
                    raise Candidate10EvidenceError(
                        f"focused trial reports errors in {path}: {trial.get('errors')}"
                    )
                rows.append({"evidence_group": path.parent.name, **trial})
    if not rows:
        raise Candidate10EvidenceError("candidate focused evidence has no trial rows")
    return rows


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    materialized = list(rows)
    if not materialized:
        raise Candidate10EvidenceError(f"refusing to write empty CSV: {path}")
    field_names = sorted({key for row in materialized for key in row})
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=field_names,
            extrasaction="raise",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(materialized)
    return len(materialized)


def import_candidate10_evidence(
    source_dir: Path, out_dir: Path, profile_path: Path
) -> dict[str, Any]:
    """Verify, normalize, and bind the measured evidence to one profile."""

    source_dir = source_dir.resolve()
    profile_path = profile_path.resolve()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if profile.get("profile_id") != "spine_candidate10_one_pass_1e61fc0":
        raise Candidate10EvidenceError("candidate importer requires the candidate-10 profile")
    manifests = [
        artifact
        for artifact in profile.get("evidence", [])
        if artifact.get("kind") == "direct_hardware_evidence_manifest"
    ]
    if len(manifests) != 1:
        raise Candidate10EvidenceError("profile must name one direct evidence manifest")
    manifest_path = Path(manifests[0]["path"]).resolve()
    if manifest_path != source_dir / "SHA256SUMS":
        raise Candidate10EvidenceError("source directory does not match the profile")
    if sha256_file(manifest_path) != manifests[0].get("sha256"):
        raise Candidate10EvidenceError("profile-bound SHA256SUMS digest mismatch")

    files_verified = verify_sha256_manifest(manifest_path)
    correctness_rows = load_correctness_cases(source_dir)
    focused_case_rows = load_focused_cases(source_dir)
    focused_rows = load_focused_trials(source_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    correctness_count = _write_csv(out_dir / "correctness_cases.csv", correctness_rows)
    focused_case_count = _write_csv(out_dir / "focused_cases.csv", focused_case_rows)
    focused_count = _write_csv(out_dir / "focused_trials.csv", focused_rows)
    result = {
        "schema_version": 1,
        "profile_id": profile["profile_id"],
        "profile_sha256": sha256_file(profile_path),
        "source_dir": str(source_dir),
        "source_manifest": str(manifest_path),
        "source_manifest_sha256": sha256_file(manifest_path),
        "files_verified": files_verified,
        "correctness_cases": correctness_count,
        "focused_cases": focused_case_count,
        "focused_trials": focused_count,
        "all_correctness_passed": True,
        "all_focused_trials_error_free": True,
        "claim": "measured_candidate10_u55c_hardware",
        "status": "PASS",
    }
    (out_dir / "import_manifest.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
