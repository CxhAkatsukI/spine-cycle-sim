#!/usr/bin/env python3
"""Run and summarize the frozen Candidate10 shared-HBM sensitivity matrix."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    ROOT
    / "configs"
    / "experiments"
    / "candidate10_hbm_sensitivity_matrix_v1.json"
)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments.comparison import sha256_file  # noqa: E402


def _read_json(path: Path) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(document, dict):
        raise ValueError(f"expected JSON object: {path}")
    return document


def load_contract(path: Path) -> dict[str, object]:
    contract = _read_json(path.resolve())
    if contract.get("schema_version") != 1:
        raise ValueError("unsupported HBM sensitivity matrix schema")
    source_spec = contract.get("source_manifest")
    profile_spec = contract.get("hbm_profiles")
    run_ids = contract.get("run_ids")
    tolerance = contract.get("winner_tolerance_ratio")
    if (
        not isinstance(source_spec, dict)
        or not isinstance(profile_spec, dict)
        or not isinstance(run_ids, list)
        or not run_ids
        or len(set(run_ids)) != len(run_ids)
        or not isinstance(tolerance, (int, float))
        or float(tolerance) <= 1.0
    ):
        raise ValueError("invalid HBM sensitivity matrix contract")
    source_path = (ROOT / str(source_spec["path"])).resolve()
    if sha256_file(source_path) != source_spec.get("sha256"):
        raise ValueError("shared comparison source manifest hash mismatch")
    source = _read_json(source_path)
    available = {str(run["run_id"]): run for run in source["runs"]}  # type: ignore[index]
    missing = sorted(set(str(item) for item in run_ids) - set(available))
    if missing:
        raise ValueError(f"unknown sensitivity run IDs: {missing}")
    algorithms = {str(available[str(item)]["algorithm"]) for item in run_ids}
    required = {
        "weighted_sssp",
        "weighted_dynamic_sssp",
        "full_pagerank",
        "thresholded_residual_pagerank",
    }
    if algorithms != required:
        raise ValueError(f"sensitivity algorithms do not close: {algorithms}")
    profile_path = (ROOT / str(profile_spec["path"])).resolve()
    if sha256_file(profile_path) != profile_spec.get("sha256"):
        raise ValueError("HBM sensitivity profile manifest hash mismatch")
    profiles = _read_json(profile_path)
    if profiles.get("schema_version") != 1:
        raise ValueError("unsupported HBM profile schema")
    baseline = profiles["baseline"]  # type: ignore[index]
    profile_rows = [
        {
            "profile_id": "baseline",
            "axis": "baseline",
            "direction": "baseline",
            "path": str((ROOT / str(baseline["path"])).resolve()),
            "sha256": str(baseline["sha256"]),
        }
    ]
    for raw in profiles["profiles"]:  # type: ignore[index]
        profile = dict(raw)
        profile_rows.append(
            {
                "profile_id": str(profile["profile_id"]),
                "axis": str(profile["axis"]),
                "direction": str(profile["direction"]),
                "path": str((ROOT / str(profile["output"])).resolve()),
                "sha256": str(profile["sha256"]),
            }
        )
    for profile in profile_rows:
        selected = Path(str(profile["path"]))
        if not selected.is_file() or sha256_file(selected) != profile["sha256"]:
            raise ValueError(f"HBM sensitivity profile hash mismatch: {selected}")
    contract["resolved_source_manifest"] = str(source_path)
    contract["resolved_hbm_profile_manifest"] = str(profile_path)
    contract["resolved_profiles"] = profile_rows
    return contract


def select_profiles(
    profiles: Iterable[Mapping[str, object]], selected_ids: Iterable[str]
) -> list[Mapping[str, object]]:
    available = {str(row["profile_id"]): row for row in profiles}
    requested = set(selected_ids)
    if not requested:
        return list(available.values())
    unknown = requested - set(available)
    if unknown:
        raise ValueError(f"unknown HBM sensitivity profiles: {sorted(unknown)}")
    requested.add("baseline")
    return [row for profile_id, row in available.items() if profile_id in requested]


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _winner(speedup: float, tolerance: float) -> str:
    if speedup > tolerance:
        return "spine"
    if speedup < 1.0 / tolerance:
        return "grasu_regraph"
    return "tie"


def summarize_pairs(
    pairs_by_profile: Mapping[str, list[Mapping[str, str]]],
    profiles: Iterable[Mapping[str, object]],
    *,
    tolerance: float,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    profile_by_id = {str(row["profile_id"]): row for row in profiles}
    if "baseline" not in pairs_by_profile:
        raise ValueError("sensitivity analysis lacks baseline pairs")
    baseline = {
        str(row["run_id"]): row for row in pairs_by_profile["baseline"]
    }
    details: list[dict[str, object]] = []
    groups: list[dict[str, object]] = []
    for profile_id, rows in pairs_by_profile.items():
        if profile_id == "baseline":
            continue
        profile = profile_by_id[profile_id]
        current = {str(row["run_id"]): row for row in rows}
        if set(current) != set(baseline):
            raise ValueError(f"sensitivity pair coverage mismatch: {profile_id}")
        speedups: list[float] = []
        inversions = 0
        winner_changes = 0
        for run_id in sorted(baseline):
            base = baseline[run_id]
            row = current[run_id]
            base_spine = int(base["spine_cycles"])
            base_grasu = int(base["grasu_regraph_cycles"])
            spine = int(row["spine_cycles"])
            grasu = int(row["grasu_regraph_cycles"])
            base_speedup = float(base["spine_speedup_over_grasu"])
            speedup = float(row["spine_speedup_over_grasu"])
            base_winner = _winner(base_speedup, tolerance)
            current_winner = _winner(speedup, tolerance)
            inversion = {base_winner, current_winner} == {
                "spine",
                "grasu_regraph",
            }
            inversions += int(inversion)
            winner_changes += int(base_winner != current_winner)
            speedups.append(speedup)
            details.append(
                {
                    "profile_id": profile_id,
                    "axis": profile["axis"],
                    "direction": profile["direction"],
                    "run_id": run_id,
                    "role": row["role"],
                    "algorithm": row["algorithm"],
                    "baseline_spine_cycles": base_spine,
                    "sensitivity_spine_cycles": spine,
                    "spine_cycle_ratio": spine / base_spine,
                    "baseline_grasu_regraph_cycles": base_grasu,
                    "sensitivity_grasu_regraph_cycles": grasu,
                    "grasu_regraph_cycle_ratio": grasu / base_grasu,
                    "baseline_spine_speedup": base_speedup,
                    "sensitivity_spine_speedup": speedup,
                    "baseline_winner": base_winner,
                    "sensitivity_winner": current_winner,
                    "winner_changed": base_winner != current_winner,
                    "strict_rank_inversion": inversion,
                }
            )
        groups.append(
            {
                "profile_id": profile_id,
                "axis": profile["axis"],
                "direction": profile["direction"],
                "pairs": len(rows),
                "spine_speedup_geomean": math.exp(
                    sum(math.log(value) for value in speedups) / len(speedups)
                ),
                "winner_changes": winner_changes,
                "strict_rank_inversions": inversions,
            }
        )
    return details, groups


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty sensitivity table: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--profile-id", action="append", default=[])
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--sst", type=Path, default=Path("/data/feiyang/sst/bin/sst"))
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    args = parser.parse_args()
    if args.jobs <= 0 or args.timeout_seconds <= 0:
        raise ValueError("jobs and timeout must be positive")
    contract = load_contract(args.contract)
    profiles = select_profiles(
        contract["resolved_profiles"], args.profile_id  # type: ignore[arg-type]
    )
    if not args.analyze_only and not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if not args.analyze_only:
        for profile in profiles:
            profile_id = str(profile["profile_id"])
            command = [
                args.python,
                str(ROOT / "scripts" / "run_shared_comparison_matrix.py"),
                "--manifest",
                str(contract["resolved_source_manifest"]),
                "--out-dir",
                str((args.out_dir / profile_id).resolve()),
                "--jobs",
                str(args.jobs),
                "--timeout-seconds",
                str(args.timeout_seconds),
                "--claim-scope",
                "structural_exploratory",
                "--no-build",
                "--sst",
                str(args.sst.resolve()),
                "--lib-dir",
                str(args.lib_dir.resolve()),
                "--dram-config",
                str(profile["path"]),
            ]
            if args.resume:
                command.append("--resume")
            for run_id in contract["run_ids"]:  # type: ignore[index]
                command.extend(("--run-id", str(run_id)))
            log_path = args.out_dir / f"{profile_id}.runner.log"
            with log_path.open("w", encoding="utf-8") as log:
                completed = subprocess.run(
                    command,
                    cwd=ROOT,
                    text=True,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
            if completed.returncode != 0:
                raise RuntimeError(f"sensitivity profile failed: {profile_id}; see {log_path}")
    expected_profiles = {str(row["profile_id"]): row for row in profiles}
    pairs_by_profile = {
        profile_id: _read_csv(args.out_dir / profile_id / "pairs.csv")
        for profile_id in expected_profiles
    }
    details, groups = summarize_pairs(
        pairs_by_profile,
        expected_profiles.values(),
        tolerance=float(contract["winner_tolerance_ratio"]),
    )
    _write_csv(args.out_dir / "sensitivity_details.csv", details)
    _write_csv(args.out_dir / "sensitivity_summary.csv", groups)
    contract_sha = sha256_file(args.contract.resolve())
    output = {
        "schema_version": 1,
        "matrix_id": contract["matrix_id"],
        "contract": str(args.contract.resolve()),
        "contract_sha256": contract_sha,
        "profiles": list(expected_profiles),
        "run_ids": contract["run_ids"],
        "pairs_per_profile": len(pairs_by_profile["baseline"]),
        "strict_rank_inversions": sum(int(row["strict_rank_inversions"]) for row in groups),
        "status": "PASS",
    }
    output["sha256"] = hashlib.sha256(
        json.dumps(output, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    (args.out_dir / "sensitivity_manifest.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"PASS shared HBM sensitivity: profiles={len(expected_profiles)} "
        f"pairs={len(pairs_by_profile['baseline'])} "
        f"strict_rank_inversions={output['strict_rank_inversions']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
