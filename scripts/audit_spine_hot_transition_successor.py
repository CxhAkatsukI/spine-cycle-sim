#!/usr/bin/env python3
"""Audit an affected old/new Spine publication-result transition."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(payload, dict) or payload.get("status") != "pass":
        raise ValueError(f"publication result is not passing: {path}")
    return payload


def _integer(mapping: Mapping[str, Any], key: str) -> int:
    value = mapping.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"expected integer {key}")
    return value


def audit_transition(
    baseline_path: Path, candidate_path: Path
) -> dict[str, Any]:
    baseline_path = baseline_path.resolve()
    candidate_path = candidate_path.resolve()
    baseline = _load(baseline_path)
    candidate = _load(candidate_path)

    old_plugin = str(baseline.get("plugin_sha256", ""))
    new_plugin = str(candidate.get("plugin_sha256", ""))
    if len(old_plugin) != 64 or len(new_plugin) != 64 or old_plugin == new_plugin:
        raise ValueError("transition requires two distinct plugin hashes")
    old_case = baseline.get("case")
    new_case = candidate.get("case")
    if not isinstance(old_case, Mapping) or old_case.get("system") != "spine":
        raise ValueError("baseline is not a Spine publication case")
    if old_case != new_case:
        raise ValueError("successor changed publication case identity")
    if baseline.get("final_state") != candidate.get("final_state"):
        raise ValueError("successor changed final state")

    old_metrics = baseline.get("scalar_metrics")
    new_metrics = candidate.get("scalar_metrics")
    if not isinstance(old_metrics, Mapping) or not isinstance(new_metrics, Mapping):
        raise ValueError("transition result lacks scalar metrics")
    old_hot = _integer(old_metrics, "resident_hot_edges")
    new_hot = _integer(new_metrics, "resident_hot_edges")
    if old_hot <= 0:
        raise ValueError("baseline row is not affected by the hot transition")
    if new_hot > old_hot:
        raise ValueError("corrected classifier increased resident hot edges")

    admission = candidate.get("admission")
    if not isinstance(admission, Mapping):
        raise ValueError("successor lacks parent admission")
    for key in (
        "architecture_correctness_mismatches",
        "mathematical_correctness_mismatches",
    ):
        if _integer(admission, key) != 0:
            raise ValueError(f"successor failed {key}")
    parent_problems = admission.get("parent_problems")
    if parent_problems is not None and parent_problems != []:
        raise ValueError("successor parent admission has problems")
    parent_checks = admission.get("parent_checks")
    if isinstance(parent_checks, Mapping) and not all(
        value is True for value in parent_checks.values()
    ):
        raise ValueError("successor parent admission check failed")
    plugin_admission = admission.get("plugin_admission")
    if (
        not isinstance(plugin_admission, Mapping)
        or plugin_admission.get("classification") != "frozen_simulator_baseline"
        or plugin_admission.get("observed_plugin_sha256") != new_plugin
        or plugin_admission.get("baseline_plugin_sha256") != new_plugin
    ):
        raise ValueError("successor plugin was not the frozen baseline")

    old_row = baseline.get("row")
    new_row = candidate.get("row")
    if not isinstance(old_row, Mapping) or not isinstance(new_row, Mapping):
        raise ValueError("transition result lacks normalized row")
    old_cycles = _integer(old_row, "cycles")
    new_cycles = _integer(new_row, "cycles")
    if old_cycles <= 0 or new_cycles <= 0:
        raise ValueError("transition cycles must be positive")

    return {
        "schema_version": 1,
        "status": "pass",
        "classification": "affected_identical_case_successor",
        "execution_id": str(old_case["execution_id"]),
        "affected_metric": "resident_hot_edges",
        "baseline": {
            "case_result": str(baseline_path),
            "plugin_sha256": old_plugin,
            "cycles": old_cycles,
            "resident_hot_edges": old_hot,
        },
        "candidate": {
            "case_result": str(candidate_path),
            "plugin_sha256": new_plugin,
            "cycles": new_cycles,
            "resident_hot_edges": new_hot,
        },
        "checks": {
            "case_identity_exact": True,
            "final_state_exact": True,
            "architecture_correctness_mismatches_zero": True,
            "mathematical_correctness_mismatches_zero": True,
            "new_hot_edges_lower": new_hot < old_hot,
        },
        "cycle_delta": new_cycles - old_cycles,
        "cycle_ratio_new_over_old": new_cycles / old_cycles,
        "hot_edge_reduction": old_hot - new_hot,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-result", type=Path, required=True)
    parser.add_argument("--candidate-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit_transition(args.baseline_result, args.candidate_result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(
        f"PASS {result['execution_id']}: cycles_delta={result['cycle_delta']} "
        f"hot_edge_reduction={result['hot_edge_reduction']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
