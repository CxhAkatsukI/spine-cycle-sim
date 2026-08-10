#!/usr/bin/env python3
"""Audit whether evaluation refresh figures use FPGA-aligned simulator evidence."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs" / "evaluation_refresh_20260810"
DEFAULT_CAMPAIGN_ANALYSIS = (
    Path("/data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen")
    / "analysis_partial"
)
REQUIRED_FIG9_ROWS = 9
ALIGNED_CURRENT_MODEL_STATUSES = {
    "PASS_CAMPAIGN_ANALYSIS",
    "PASS_CURRENT_MODEL_DATA",
}


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"missing": True, "path": str(path)}
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def provenance_status(out_dir: Path) -> dict[str, dict[str, Any]]:
    provenance_dir = out_dir / "provenance"
    return {
        figure: read_json(provenance_dir / f"{figure}.json")
        for figure in ("fig7", "fig8", "fig9", "fig10")
    }


def campaign_status(analysis_dir: Path | None) -> dict[str, Any]:
    if analysis_dir is None:
        return {"present": False}
    summary_path = analysis_dir / "summary.json"
    pair_path = analysis_dir / "pair_rows.csv"
    if not summary_path.is_file():
        return {
            "present": False,
            "analysis_dir": str(analysis_dir),
            "missing": str(summary_path),
        }
    summary = read_json(summary_path)
    pairs = read_csv_rows(pair_path)
    algorithms = sorted({row["algorithm"] for row in pairs})
    datasets = sorted({row["dataset_id"] for row in pairs})
    return {
        "present": True,
        "analysis_dir": str(analysis_dir),
        "summary_status": summary.get("status"),
        "observed_executions": int(summary.get("observed_executions", 0)),
        "expected_executions": int(summary.get("expected_executions", 0)),
        "pair_rows": len(pairs),
        "required_pair_rows": REQUIRED_FIG9_ROWS,
        "missing_executions": int(
            summary.get(
                "missing_executions",
                len(summary.get("missing_execution_ids", [])),
            )
        ),
        "complete_for_fig9": len(pairs) == REQUIRED_FIG9_ROWS,
        "paired_algorithms": algorithms,
        "paired_datasets": datasets,
    }


def figure_alignment(
    provenance: dict[str, dict[str, Any]], campaign: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    fig7_status = provenance["fig7"].get("status")
    fig8_status = provenance["fig8"].get("status")
    fig9_status = provenance["fig9"].get("status")
    fig10_status = provenance["fig10"].get("status")
    return {
        "fig7": {
            "aligned": fig7_status == "PASS",
            "status": fig7_status,
            "evidence": "routed FPGA data",
        },
        "fig8": {
            "aligned": fig8_status in ALIGNED_CURRENT_MODEL_STATUSES,
            "status": fig8_status,
            "evidence": "setup-inclusive update-throughput simulator rows",
            "gap": (
                "still uses archived update-only evidence"
                if str(fig8_status).startswith("INTERIM")
                else ""
            ),
        },
        "fig9": {
            "aligned": fig9_status == "PASS_CAMPAIGN_ANALYSIS",
            "status": fig9_status,
            "evidence": "campaign pair_rows memory and HBM-energy ledger",
            "campaign_pairs": campaign.get("pair_rows", 0),
            "required_pairs": REQUIRED_FIG9_ROWS,
        },
        "fig10": {
            "aligned": fig10_status in ALIGNED_CURRENT_MODEL_STATUSES,
            "status": fig10_status,
            "evidence": "RQ3 component ledger",
            "gap": (
                "still uses archived RQ3 component traces"
                if str(fig10_status).startswith("INTERIM")
                else ""
            ),
        },
    }


def build_audit(out_dir: Path, analysis_dir: Path | None) -> dict[str, Any]:
    provenance = provenance_status(out_dir)
    campaign = campaign_status(analysis_dir)
    figures = figure_alignment(provenance, campaign)
    ready = all(figure["aligned"] for figure in figures.values())
    return {
        "status": "READY" if ready else "INCOMPLETE",
        "out_dir": str(out_dir),
        "campaign": campaign,
        "figures": figures,
        "next_actions": [
            action
            for action, needed in (
                (
                    "finish all 9 AU/SU/WK campaign pairs for calibrated Fig.9",
                    not campaign.get("complete_for_fig9", False),
                ),
                (
                    "replace Fig.8 archived update-throughput CSVs with calibrated campaign-derived rows",
                    not figures["fig8"]["aligned"],
                ),
                (
                    "replace Fig.10 archived RQ3 traces with calibrated current-model component ledgers",
                    not figures["fig10"]["aligned"],
                ),
            )
            if needed
        ],
    }


def write_markdown(path: Path, audit: dict[str, Any]) -> None:
    lines = [
        "# Evaluation Refresh Alignment Audit",
        "",
        f"Status: `{audit['status']}`",
        "",
        "## Campaign",
        "",
    ]
    campaign = audit["campaign"]
    if campaign.get("present"):
        lines.extend(
            [
                f"- Analysis: `{campaign['analysis_dir']}`",
                f"- Summary status: `{campaign['summary_status']}`",
                f"- Observed executions: `{campaign['observed_executions']}/{campaign['expected_executions']}`",
                f"- Complete pairs: `{campaign['pair_rows']}/{campaign['required_pair_rows']}`",
                f"- Paired algorithms: `{', '.join(campaign['paired_algorithms'])}`",
                f"- Paired datasets: `{', '.join(campaign['paired_datasets'])}`",
            ]
        )
    else:
        lines.append("- Campaign analysis is not present.")
    lines.extend(["", "## Figures", ""])
    for figure, status in audit["figures"].items():
        aligned = "yes" if status["aligned"] else "no"
        lines.append(
            f"- `{figure}`: aligned={aligned}, status=`{status.get('status')}`"
        )
        if status.get("gap"):
            lines.append(f"  Gap: {status['gap']}.")
    if audit["next_actions"]:
        lines.extend(["", "## Next Actions", ""])
        lines.extend(f"- {action}." for action in audit["next_actions"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--campaign-analysis-dir", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()

    analysis_dir = args.campaign_analysis_dir
    if analysis_dir is None and DEFAULT_CAMPAIGN_ANALYSIS.is_dir():
        analysis_dir = DEFAULT_CAMPAIGN_ANALYSIS
    out_dir = args.out_dir.resolve()
    audit = build_audit(out_dir, analysis_dir.resolve() if analysis_dir else None)
    provenance_dir = out_dir / "provenance"
    provenance_dir.mkdir(parents=True, exist_ok=True)
    audit_json = provenance_dir / "alignment_audit.json"
    audit_json.write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(out_dir / "alignment_audit.md", audit)
    print(
        f"EVALUATION_ALIGNMENT_{audit['status']} "
        f"pairs={audit['campaign'].get('pair_rows', 0)}/{REQUIRED_FIG9_ROWS} "
        f"out={audit_json}",
        flush=True,
    )
    if args.require_ready and audit["status"] != "READY":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
