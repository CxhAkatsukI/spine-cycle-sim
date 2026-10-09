#!/usr/bin/env python3
"""Report source-audited comparability; never fit or rescale a published rate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.campaign_runtime import (  # noqa: E402
    atomic_write_json,
    sha256_file,
)
from spine_cycle_sim.experiments.publication_match import assess_study  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    contract_path = args.contract.resolve()
    contract = json.loads(contract_path.read_text(encoding="ascii"))
    report = assess_study(contract)
    evidence = []
    for item in contract["local_evidence"]:
        path = Path(item["path"])
        path = path if path.is_absolute() else ROOT / path
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            raise ValueError(f"source evidence missing or changed: {path}")
        evidence.append(item)
    report.update({
        "contract_sha256": sha256_file(contract_path),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip(),
        "worktree_status": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True,
        ).splitlines(),
        "local_evidence": evidence,
        "analysis_code": [
            {"path": name, "sha256": sha256_file(ROOT / name)}
            for name in (
                "spine_cycle_sim/experiments/publication_match.py",
                "scripts/audit_grasu_regraph_publication.py",
            )
        ],
        "sources": contract["sources"],
        "execution_class": "source_audit_no_new_publication_timing_samples",
    })
    atomic_write_json(args.out.resolve(), report)
    print(f"Publication matches: {report['matched_comparisons']}/{len(report['comparisons'])}")
    for row in report["comparisons"]:
        print(f"  {row['id']}: {row['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
