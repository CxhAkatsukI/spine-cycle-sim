#!/usr/bin/env python3
"""Prove that a plugin transition leaves G+R execution results unchanged."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_path(run_dir: Path) -> Path:
    for name in ("run_manifest.json", "manifest.json", "summary.json"):
        candidate = run_dir / name
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"missing run manifest under {run_dir}")


def compare_pair(label: str, baseline_dir: Path, candidate_dir: Path) -> dict[str, Any]:
    baseline_result_path = baseline_dir / "result.json"
    candidate_result_path = candidate_dir / "result.json"
    baseline = read_json(baseline_result_path)
    candidate = read_json(candidate_result_path)
    baseline_manifest_path = manifest_path(baseline_dir)
    candidate_manifest_path = manifest_path(candidate_dir)
    baseline_manifest = read_json(baseline_manifest_path)
    candidate_manifest = read_json(candidate_manifest_path)
    if baseline != candidate:
        changed = sorted(
            key
            for key in set(baseline) | set(candidate)
            if baseline.get(key) != candidate.get(key)
        )
        raise ValueError(f"{label} changed G+R result fields: {changed}")
    for name, manifest in (
        ("baseline", baseline_manifest),
        ("candidate", candidate_manifest),
    ):
        if manifest.get("status") != "PASS":
            raise ValueError(f"{label} {name} run did not pass")
    return {
        "label": label,
        "status": "PASS",
        "exact_result_match": True,
        "cycles": int(baseline["cycles"]),
        "baseline": {
            "directory": str(baseline_dir.resolve()),
            "result_sha256": sha256_file(baseline_result_path),
            "manifest_sha256": sha256_file(baseline_manifest_path),
            "plugin_sha256": baseline_manifest["sst_plugin_sha256"],
        },
        "candidate": {
            "directory": str(candidate_dir.resolve()),
            "result_sha256": sha256_file(candidate_result_path),
            "manifest_sha256": sha256_file(candidate_manifest_path),
            "plugin_sha256": candidate_manifest["sst_plugin_sha256"],
        },
    }


def parse_pair(value: str) -> tuple[str, Path, Path]:
    try:
        label, directories = value.split("=", 1)
        baseline, candidate = directories.split(",", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "pair must be LABEL=BASELINE_DIR,CANDIDATE_DIR"
        ) from exc
    if not label or not baseline or not candidate:
        raise argparse.ArgumentTypeError("pair fields must be non-empty")
    return label, Path(baseline), Path(candidate)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", action="append", type=parse_pair, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args()

    rows = [compare_pair(*pair) for pair in args.pair]
    plugin_pairs = {
        (row["baseline"]["plugin_sha256"], row["candidate"]["plugin_sha256"])
        for row in rows
    }
    if len(plugin_pairs) != 1:
        raise ValueError("all equivalence rows must compare the same plugin pair")
    report = {
        "schema_version": 1,
        "status": "PASS",
        "classification": "grasu_execution_path_exact_result_equivalence",
        "source_revision": args.source_revision,
        "changed_source_scope": "Spine resident hot/cold classifier and Spine counters only",
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(f"GRASU_PLUGIN_TRANSITION_PASS rows={len(rows)} output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
