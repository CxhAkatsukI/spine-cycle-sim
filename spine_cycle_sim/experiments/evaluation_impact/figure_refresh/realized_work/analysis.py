"""Recompute stage tables and a calibration-only fit from this campaign."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import platform

import numpy as np

from scripts.package_simulator_predicted_fig10 import normalized_rows
from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.rq3 import TEN_STAGE_KEYS, analyze_rq3_results, write_rq3_analysis
from spine_cycle_sim.experiments.shared_workloads import load_slice
from .matrix import FRESH, SELECTION
from .run import admit


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"empty table: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="ascii") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def check_zero_net(case: dict) -> None:
    base = load_slice(Path(case["inputs"]["--workload"]["path"]))
    update = load_slice(Path(case["inputs"]["--update-workload"]["path"]))
    if base.vertices != update.vertices:
        raise ValueError("zero-net vertex domains differ")
    state = Counter()
    for edge in base.records:
        state[(edge.src, edge.dst, edge.weight)] += edge.diff
    original = +state
    for edge in update.records:
        state[(edge.src, edge.dst, edge.weight)] += edge.diff
        if state[(edge.src, edge.dst, edge.weight)] < 0:
            raise ValueError("zero-net deletes an absent edge")
    if +state != original or not any(e.diff < 0 for e in update.records):
        raise ValueError("zero-net snapshot equivalence failed")


def stage_rows(analysis: dict) -> list[dict]:
    by_id = {r["execution_id"]: r for r in analysis["latency_rows"]}
    rows = []
    for group, tick, previous_id in SELECTION:
        row = {**by_id[FRESH + previous_id], "figure_group": group, "figure_tick": tick}
        if not all(row[k] is True for k in (
            "ten_stage_supported", "ten_stage_ledger_closed", "ledger_closed"
        )):
            raise ValueError(f"unsupported stage attribution: {row['execution_id']}")
        if sum(row[k] for k in TEN_STAGE_KEYS) != row["total_cycles"]:
            raise ValueError("stage cycles do not conserve total")
        rows.append(row)
    return rows


def analyze(campaign: Path) -> dict:
    matrix = json.loads((campaign / "matrix.json").read_text())
    identity = json.loads((campaign / "identity.json").read_text())
    if sha256_file(campaign / "matrix.json") != identity["matrix_sha256"]:
        raise ValueError("frozen matrix changed")
    if len(matrix["cases"]) != 42:
        raise ValueError("expected 41 fit/holdout cases plus one zero-net")
    results = []
    for case in matrix["cases"]:
        for item in case["inputs"].values():
            if sha256_file(Path(item["path"])) != item["sha256"]:
                raise ValueError("input changed")
        path = Path(case["out_dir"]) / "case_result.json"
        wrapper = json.loads(path.read_text())
        if wrapper != admit(case, identity["plugin_sha256"]):
            raise ValueError(f"admission changed: {case['execution_id']}")
        results.append(wrapper)
        if case["previous_execution_id"] == "zero_net_sssp":
            check_zero_net(case)
    fit_cases = [r for r in results if r["rq3_role"] != "excluded_fig10_only"]
    roles = Counter(r["rq3_role"] for r in fit_cases)
    if roles != {"synthetic_calibration": 18, "trace_calibration": 6, "trace_holdout": 17}:
        raise ValueError(f"predeclared split changed: {roles}")
    fit = analyze_rq3_results(fit_cases, preferred_plugin_sha256=[identity["plugin_sha256"]])
    if len(fit["e2e_prediction_rows"]) != 41:
        raise ValueError("model omitted declared rows")
    selection = {FRESH + previous for _, _, previous in SELECTION}
    breakdown = analyze_rq3_results([r for r in results if r["case"]["execution_id"] in selection],
                                   preferred_plugin_sha256=[identity["plugin_sha256"]])
    stages = stage_rows(breakdown)
    output = campaign / "analysis"
    write_rq3_analysis(output, fit)
    for path in output.glob("rq3_*.csv"):
        with path.open(newline="", encoding="ascii") as stream:
            rows = list(csv.DictReader(stream))
        write_csv(path, rows)
    write_csv(output / "fig10_stage_rows.csv", stages)
    write_csv(output / "fig10_normalized_breakdown_rows.csv", normalized_rows(stages))
    report = {"status": "PASS_SIMULATOR_PREDICTION", "executions": 42,
        "fig10_bars": len(stages), "fig11_fit_and_holdout_rows": len(fit_cases),
        "split": dict(roles), "plugin_sha256": identity["plugin_sha256"],
        "e2e_metrics": fit["e2e_metric_rows"],
        "stage_regressions": fit["regression_rows"],
        "no_holdout_used_for_fit": fit["e2e_model"]["holdout_rows_are_never_used_for_fit"],
        "zero_net_excluded_from_fit": True,
        "all_fig10_ten_stage_ledgers_closed": True,
        "fpga_stage_calibrated": False,
        "analysis_environment": {"python": platform.python_version(), "numpy": np.__version__},
        "residual_apply_mode": matrix["residual_apply_mode"]}
    atomic_write_json(output / "fresh_summary.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(analyze(args.campaign.resolve()), indent=2))


if __name__ == "__main__":
    main()
