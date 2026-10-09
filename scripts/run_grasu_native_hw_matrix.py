#!/usr/bin/env python3
"""Run and summarize the frozen native GraSU/ReGraph FPGA alignment matrix."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.grasu_native_validation import validate_result  # noqa: E402


DEFAULT_MATRIX = (
    ROOT / "configs" / "experiments" / "grasu_native_hw_matrix_20260725.json"
)
DEFAULT_SST = Path("/data/feiyang/sst/bin/sst")
ROLES = frozenset({"calibration", "holdout", "stress"})
TIMING_TARGETS = ("update", "conversion", "compute_span", "event_e2e")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def repo_path(value: str) -> Path:
    path = (ROOT / value).resolve()
    if path != ROOT and ROOT not in path.parents:
        raise ValueError(f"matrix path escapes repository: {value}")
    return path


def load_matrix(path: Path = DEFAULT_MATRIX) -> dict[str, Any]:
    matrix = json.loads(path.read_text(encoding="utf-8"))
    if matrix.get("schema_version") != 1:
        raise ValueError("native hardware matrix has unsupported schema")
    if matrix.get("claim_class") != "native_hardware_alignment_unfitted_baseline":
        raise ValueError("native hardware matrix has an unsafe claim class")
    cases = matrix.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("native hardware matrix has no cases")

    names: set[str] = set()
    roles: dict[str, set[str]] = {role: set() for role in ROLES}
    for case in cases:
        required = {
            "case",
            "role",
            "family",
            "source",
            "supersteps",
            "graph",
            "graph_sha256",
            "hardware_log",
            "hardware_log_sha256",
        }
        missing = sorted(required - case.keys())
        if missing:
            raise ValueError(f"matrix case is missing {missing}: {case}")
        name = str(case["case"])
        role = str(case["role"])
        if name in names:
            raise ValueError(f"duplicate native matrix case: {name}")
        if role not in ROLES:
            raise ValueError(f"invalid native matrix role: {role}")
        if int(case["source"]) < 0 or int(case["supersteps"]) <= 0:
            raise ValueError(f"invalid source/supersteps for {name}")
        names.add(name)
        roles[role].add(name)

    if not roles["calibration"] or not roles["holdout"]:
        raise ValueError("native matrix requires calibration and holdout cases")
    if roles["calibration"] & roles["holdout"]:
        raise ValueError("native calibration and holdout cases overlap")
    return matrix


def artifact_errors(matrix: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    profile_path = repo_path(str(matrix["profile"]))
    if not profile_path.is_file():
        errors.append(f"missing profile: {profile_path}")
        return errors
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    xclbin_hashes = {
        item["sha256"]
        for item in profile.get("evidence", [])
        if item.get("kind") == "xclbin"
    }
    expected_xclbin = matrix["artifact"]["xclbin_sha256"]
    if expected_xclbin not in xclbin_hashes:
        errors.append("matrix xclbin hash is not pinned by the native profile")

    for case in matrix["cases"]:
        for key in ("graph", "hardware_log"):
            path = repo_path(str(case[key]))
            expected = str(case[f"{key}_sha256"])
            if not path.is_file():
                errors.append(f"{case['case']}: missing {key}: {path}")
            elif sha256(path) != expected:
                errors.append(f"{case['case']}: {key} SHA-256 mismatch")
    return errors


def selected_cases(
    matrix: dict[str, Any], roles: set[str], names: set[str]
) -> list[dict[str, Any]]:
    unknown_roles = roles - ROLES
    if unknown_roles:
        raise ValueError(f"unknown matrix roles: {sorted(unknown_roles)}")
    known_names = {str(case["case"]) for case in matrix["cases"]}
    unknown_names = names - known_names
    if unknown_names:
        raise ValueError(f"unknown matrix cases: {sorted(unknown_names)}")
    return [
        case
        for case in matrix["cases"]
        if case["role"] in roles and (not names or case["case"] in names)
    ]


def prediction_row(
    case: dict[str, Any], result: dict[str, Any], report: dict[str, Any]
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "case": case["case"],
        "role": case["role"],
        "family": case["family"],
        "structure_matches": report["structure_matches"],
        "correctness_mismatches": result["correctness_mismatches"],
        "vertices": result["vertices"],
        "initial_edges": result["initial_edges"],
        "updates": result["updates"],
        "final_edges": result["final_edges"],
        "pma_slots": result["pma_slots"],
        "compact_edge_slots": result["compact_edge_slots"],
        "source_external": result["source_external"],
        "source_internal": result["source_internal"],
        "supersteps": result["supersteps"],
        "simulation_cycles": result["cycles"],
    }
    for target in TIMING_TARGETS:
        timing = report["timing"][target]
        row[f"{target}_hardware_ms"] = timing["hardware_ms"]
        row[f"{target}_simulation_cycles"] = timing["simulation_cycles"]
        row[f"{target}_simulation_ms"] = timing["simulation_ms"]
        row[f"{target}_signed_error_pct"] = timing["signed_error_pct"]
        row[f"{target}_absolute_error_pct"] = timing["absolute_error_pct"]
    return row


def group_summary(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    materialized = list(rows)
    summaries: list[dict[str, Any]] = []
    roles = sorted({str(row["role"]) for row in materialized})
    for role in [*roles, "all"]:
        selected = (
            materialized
            if role == "all"
            else [row for row in materialized if row["role"] == role]
        )
        for target in TIMING_TARGETS:
            absolute = [float(row[f"{target}_absolute_error_pct"]) for row in selected]
            signed = [float(row[f"{target}_signed_error_pct"]) for row in selected]
            summaries.append(
                {
                    "role": role,
                    "target": target,
                    "cases": len(selected),
                    "structural_matches": sum(
                        bool(row["structure_matches"]) for row in selected
                    ),
                    "median_absolute_error_pct": statistics.median(absolute),
                    "max_absolute_error_pct": max(absolute),
                    "median_signed_error_pct": statistics.median(signed),
                }
            )
    return summaries


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def case_commands(
    case: dict[str, Any], out_dir: Path, sst: Path, lib_dir: Path
) -> tuple[list[str], list[str], list[str]]:
    case_dir = out_dir / str(case["case"])
    input_dir = case_dir / "input"
    sst_dir = case_dir / "sst"
    convert = [
        sys.executable,
        str(ROOT / "scripts" / "convert_grasu_graph_to_slices.py"),
        str(repo_path(str(case["graph"]))),
        "--initial-out",
        str(input_dir / "initial.slice"),
        "--update-out",
        str(input_dir / "update.slice"),
        "--metadata-out",
        str(input_dir / "metadata.json"),
    ]
    run = [
        sys.executable,
        str(ROOT / "scripts" / "run_sst_grasu_regraph_native.py"),
        "--no-build",
        "--workload",
        str(input_dir / "initial.slice"),
        "--update-workload",
        str(input_dir / "update.slice"),
        "--source",
        str(case["source"]),
        "--supersteps",
        str(case["supersteps"]),
        "--max-cycles",
        str(case.get("max_cycles", 20_000_000)),
        "--sst",
        str(sst),
        "--lib-dir",
        str(lib_dir),
        "--out-dir",
        str(sst_dir),
    ]
    analyze = [
        sys.executable,
        str(ROOT / "scripts" / "analyze_grasu_native_hw_alignment.py"),
        "--sim-result",
        str(sst_dir / "result.json"),
        "--hardware-log",
        str(repo_path(str(case["hardware_log"]))),
        "--profile",
        str(repo_path("configs/architectures/grasu_regraph_native_a9aef06.json")),
        "--out",
        str(case_dir / "alignment.json"),
    ]
    return convert, run, analyze


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--roles",
        default="calibration,holdout",
        help="Comma-separated roles; stress is excluded by default.",
    )
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    matrix_path = args.matrix.resolve()
    matrix = load_matrix(matrix_path)
    errors = artifact_errors(matrix)
    if errors:
        raise RuntimeError("native matrix artifact errors: " + "; ".join(errors))
    roles = {role.strip() for role in args.roles.split(",") if role.strip()}
    cases = selected_cases(matrix, roles, set(args.case))
    if not cases:
        raise ValueError("native hardware matrix selection is empty")

    out_dir = args.out_dir.resolve()
    commands = {
        case["case"]: case_commands(
            case, out_dir, args.sst.resolve(), args.lib_dir.resolve()
        )
        for case in cases
    }
    if args.dry_run:
        print(json.dumps(commands, indent=2))
        return 0
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)

    profile = json.loads(repo_path(str(matrix["profile"])).read_text(encoding="utf-8"))
    predictions: list[dict[str, Any]] = []
    case_manifests: list[dict[str, Any]] = []
    failures: list[str] = []
    for index, case in enumerate(cases, start=1):
        name = str(case["case"])
        print(f"[{index}/{len(cases)}] native hardware alignment: {name}", flush=True)
        convert, run, analyze = commands[name]
        started = time.monotonic()
        try:
            subprocess.run(convert, cwd=ROOT, check=True)
            subprocess.run(run, cwd=ROOT, check=True)
            subprocess.run(analyze, cwd=ROOT, check=True)
            case_dir = out_dir / name
            result = json.loads(
                (case_dir / "sst" / "result.json").read_text(encoding="utf-8")
            )
            validation_profile = json.loads(json.dumps(profile))
            validation_profile["parameters"]["native_validation_supersteps"] = int(
                case["supersteps"]
            )
            validate_result(result, validation_profile, int(case["source"]))
            report = json.loads(
                (case_dir / "alignment.json").read_text(encoding="utf-8")
            )
            if not report["structure_matches"]:
                raise RuntimeError(f"{name}: native hardware structure mismatch")
            predictions.append(prediction_row(case, result, report))
            status = "PASS"
        except Exception as error:  # Preserve every completed case before failing.
            failures.append(f"{name}: {error}")
            status = "FAIL"
        case_manifests.append(
            {
                "case": name,
                "role": case["role"],
                "status": status,
                "runtime_seconds": time.monotonic() - started,
                "graph": case["graph"],
                "graph_sha256": case["graph_sha256"],
                "hardware_log": case["hardware_log"],
                "hardware_log_sha256": case["hardware_log_sha256"],
                "commands": {"convert": convert, "run": run, "analyze": analyze},
            }
        )
        if failures:
            break

    summaries = group_summary(predictions) if predictions else []
    out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(out_dir / "predictions.csv", predictions)
    write_csv(out_dir / "group_summary.csv", summaries)
    manifest = {
        "schema_version": 1,
        "matrix_id": matrix["matrix_id"],
        "claim_class": matrix["claim_class"],
        "timing_claim": "unfitted_trend_only_not_cycle_calibrated",
        "matrix": str(matrix_path),
        "matrix_sha256": sha256(matrix_path),
        "profile": matrix["profile"],
        "profile_sha256": sha256(repo_path(str(matrix["profile"]))),
        "artifact": matrix["artifact"],
        "selected_roles": sorted(roles),
        "selected_cases": [case["case"] for case in cases],
        "structure_gate_passed": not failures
        and len(predictions) == len(cases)
        and all(bool(row["structure_matches"]) for row in predictions),
        "timing_gate": "not_applied_before_mechanism_based_calibration",
        "failures": failures,
        "cases": case_manifests,
        "group_summary": summaries,
        "status": "PASS" if not failures else "FAIL",
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if failures:
        raise RuntimeError("native matrix failed: " + "; ".join(failures))
    print(
        f"PASS native hardware matrix: cases={len(predictions)} "
        f"structure={manifest['structure_gate_passed']} -> {out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
