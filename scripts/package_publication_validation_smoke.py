#!/usr/bin/env python3
"""Package the fixed native validation-refactor smoke, retaining its rejection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.campaign_runtime import (  # noqa: E402
    atomic_write_json,
    sha256_file,
)
from spine_cycle_sim.experiments.grasu_native_validation import validate_result  # noqa: E402


CASES = (
    ("tiny_star_v16_u12", "before", "after_star", "native_star_fixed_two_rounds", False),
    ("tiny_spread_v16_u8", "before_holdout", "after_holdout", "native_spread_holdout", True),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--baseline-plugin-sha256", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    plugin = ROOT / "build/sst/libspine_cycle.so"
    if sha256_file(plugin) != args.baseline_plugin_sha256:
        raise ValueError("plugin changed since the pre-extraction smoke")
    profile = json.loads((ROOT / "configs/architectures/grasu_regraph_native_a9aef06.json").read_text())
    campaign_path = args.run_root / "campaign/campaign_state.json"
    campaign = json.loads(campaign_path.read_text())
    jobs = {job["job_id"]: job for job in campaign["jobs"]}
    out = args.out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows, copied = [], []

    def copy(source: Path, destination: str) -> None:
        target = out / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.append({"path": destination, "sha256": sha256_file(target)})

    for name, before_dir, after_dir, job_id, accepted in CASES:
        before = args.baseline_root / before_dir / name / "sst/result.json"
        after_root = args.run_root / after_dir / name
        after = after_root / "sst/result.json"
        baseline, candidate = (json.loads(path.read_text()) for path in (before, after))
        if baseline != candidate:
            raise ValueError(f"native result fields changed during extraction: {name}")
        if candidate["success"] is not accepted:
            raise ValueError(f"unexpected correctness admission: {name}")
        if not accepted and (
            candidate.get("architecture_correctness_mismatches") != 0
            or candidate.get("mathematical_correctness_mismatches") != 1
            or candidate.get("supersteps") != 2
        ):
            raise ValueError("rejected case is not the known two-round convergence failure")
        validation_profile = json.loads(json.dumps(profile))
        validation_profile["parameters"]["native_validation_supersteps"] = candidate["supersteps"]
        try:
            validate_result(candidate, validation_profile, 0)
        except RuntimeError:
            if accepted:
                raise
        else:
            if not accepted:
                raise ValueError("failed mathematical oracle was accidentally admitted")
        job = jobs[job_id]
        if job["status"] != ("pass" if accepted else "fail"):
            raise ValueError(f"unexpected process status: {name}")
        copy(before, f"smoke/{name}/before.result.json")
        copy(after, f"smoke/{name}/after.result.json")
        copy(args.run_root / f"campaign/jobs/{job_id}/stdout.log", f"smoke/{name}/stdout.log")
        for filename in ("initial.slice", "update.slice", "metadata.json"):
            copy(after_root / "input" / filename, f"smoke/{name}/input/{filename}")
        row = {
            "case": name, "all_result_fields_equivalent": True,
            "cycles": candidate["cycles"], "backend_requests": candidate["backend_requests"],
            "correctness_mismatches": candidate["correctness_mismatches"],
            "admission": "ACCEPTED" if accepted else "REJECTED_NOT_CONVERGED",
            "sampled_peak_rss_bytes": job["peak_rss_bytes"],
            "elapsed_seconds": job["elapsed_seconds"],
        }
        if accepted:
            alignment = json.loads((after_root / "alignment.json").read_text())
            row["raw_native_event_e2e_absolute_error_pct"] = alignment["timing"]["event_e2e"]["absolute_error_pct"]
            copy(after_root / "alignment.json", f"smoke/{name}/alignment.json")
        rows.append(row)

    diagnostic = args.run_root / "star_three_round_correctness_only/result.json"
    result = json.loads(diagnostic.read_text())
    diagnostic_manifest_path = diagnostic.parent / "manifest.json"
    diagnostic_manifest = json.loads(diagnostic_manifest_path.read_text())
    star_input = args.run_root / "after_star/tiny_star_v16_u12/input"
    for field, filename in (("workload", "initial.slice"), ("update_workload", "update.slice")):
        if diagnostic_manifest[f"{field}_sha256"] != sha256_file(star_input / filename):
            raise ValueError("three-round diagnostic used different graph/update inputs")
    validation_profile = json.loads(json.dumps(profile))
    validation_profile["parameters"]["native_validation_supersteps"] = 3
    validate_result(result, validation_profile, 0)
    if result["supersteps"] != 3:
        raise ValueError("diagnostic must be the separate three-round execution")
    copy(diagnostic, "smoke/star_three_round_correctness_only.result.json")
    copy(diagnostic_manifest_path, "smoke/star_three_round_correctness_only.manifest.json")
    copy(campaign_path, "smoke/campaign_state.json")
    report = {
        "schema_version": 1, "refactor_status": "ALL_RESULT_FIELDS_EQUIVALENT",
        "publication_timing_match": "NOT_TESTED_BY_THIS_SMOKE",
        "plugin_sha256": args.baseline_plugin_sha256,
        "source_files": [
            {"path": name, "sha256": sha256_file(ROOT / name)}
            for name in (
                "scripts/run_sst_grasu_regraph_native.py",
                "scripts/run_grasu_native_hw_matrix.py",
                "spine_cycle_sim/experiments/grasu_native_validation.py",
                "configs/experiments/grasu_native_hw_matrix_20260725.json",
                "configs/architectures/grasu_regraph_native_a9aef06.json",
                "configs/experiments/publication_validation_smoke_v1.json",
            )
        ],
        "resource_measurement": "One-second sampled process-group RSS, not allocator peak.",
        "campaign_configuration": campaign["configuration"],
        "cases": rows, "artifacts": copied,
        "three_round_diagnostic": {
            "cycles": result["cycles"], "correctness_mismatches": result["correctness_mismatches"],
            "claim": "correctness_only_not_compared_with_two_round_hardware_log",
        },
    }
    atomic_write_json(out / "smoke_report.json", report)
    print("Packaged exact refactor equivalence, one accepted case, one preserved rejection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
