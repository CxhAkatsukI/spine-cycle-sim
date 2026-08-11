#!/usr/bin/env python3
"""Audit whether evaluation refresh figures use FPGA-aligned simulator evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.profiles import load_architecture_profile


DEFAULT_OUT = ROOT / "docs" / "evaluation_refresh_20260810"
DEFAULT_CAMPAIGN_ANALYSIS = (
    Path("/data/tmp/chuxiao/evaluation_refresh_20260810_calibration_frozen")
    / "analysis_partial"
)
DEFAULT_CALIBRATION_CONTRACT = (
    ROOT / "configs" / "contracts" / "evaluation_refresh_fpga_calibration_v7.json"
)
DEFAULT_CALIBRATION_DIR = DEFAULT_OUT / "calibration_v11_analysis"
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


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def calibration_contract_status(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"valid": False, "path": str(path), "problems": ["missing contract"]}
    payload = read_json(path)
    problems: list[str] = []
    if payload.get("schema_version") not in {1, 2}:
        problems.append("schema_version must be 1 or 2")
    if payload.get("status") != "frozen":
        problems.append("contract status must be frozen")
    contract_id = payload.get("contract_id")
    if not isinstance(contract_id, str) or not contract_id:
        problems.append("contract_id is missing")
    profiles = payload.get("architecture_profiles")
    if not isinstance(profiles, list) or not profiles:
        problems.append("architecture_profiles is empty")
        profiles = []
    profile_ids: list[str] = []
    expected_pairs: list[str] = []
    for index, entry in enumerate(profiles):
        if not isinstance(entry, dict):
            problems.append(f"architecture_profiles[{index}] is not an object")
            continue
        relpath = entry.get("path")
        expected_sha = entry.get("sha256")
        profile_id = entry.get("profile_id")
        architecture = entry.get("architecture")
        algorithm = entry.get("algorithm")
        if not all(isinstance(value, str) and value for value in (relpath, expected_sha, profile_id, architecture, algorithm)):
            problems.append(f"architecture_profiles[{index}] has incomplete identity")
            continue
        profile_path = ROOT / relpath
        if not profile_path.is_file():
            problems.append(f"missing architecture profile: {profile_path}")
            continue
        if sha256_file(profile_path) != expected_sha:
            problems.append(f"architecture profile hash mismatch: {profile_id}")
            continue
        try:
            loaded = load_architecture_profile(profile_path)
        except ValueError as exc:
            problems.append(f"invalid architecture profile {profile_id}: {exc}")
            continue
        if loaded.profile_id != profile_id:
            problems.append(f"architecture profile id mismatch: {profile_id}")
        if loaded.evidence_tier.value != "hardware_validated":
            problems.append(f"profile is not hardware validated: {profile_id}")
        profile_ids.append(profile_id)
        expected_pairs.append(f"{architecture}:{algorithm}:{profile_id}")
    plugin = payload.get("simulator_plugin")
    if not isinstance(plugin, dict):
        problems.append("simulator_plugin identity is missing")
    else:
        plugin_relpath = plugin.get("path")
        plugin_sha256 = plugin.get("sha256")
        if not isinstance(plugin_relpath, str) or not plugin_relpath:
            problems.append("simulator_plugin path is missing")
        elif not (ROOT / plugin_relpath).is_file():
            problems.append(f"missing simulator plugin: {ROOT / plugin_relpath}")
        elif sha256_file(ROOT / plugin_relpath) != plugin_sha256:
            problems.append("simulator_plugin hash mismatch")
        if plugin.get("architectures") != ["spine", "grasu_regraph"]:
            problems.append("simulator_plugin must freeze both architectures")
    return {
        "valid": not problems,
        "path": str(path),
        "contract_id": contract_id,
        "sha256": sha256_file(path),
        "profile_ids": sorted(profile_ids),
        "expected_pairs": sorted(expected_pairs),
        "payload": payload,
        "problems": problems,
    }


def _coverage_key(row: dict[str, Any]) -> str:
    return ":".join(
        str(row.get(field, ""))
        for field in ("architecture", "algorithm", "profile_id")
    )


def calibration_manifest_status(
    kind: str,
    path: Path,
    contract: dict[str, Any],
) -> dict[str, Any]:
    if not path.is_file():
        return {"passed": False, "path": str(path), "problems": ["missing manifest"]}
    payload = read_json(path)
    problems: list[str] = []
    contract_payload = contract.get("payload", {})
    common = contract_payload.get("manifest_gates", {}).get("common", {})
    required = contract_payload.get("manifest_gates", {}).get(kind, {})
    if payload.get("schema_version") != 1:
        problems.append("schema_version must be 1")
    if payload.get("gate_kind") != kind:
        problems.append(f"gate_kind must be {kind}")
    if payload.get("contract_id") != contract.get("contract_id"):
        problems.append("contract_id mismatch")
    if payload.get("contract_sha256") != contract.get("sha256"):
        problems.append("contract_sha256 mismatch")
    for field, expected in common.items():
        if payload.get(field) != expected:
            problems.append(f"{field} must equal {expected!r}")
    coverage = payload.get("coverage")
    if not isinstance(coverage, list):
        problems.append("coverage must be a list")
        coverage = []
    observed = {_coverage_key(row): row for row in coverage if isinstance(row, dict)}
    missing_pairs = sorted(set(contract.get("expected_pairs", ())) - set(observed))
    if missing_pairs:
        problems.append("missing coverage: " + ", ".join(missing_pairs))
    if kind in {"total_cycle", "component_cycle"}:
        if kind == "total_cycle":
            min_cal = int(
                required["minimum_calibration_cases_per_architecture_algorithm"]
            )
            min_holdout = int(
                required["minimum_holdout_cases_per_architecture_algorithm"]
            )
        else:
            min_cal = int(required["minimum_calibration_cases_per_component"])
            min_holdout = int(required["minimum_holdout_cases_per_component"])
        for pair in contract.get("expected_pairs", ()):
            row = observed.get(pair, {})
            if int(row.get("calibration_cases", 0)) < min_cal:
                problems.append(f"insufficient calibration cases: {pair}")
            if int(row.get("holdout_cases", 0)) < min_holdout:
                problems.append(f"insufficient holdout cases: {pair}")
    elif kind == "memory_ledger":
        for pair in contract.get("expected_pairs", ()):
            row = observed.get(pair, {})
            if int(row.get("validation_cases", 0)) < 1:
                problems.append(f"missing ledger validation case: {pair}")
            if row.get("ledger_closed") is not True:
                problems.append(f"ledger is not closed: {pair}")
    elif kind == "structural_work":
        for pair in contract.get("expected_pairs", ()):
            row = observed.get(pair, {})
            if int(row.get("validation_cases", 0)) < 1:
                problems.append(f"missing structural validation case: {pair}")
            if pair.startswith("spine:") and row.get("ledger_closed") is not True:
                problems.append(f"Spine structural work does not match: {pair}")
            if pair.startswith("grasu_regraph:") and row.get(
                "hardware_counter_scope"
            ) != "not_observable":
                problems.append(f"G+R hardware counter limitation is missing: {pair}")
        if payload.get("grasu_regraph_hardware_counter_limitation_explicit") is not True:
            problems.append("G+R structural hardware-counter limitation must be explicit")
    else:
        problems.append(f"unsupported manifest kind: {kind}")
    threshold_checks = payload.get("threshold_checks")
    if not isinstance(threshold_checks, dict) or threshold_checks.get("all_pass") is not True:
        problems.append("threshold_checks.all_pass must be true")
    if kind in {"component_cycle", "memory_ledger", "structural_work"} and not payload.get(
        "hardware_observation_scope"
    ):
        problems.append("hardware_observation_scope must be explicit")
    return {
        "passed": not problems,
        "path": str(path),
        "status": payload.get("status"),
        "coverage_rows": len(coverage),
        "problems": problems,
    }


def calibration_status(contract_path: Path, calibration_dir: Path) -> dict[str, Any]:
    contract = calibration_contract_status(contract_path)
    manifests: dict[str, Any] = {}
    required = contract.get("payload", {}).get("required_manifests", {})
    for kind in (
        "total_cycle",
        "component_cycle",
        "memory_ledger",
        "structural_work",
    ):
        filename = required.get(kind, f"{kind}.json")
        manifests[kind] = calibration_manifest_status(
            kind, calibration_dir / filename, contract
        )
    return {
        "passed": contract["valid"] and all(item["passed"] for item in manifests.values()),
        "directory": str(calibration_dir),
        "contract": {key: value for key, value in contract.items() if key != "payload"},
        "manifests": manifests,
    }


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
    manifest_path = analysis_dir / "manifest.json"
    pair_path = analysis_dir / "pair_rows.csv"
    if not summary_path.is_file():
        if manifest_path.is_file() and pair_path.is_file():
            manifest = read_json(manifest_path)
            pairs = read_csv_rows(pair_path)
            algorithms = sorted({row["algorithm"] for row in pairs})
            datasets = sorted({row["dataset_id"] for row in pairs})
            expected = int(manifest.get("expected_rows", REQUIRED_FIG9_ROWS))
            current = manifest.get("status") == "PASS_CURRENT_MODEL_DATA"
            return {
                "present": True,
                "analysis_dir": str(analysis_dir),
                "summary_status": manifest.get("status"),
                "observed_executions": len(pairs) * 2,
                "expected_executions": expected * 2,
                "pair_rows": len(pairs),
                "required_pair_rows": REQUIRED_FIG9_ROWS,
                "missing_executions": max(0, expected - len(pairs)) * 2,
                "complete_for_fig9": current
                and len(pairs) == REQUIRED_FIG9_ROWS,
                "paired_algorithms": algorithms,
                "paired_datasets": datasets,
                "evidence_kind": "current_ledger_gated_fig9_package",
            }
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
    provenance: dict[str, dict[str, Any]],
    campaign: dict[str, Any],
    calibration: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    fig7_status = provenance["fig7"].get("status")
    fig8_status = provenance["fig8"].get("status")
    fig9_status = provenance["fig9"].get("status")
    fig10_status = provenance["fig10"].get("status")
    total_pass = calibration["manifests"]["total_cycle"]["passed"]
    component_pass = calibration["manifests"]["component_cycle"]["passed"]
    ledger_pass = calibration["manifests"]["memory_ledger"]["passed"]
    structural_pass = calibration["manifests"]["structural_work"]["passed"]
    contract_pass = calibration["contract"]["valid"]
    return {
        "fig7": {
            "aligned": fig7_status == "PASS",
            "status": fig7_status,
            "evidence": "routed FPGA data",
        },
        "fig8": {
            "aligned": (
                fig8_status in ALIGNED_CURRENT_MODEL_STATUSES
                and contract_pass
                and total_pass
                and component_pass
                and structural_pass
            ),
            "status": fig8_status,
            "evidence": "setup-inclusive update-throughput simulator rows",
            "gap": "current-model data are not current-hardware calibrated with immutable holdout"
            if not total_pass
            else "",
        },
        "fig9": {
            "aligned": (
                fig9_status in ALIGNED_CURRENT_MODEL_STATUSES
                and campaign.get("complete_for_fig9", False)
                and contract_pass
                and ledger_pass
                and structural_pass
            ),
            "status": fig9_status,
            "evidence": "campaign pair_rows memory and HBM-energy ledger",
            "campaign_pairs": campaign.get("pair_rows", 0),
            "required_pairs": REQUIRED_FIG9_ROWS,
            "gap": "execution-driven request/byte/FIFO ledger validation is incomplete"
            if not ledger_pass
            else "",
        },
        "fig10": {
            "aligned": (
                fig10_status in ALIGNED_CURRENT_MODEL_STATUSES
                and contract_pass
                and total_pass
                and component_pass
                and structural_pass
            ),
            "status": fig10_status,
            "evidence": "RQ3 component ledger",
            "gap": "ten-stage attribution lacks current-hardware total/component calibration and holdout"
            if not (total_pass and component_pass)
            else "",
        },
    }


def build_audit(
    out_dir: Path,
    analysis_dir: Path | None,
    calibration_contract_path: Path = DEFAULT_CALIBRATION_CONTRACT,
    calibration_dir: Path | None = None,
) -> dict[str, Any]:
    provenance = provenance_status(out_dir)
    campaign = campaign_status(analysis_dir)
    calibration = calibration_status(
        calibration_contract_path,
        calibration_dir or out_dir / "calibration",
    )
    figures = figure_alignment(provenance, campaign, calibration)
    ready = all(figure["aligned"] for figure in figures.values())
    return {
        "status": "READY" if ready else "INCOMPLETE",
        "out_dir": str(out_dir),
        "campaign": campaign,
        "calibration": calibration,
        "figures": figures,
        "next_actions": [
            action
            for action, needed in (
                (
                    "finish all 9 AU/SU/WK campaign pairs for calibrated Fig.9",
                    not campaign.get("complete_for_fig9", False),
                ),
                (
                    "replace Fig.8 archived update-throughput CSVs with current setup-inclusive update-only evidence",
                    not figures["fig8"]["aligned"],
                ),
                (
                    "replace Fig.10 archived RQ3 traces with calibrated current-model component ledgers",
                    not figures["fig10"]["aligned"],
                ),
                (
                    "complete correctness-gated current-hardware total-cycle calibration and immutable holdout",
                    not calibration["manifests"]["total_cycle"]["passed"],
                ),
                (
                    "complete observable component-cycle calibration without summing overlapping event intervals",
                    not calibration["manifests"]["component_cycle"]["passed"],
                ),
                (
                    "close request, byte, and finite-FIFO ledgers for both architectures",
                    not calibration["manifests"]["memory_ledger"]["passed"],
                ),
                (
                    "match Spine iterations, range tasks, and processed edges to routed hardware and disclose unavailable G+R counters",
                    not calibration["manifests"]["structural_work"]["passed"],
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
    lines.extend(["", "## FPGA Calibration", ""])
    calibration = audit["calibration"]
    lines.append(
        f"- Frozen contract valid: `{'yes' if calibration['contract']['valid'] else 'no'}`"
    )
    for kind, manifest in calibration["manifests"].items():
        lines.append(f"- `{kind}`: pass=`{str(manifest['passed']).lower()}`")
        for problem in manifest["problems"]:
            lines.append(f"  - {problem}")
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
    parser.add_argument(
        "--calibration-contract", type=Path, default=DEFAULT_CALIBRATION_CONTRACT
    )
    parser.add_argument("--calibration-dir", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()

    analysis_dir = args.campaign_analysis_dir
    if analysis_dir is None and DEFAULT_CAMPAIGN_ANALYSIS.is_dir():
        analysis_dir = DEFAULT_CAMPAIGN_ANALYSIS
    out_dir = args.out_dir.resolve()
    audit = build_audit(
        out_dir,
        analysis_dir.resolve() if analysis_dir else None,
        args.calibration_contract.resolve(),
        args.calibration_dir.resolve() if args.calibration_dir else None,
    )
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
