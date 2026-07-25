#!/usr/bin/env python3
"""Run the frozen normalized Spine versus GraSU/ReGraph comparison matrix."""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spine_cycle_sim.experiments import (  # noqa: E402
    build_invocation,
    implementation_fingerprint,
    pair_rows,
    select_runs,
    validate_shared_comparison_manifest,
    validate_system_result,
)
from spine_cycle_sim.experiments.comparison import (  # noqa: E402
    RunInvocation,
    load_system_result,
    result_row,
    sha256_file,
)


DEFAULT_MANIFEST = (
    ROOT / "configs" / "experiments" / "shared_comparison_workloads_20260725.json"
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _completed_row(
    run: dict[str, object],
    invocation: RunInvocation,
    *,
    wall_seconds: float,
    cache_reused: bool,
) -> dict[str, object]:
    result, dram = load_system_result(invocation)
    problems = validate_system_result(run, invocation, result, dram)
    if problems:
        raise RuntimeError(
            f"{invocation.run_id}/{invocation.system} parent gate failed: "
            + ", ".join(problems)
        )
    row = result_row(
        run, invocation, result, dram, wall_seconds=wall_seconds
    )
    row["cache_reused"] = cache_reused
    return row


def _run_one(
    run: dict[str, object],
    invocation: RunInvocation,
    *,
    timeout_seconds: float,
    resume: bool,
    implementation_sha256: str,
) -> dict[str, object]:
    invocation.out_dir.mkdir(parents=True, exist_ok=True)
    resume_path = invocation.out_dir / "shared_run.json"
    input_contract_sha256 = hashlib.sha256(
        json.dumps(run, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    if resume and resume_path.is_file():
        cached = json.loads(resume_path.read_text(encoding="utf-8"))
        if (
            cached.get("status") == "PASS"
            and cached.get("command") == list(invocation.command)
            and cached.get("input_contract_sha256") == input_contract_sha256
            and cached.get("implementation_sha256") == implementation_sha256
        ):
            return _completed_row(
                run,
                invocation,
                wall_seconds=float(cached["wall_seconds"]),
                cache_reused=True,
            )
    start = time.monotonic()
    process = subprocess.Popen(
        invocation.command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        stdout, _ = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as error:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, _ = process.communicate(timeout=10.0)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, _ = process.communicate()
        (invocation.out_dir / "driver.log").write_text(
            stdout, encoding="utf-8"
        )
        raise RuntimeError(
            f"{invocation.run_id}/{invocation.system} exceeded "
            f"{timeout_seconds:.1f}s and its process group was terminated"
        ) from error
    wall_seconds = time.monotonic() - start
    (invocation.out_dir / "driver.log").write_text(
        stdout, encoding="utf-8"
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"{invocation.run_id}/{invocation.system} failed with "
            f"rc={process.returncode}; see {invocation.out_dir / 'driver.log'}"
        )
    row = _completed_row(
        run, invocation, wall_seconds=wall_seconds, cache_reused=False
    )
    resume_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": invocation.run_id,
                "system": invocation.system,
                "command": list(invocation.command),
                "input_contract_sha256": input_contract_sha256,
                "implementation_sha256": implementation_sha256,
                "wall_seconds": wall_seconds,
                "row": row,
                "status": "PASS",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--system", action="append", choices=("spine", "grasu_regraph"))
    parser.add_argument("--role", action="append", default=[])
    parser.add_argument("--algorithm", action="append", default=[])
    parser.add_argument("--run-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--sst", type=Path, default=Path("/data/feiyang/sst/bin/sst"))
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument(
        "--spine-profile",
        type=Path,
        default=ROOT / "configs" / "architectures" / "spine_latest_afb8199.json",
    )
    args = parser.parse_args()
    if args.jobs <= 0 or args.timeout_seconds <= 0.0:
        raise ValueError("jobs and timeout must be positive")
    manifest = validate_shared_comparison_manifest(ROOT, args.manifest)
    selected = select_runs(
        manifest,
        roles=args.role,
        algorithms=args.algorithm,
        run_ids=args.run_id,
        limit=args.limit,
    )
    systems = args.system or ["spine", "grasu_regraph"]
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)
    implementation = implementation_fingerprint(
        [
            Path(__file__),
            ROOT / "spine_cycle_sim" / "experiments" / "comparison.py",
            ROOT / "spine_cycle_sim" / "experiments" / "shared_workloads.py",
            ROOT / "scripts" / "run_sst_spine_vertical.py",
            ROOT / "scripts" / "run_sst_grasu_regraph.py",
            ROOT / "scripts" / "run_sst_grasu_regraph_pagerank.py",
            ROOT / "scripts" / "run_sst_grasu_regraph_residual_pagerank.py",
            ROOT / "sst" / "spine_vertical_slice.py",
            ROOT / "sst" / "grasu_regraph_vertical.py",
            ROOT / "configs" / "memory" / "HBM2_1ch_x128.ini",
            ROOT
            / "configs"
            / "architectures"
            / "grasu_regraph_normalized_weighted_spine23.json",
            ROOT
            / "configs"
            / "architectures"
            / "grasu_regraph_normalized_pagerank_spine23.json",
            ROOT
            / "configs"
            / "architectures"
            / "grasu_regraph_normalized_residual_pagerank_spine23.json",
            args.spine_profile,
            args.lib_dir / "libspine_cycle.so",
            args.sst,
        ]
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    invocations: list[tuple[dict[str, object], RunInvocation]] = []
    for run in selected:
        for system in systems:
            invocations.append(
                (
                    run,
                    build_invocation(
                        ROOT,
                        run,
                        system=system,
                        output_root=args.out_dir,
                        python=args.python,
                        sst=args.sst,
                        lib_dir=args.lib_dir,
                        spine_profile=args.spine_profile,
                    ),
                )
            )

    matrix_start = time.monotonic()
    rows: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(
                _run_one,
                run,
                invocation,
                timeout_seconds=args.timeout_seconds,
                resume=args.resume,
                implementation_sha256=str(implementation["sha256"]),
            ): invocation
            for run, invocation in invocations
        }
        for future in as_completed(futures):
            invocation = futures[future]
            row = future.result()
            rows.append(row)
            print(
                f"PASS {invocation.run_id}/{invocation.system}: "
                f"cycles={row['cycles']} wall={float(row['wall_seconds']):.2f}s",
                flush=True,
            )
    matrix_wall_seconds = time.monotonic() - matrix_start
    rows.sort(key=lambda row: (str(row["run_id"]), str(row["system"])))
    pairs = pair_rows(rows)
    reused_rows = sum(bool(row["cache_reused"]) for row in rows)
    all_run_ids = {str(run["run_id"]) for run in manifest["runs"]}
    selected_run_ids = {str(run["run_id"]) for run in selected}
    complete_matrix = selected_run_ids == all_run_ids and set(systems) == {
        "spine",
        "grasu_regraph",
    }
    output: dict[str, Any] = {
        "schema_version": 1,
        "matrix_id": manifest["matrix_id"],
        "source_manifest": str(args.manifest.resolve()),
        "source_manifest_sha256": sha256_file(args.manifest.resolve()),
        "implementation": implementation,
        "claim_class": (
            "complete_normalized_structural_matrix"
            if complete_matrix
            else "filtered_normalized_structural_subset"
        ),
        "complete_matrix": complete_matrix,
        "systems": systems,
        "selected_run_ids": sorted(selected_run_ids),
        "matrix_wall_seconds": matrix_wall_seconds,
        "executed_rows": len(rows) - reused_rows,
        "reused_rows": reused_rows,
        "result_rows": len(rows),
        "paired_rows": len(pairs),
        "status": "PASS",
    }
    (args.out_dir / "comparison_manifest.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_csv(args.out_dir / "results.csv", rows)
    _write_csv(args.out_dir / "pairs.csv", pairs)
    print(
        f"PASS shared matrix: rows={len(rows)} pairs={len(pairs)} "
        f"complete={complete_matrix} wall={matrix_wall_seconds:.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
