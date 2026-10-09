#!/usr/bin/env python3
"""Run a source-frozen G+R regression matrix and optionally compare a baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.campaign_runtime import (  # noqa: E402
    CampaignRunner, atomic_write_json, sha256_file,
)
from spine_cycle_sim.experiments.refactor_equivalence import (  # noqa: E402
    case_command, compare_runs, source_snapshot, verify_source_snapshot,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=ROOT / "configs/experiments/grasu_component_refactor_v1.json")
    parser.add_argument("--lib-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--case-timeout-seconds", type=int, default=240)
    args = parser.parse_args()
    if args.case_timeout_seconds <= 0:
        parser.error("--case-timeout-seconds must be positive")
    out = args.out_dir.resolve()
    if out.exists():
        raise ValueError("use a new output directory; frozen runs cannot be overwritten")
    contract = json.loads(args.contract.read_text())
    lib_dir = args.lib_dir.resolve()
    identity = {
        "schema_version": 1, "contract_sha256": sha256_file(args.contract),
        "plugin_sha256": sha256_file(lib_dir / "libspine_cycle.so"),
        "source": source_snapshot(ROOT, args.contract, contract),
        "case_timeout_seconds": args.case_timeout_seconds,
    }
    atomic_write_json(out / "identity.json", identity)
    manifest = {
        "schema_version": 1, "campaign_id": contract["study_id"],
        "default_cwd": str(ROOT),
        "jobs": [
            {"job_id": case["id"], "command": case_command(
                ROOT, case, lib_dir, out / "cases" / case["id"],
                timeout_seconds=args.case_timeout_seconds),
             "estimated_rss_gib": 1.0, "system": "grasu", "tier": "source_refactor_equivalence"}
            for case in contract["cases"]
        ],
    }
    path = out / "campaign.json"
    atomic_write_json(path, manifest)
    runner = CampaignRunner(
        path, out / "campaign", jobs=args.jobs, large_jobs=1,
        memory_reserve_bytes=16 * 2**30, memory_emergency_bytes=12 * 2**30,
        memory_recovery_bytes=16 * 2**30, sample_seconds=1.0,
        pin_cpus=False, resume=False, no_progress_warn_seconds=120,
    )
    if not runner.run():
        print(f"FAIL: inspect saved case logs in {out}", flush=True)
        return 1
    if sha256_file(lib_dir / "libspine_cycle.so") != identity["plugin_sha256"]:
        raise ValueError("plugin changed during the campaign")
    verify_source_snapshot(ROOT, identity["source"])
    if args.baseline_dir:
        report = compare_runs(contract, args.baseline_dir.resolve(), out)
        atomic_write_json(out / "equivalence.json", report)
        print(f"{report['status']}: exact result comparison for {len(report['cases'])} cases", flush=True)
        return 0 if report["status"] == "PASS" else 1
    print(f"PASS: frozen baseline for {len(contract['cases'])} cases -> {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
