#!/usr/bin/env python3
"""Build paper data for Spine ablations and shared-HBM sensitivity."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OPT_V1 = (
    ROOT / "docs/evidence/spine_opt_v1_fallback_level_cache_20260728.json"
)
DEFAULT_OPT_V2 = ROOT / "docs/evidence/spine_opt_v2_reader_working_set_20260728.json"
DEFAULT_SENSITIVITY_DETAILS = (
    ROOT
    / "docs/evidence/candidate10_hbm_sensitivity_v1_20260727"
    / "sensitivity_details.csv"
)
DEFAULT_SENSITIVITY_SUMMARY = (
    ROOT
    / "docs/evidence/candidate10_hbm_sensitivity_v1_20260727"
    / "sensitivity_summary.csv"
)
DEFAULT_OUTPUT_DIR = ROOT / "docs/paper/data"


def _read_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _positive(value: object, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid {name}: {value!r}") from exc
    if parsed <= 0:
        raise RuntimeError(f"non-positive {name}: {parsed}")
    return parsed


def _speedup(parent: dict[str, object], optimized: dict[str, object]) -> float:
    return _positive(parent["cycles"], "parent cycles") / _positive(
        optimized["cycles"], "optimized cycles"
    )


def build_ablation_rows(opt_v1_path: Path, opt_v2_path: Path) -> list[dict[str, object]]:
    opt_v1 = _read_json(opt_v1_path)
    opt_v2 = _read_json(opt_v2_path)
    if not opt_v1["claims"]["all_correctness_and_ledgers_pass"]:
        raise RuntimeError("opt-v1 correctness/ledger gate failed")
    if not opt_v2["claims"]["all_correctness_and_ledgers_pass"]:
        raise RuntimeError("opt-v2 correctness/ledger gate failed")

    fallback_v1 = opt_v1["sst_fallback_ab"]
    exact_v2 = opt_v2["sst_compact_exact"]
    fallback_v2 = opt_v2["sst_compact_fallback"]
    large_v2 = opt_v2["sst_large_full_pagerank"]
    cases = [
        ("Opt-v1 fallback", fallback_v1["baseline"], fallback_v1["optimized"], "compact fallback"),
        ("Opt-v2 exact cache", exact_v2["parent"], exact_v2["cached"], "compact exact"),
        ("Opt-v2 fallback cache", fallback_v2["parent"], fallback_v2["cached"], "compact fallback"),
        ("Opt-v2 gate only", large_v2["native_gate_parent"], large_v2["expanded_gate"], "Amazon 50K"),
        ("Opt-v2 combined", large_v2["native_gate_parent"], large_v2["expanded_gate_and_cache"], "Amazon 50K"),
    ]

    rows: list[dict[str, object]] = []
    for index, (label, parent, optimized, scope) in enumerate(cases):
        for result_name, result in (("parent", parent), ("optimized", optimized)):
            if not result["success"]:
                raise RuntimeError(f"{label} {result_name} did not succeed")
            if int(result["correctness_mismatches"]) != 0:
                raise RuntimeError(f"{label} {result_name} failed correctness")
            if not result["memory_locality_ledger_match"]:
                raise RuntimeError(f"{label} {result_name} failed memory ledger")
        parent_requests = _positive(parent["backend_requests"], "parent requests")
        optimized_requests = _positive(
            optimized["backend_requests"], "optimized requests"
        )
        rows.append(
            {
                "index": index,
                "label": label,
                "scope": scope,
                "parent_cycles": int(parent["cycles"]),
                "optimized_cycles": int(optimized["cycles"]),
                "speedup": _speedup(parent, optimized),
                "backend_request_reduction_percent": 100.0
                * (1.0 - optimized_requests / parent_requests),
            }
        )
    return rows


def build_sensitivity_rows(
    details_path: Path, summary_path: Path
) -> list[dict[str, object]]:
    with details_path.open(encoding="utf-8", newline="") as stream:
        details = list(csv.DictReader(stream))
    with summary_path.open(encoding="utf-8", newline="") as stream:
        summary = list(csv.DictReader(stream))
    if not details or not summary:
        raise RuntimeError("empty HBM sensitivity evidence")

    baseline_by_run: dict[str, float] = {}
    for row in details:
        run_id = row["run_id"]
        value = _positive(row["baseline_spine_speedup"], "baseline speedup")
        previous = baseline_by_run.setdefault(run_id, value)
        if not math.isclose(previous, value, rel_tol=0.0, abs_tol=1e-12):
            raise RuntimeError(f"inconsistent baseline speedup for {run_id}")
        if row["strict_rank_inversion"] != "False":
            raise RuntimeError(f"strict rank inversion for {run_id}/{row['profile_id']}")

    baseline = math.exp(
        sum(math.log(value) for value in baseline_by_run.values())
        / len(baseline_by_run)
    )
    labels = {
        "baseline": "Baseline",
        "latency_low": "Latency -20%",
        "latency_high": "Latency +20%",
        "bandwidth_high": "Bandwidth +20%",
        "bandwidth_low": "Bandwidth -20%",
    }
    rows: list[dict[str, object]] = [
        {
            "index": 0,
            "profile_id": "baseline",
            "label": labels["baseline"],
            "spine_speedup_geomean": baseline,
            "winner_changes": 0,
            "strict_rank_inversions": 0,
        }
    ]
    for index, row in enumerate(summary, start=1):
        profile_id = row["profile_id"]
        if profile_id not in labels:
            raise RuntimeError(f"unknown sensitivity profile {profile_id}")
        if int(row["strict_rank_inversions"]) != 0:
            raise RuntimeError(f"strict rank inversion under {profile_id}")
        rows.append(
            {
                "index": index,
                "profile_id": profile_id,
                "label": labels[profile_id],
                "spine_speedup_geomean": _positive(
                    row["spine_speedup_geomean"], "sensitivity speedup"
                ),
                "winner_changes": int(row["winner_changes"]),
                "strict_rank_inversions": int(row["strict_rank_inversions"]),
            }
        )
    return rows


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise RuntimeError(f"no rows for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opt-v1", type=Path, default=DEFAULT_OPT_V1)
    parser.add_argument("--opt-v2", type=Path, default=DEFAULT_OPT_V2)
    parser.add_argument(
        "--sensitivity-details", type=Path, default=DEFAULT_SENSITIVITY_DETAILS
    )
    parser.add_argument(
        "--sensitivity-summary", type=Path, default=DEFAULT_SENSITIVITY_SUMMARY
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    ablation = build_ablation_rows(args.opt_v1, args.opt_v2)
    sensitivity = build_sensitivity_rows(
        args.sensitivity_details, args.sensitivity_summary
    )
    write_rows(args.out_dir / "spine_optimization_ablation.csv", ablation)
    write_rows(args.out_dir / "hbm_sensitivity.csv", sensitivity)
    print(
        f"wrote {len(ablation)} ablation and {len(sensitivity)} sensitivity rows "
        f"to {args.out_dir}"
    )


if __name__ == "__main__":
    main()
