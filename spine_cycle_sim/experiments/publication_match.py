"""Fail-closed comparisons with independently audited publication conditions.

This module does not infer architectural equivalence or fit timing factors.
Each condition needs a source-backed audit before a rate error is admitted.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


REQUIRED_CONDITIONS = (
    "algorithm", "workload", "initial_state", "topology", "memory",
    "clock", "boundary", "numerator", "correctness",
)
CONDITION_STATUSES = frozenset({"matched", "mismatch", "unresolved"})


def positive_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a positive finite number")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a positive finite number")
    return number


def assess_comparison(
    case: Mapping[str, Any], *, threshold_pct: float
) -> dict[str, Any]:
    """Admit a relative rate error only after every comparison gate passes."""

    threshold = positive_number(threshold_pct, "threshold_pct")
    conditions = case.get("conditions")
    if not isinstance(conditions, Mapping) or set(conditions) != set(REQUIRED_CONDITIONS):
        raise ValueError("comparison must explicitly audit all required conditions")
    if not isinstance(case.get("id"), str) or not case["id"]:
        raise ValueError("comparison needs a nonempty id")
    mismatches, unresolved = [], []
    for name in REQUIRED_CONDITIONS:
        condition = conditions[name]
        if not isinstance(condition, Mapping):
            raise ValueError(f"{name} must be an audited condition")
        status = condition.get("status")
        if status not in CONDITION_STATUSES:
            raise ValueError(f"{name} has an invalid audit status")
        if not isinstance(condition.get("evidence"), str) or not condition["evidence"].strip():
            raise ValueError(f"{name} needs an evidence explanation")
        if status == "mismatch":
            mismatches.append(name)
        elif status == "unresolved":
            unresolved.append(name)

    rates = {}
    for name in ("reference_rate", "candidate_rate"):
        value = case.get(name)
        rates[name] = None if value is None else positive_number(value, name)
    result = {
        "id": case["id"], "status": "INSUFFICIENT_EVIDENCE",
        "threshold_pct": threshold, "mismatches": mismatches,
        "unresolved": unresolved, "absolute_rate_error_pct": None,
        **rates,
    }
    if mismatches:
        result["status"] = "NOT_COMPARABLE_AS_CONFIGURED"
    elif not unresolved and all(value is not None for value in rates.values()):
        error = abs(rates["candidate_rate"] / rates["reference_rate"] - 1) * 100
        result["absolute_rate_error_pct"] = error
        result["status"] = (
            "WITHIN_THRESHOLD" if error <= threshold + 1e-12 else "OUTSIDE_THRESHOLD"
        )
    return result


def assess_study(contract: Mapping[str, Any]) -> dict[str, Any]:
    if contract.get("schema_version") != 1:
        raise ValueError("unsupported publication-match contract")
    cases = contract.get("comparisons")
    if not isinstance(cases, list) or not cases:
        raise ValueError("publication-match contract needs comparisons")
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("comparison ids must be unique")
    rows = [
        assess_comparison(case, threshold_pct=contract["threshold_pct"])
        for case in cases
    ]
    all_matched = all(row["status"] == "WITHIN_THRESHOLD" for row in rows)
    return {
        "schema_version": 1,
        "claim": (
            "declared_publication_comparisons_within_threshold" if all_matched
            else "publication_performance_match_not_established"
        ),
        "comparisons": rows,
        "matched_comparisons": sum(row["status"] == "WITHIN_THRESHOLD" for row in rows),
        "all_comparisons_matched": all_matched,
    }
