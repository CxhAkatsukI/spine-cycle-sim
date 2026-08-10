#!/usr/bin/env python3
"""Analyze the calibration campaign and regenerate evaluation refresh figures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAMPAIGN_ROOT = Path("/data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen")
DEFAULT_OUT = ROOT / "docs" / "evaluation_refresh_20260810"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], *, cwd: Path) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-root", type=Path, default=DEFAULT_CAMPAIGN_ROOT)
    parser.add_argument(
        "--extra-result-root",
        type=Path,
        action="append",
        default=[],
        help="additional publication-analysis result root to merge with campaign-root",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--analysis-name", default="analysis_final")
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()

    campaign_root = args.campaign_root.resolve()
    analysis_dir = campaign_root / args.analysis_name
    manifest = campaign_root / "campaign_manifest.json"
    if not manifest.is_file():
        raise FileNotFoundError(manifest)

    analyze_command = [
        args.python,
        str(ROOT / "scripts" / "analyze_publication_experiment_campaign.py"),
        "--result-root",
        str(campaign_root),
    ]
    for result_root in args.extra_result_root:
        analyze_command.extend(("--result-root", str(result_root.resolve())))
    analyze_command.extend(
        [
            "--manifest",
        str(manifest),
        "--result-transition-contract",
        str(ROOT / "configs" / "contracts" / "large_graph_publication_campaign_fullgraph_v8.json"),
        "--required-system",
        "spine",
        "--required-system",
        "grasu_regraph_k4_shared",
        "--out-dir",
        str(analysis_dir),
        ]
    )
    if not args.allow_partial:
        analyze_command.append("--require-complete")
    run(analyze_command, cwd=ROOT)

    summary_path = analysis_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("status") != "PASS" and not args.allow_partial:
        raise SystemExit(f"analysis did not pass: {summary.get('status')}")

    render_command = [
        args.python,
        str(ROOT / "scripts" / "render_evaluation_refresh.py"),
        "--campaign-analysis-dir",
        str(analysis_dir),
        "--out-dir",
        str(args.out_dir.resolve()),
    ]
    if args.allow_partial:
        render_command.append("--allow-partial-campaign-fig9")
    run(render_command, cwd=ROOT)

    run(
        [
            args.python,
            str(ROOT / "scripts" / "collect_fullpr_route_evidence.py"),
            "--out-dir",
            str(args.out_dir.resolve()),
        ],
        cwd=ROOT,
    )
    run(
        [
            args.python,
            str(ROOT / "scripts" / "audit_evaluation_refresh_alignment.py"),
            "--out-dir",
            str(args.out_dir.resolve()),
            "--campaign-analysis-dir",
            str(analysis_dir),
        ],
        cwd=ROOT,
    )

    provenance = {
        "status": summary.get("status"),
        "campaign_root": str(campaign_root),
        "extra_result_roots": [str(path.resolve()) for path in args.extra_result_root],
        "campaign_manifest": str(manifest),
        "campaign_manifest_sha256": sha256(manifest),
        "analysis_dir": str(analysis_dir),
        "analysis_summary": str(summary_path),
        "analysis_summary_sha256": sha256(summary_path),
        "out_dir": str(args.out_dir.resolve()),
        "allow_partial": args.allow_partial,
    }
    provenance_path = args.out_dir / "provenance" / "calibration_campaign.json"
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path.write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"EVALUATION_REFRESH_FINALIZE_{summary.get('status')} "
        f"analysis={analysis_dir} out={args.out_dir.resolve()}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
