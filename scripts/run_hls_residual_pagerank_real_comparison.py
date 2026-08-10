#!/usr/bin/env python3
"""Run real compact thresholded residual PageRank on Spine and GraSU."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_hls_pagerank_real_comparison import (  # noqa: E402
    DEFAULT_CAPABILITIES,
    DEFAULT_INPUT_MANIFEST,
    DEFAULT_SPINE_PROFILE,
    DEFAULT_SST,
    _display_path,
    _profile,
    _run_process,
    _select_runs,
    _validate_input_manifest,
    _write_csv,
)
from spine_cycle_sim.experiments.hls_pagerank_real_comparison import (  # noqa: E402
    residual_pair_row,
    residual_system_row,
    validate_grasu_residual_result,
    validate_spine_residual_result,
)
from spine_cycle_sim.experiments.shared_workloads import sha256_file  # noqa: E402


DEFAULT_GRASU_PROFILE = (
    ROOT
    / "configs"
    / "architectures"
    / "grasu_regraph_weighted_pma_hls_proposed_residual_pagerank_ff13a67.json"
)
PROFILE_SETS = {
    "legacy": {
        "spine_profile": DEFAULT_SPINE_PROFILE,
        "spine_profile_id": "spine_shared_engine_9c08763",
        "grasu_profile": DEFAULT_GRASU_PROFILE,
        "grasu_profile_id": (
            "grasu_regraph_weighted_pma_hls_proposed_residual_pagerank_ff13a67"
        ),
        "capability_catalog": DEFAULT_CAPABILITIES,
    },
    "candidate10_hls_v3": {
        "spine_profile": ROOT
        / "configs/architectures/spine_candidate10_normalized_v1.json",
        "spine_profile_id": "spine_candidate10_normalized_v1",
        "grasu_profile": ROOT
        / "configs/architectures/grasu_regraph_candidate10_normalized_hls_residual_pagerank_v3.json",
        "grasu_profile_id": (
            "grasu_regraph_candidate10_normalized_hls_residual_pagerank_v3"
        ),
        "capability_catalog": ROOT
        / "configs/contracts/grasu_regraph_candidate10_hls_capabilities_v3.json",
    },
}
PAGERANK_DAMPING = 0.85
PAGERANK_EPSILON = 1.0e-6
RESIDUAL_MAX_ITERATIONS = 256


def _command(
    run: Mapping[str, object],
    system: str,
    *,
    args: argparse.Namespace,
    out_dir: Path,
) -> list[str]:
    graph = ROOT / run["graph"]["path"]  # type: ignore[index]
    update = ROOT / run["update"]["path"]  # type: ignore[index]
    if system == "spine":
        command = [
            args.python,
            str(ROOT / "scripts" / "run_sst_spine_vertical.py"),
            "--no-build",
            "--scenario",
            "residual_pagerank",
            "--validation-mode",
            "generic",
            "--profile",
            str(args.spine_profile.resolve()),
            "--workload",
            str(graph.resolve()),
            "--update-workload",
            str(update.resolve()),
            "--pagerank-damping",
            str(PAGERANK_DAMPING),
            "--pagerank-epsilon",
            str(PAGERANK_EPSILON),
            "--residual-max-iterations",
            str(RESIDUAL_MAX_ITERATIONS),
            "--max-cycles",
            str(args.max_cycles),
            "--sst",
            str(args.sst.resolve()),
            "--lib-dir",
            str(args.lib_dir.resolve()),
            "--out-dir",
            str(out_dir.resolve()),
        ]
        if args.instantiate_all_hbm_channels:
            command.append("--instantiate-all-hbm-channels")
        return command
    if system == "grasu_regraph":
        command = [
            args.python,
            str(
                ROOT
                / "scripts"
                / "run_sst_grasu_regraph_hls_residual_pagerank.py"
            ),
            "--no-build",
            "--profile",
            str(args.grasu_profile.resolve()),
            "--capability-catalog",
            str(args.capability_catalog.resolve()),
            "--workload",
            str(graph.resolve()),
            "--update-workload",
            str(update.resolve()),
            "--max-cycles",
            str(args.max_cycles),
            "--sst",
            str(args.sst.resolve()),
            "--lib-dir",
            str(args.lib_dir.resolve()),
            "--out-dir",
            str(out_dir.resolve()),
        ]
        if args.instantiate_all_hbm_channels:
            command.append("--instantiate-all-hbm-channels")
        return command
    raise ValueError(f"unsupported system: {system}")


def _system_fingerprint_paths(
    args: argparse.Namespace, system: str
) -> list[Path]:
    """Keep one system's implementation changes from invalidating the other."""

    common = [
        Path(__file__),
        ROOT / "scripts" / "run_hls_pagerank_real_comparison.py",
        ROOT
        / "spine_cycle_sim"
        / "experiments"
        / "hls_pagerank_real_comparison.py",
        ROOT / "spine_cycle_sim" / "experiments" / "memory_traffic.py",
        args.input_manifest,
        args.sst,
    ]
    if system == "spine":
        plugin = getattr(args, "adopt_spine_plugin", None)
        return [
            *common,
            Path(plugin) if plugin is not None else args.lib_dir / "libspine_cycle.so",
            ROOT / "scripts" / "run_sst_spine_vertical.py",
            args.spine_profile,
        ]
    if system == "grasu_regraph":
        return [
            *common,
            args.lib_dir / "libspine_cycle.so",
            ROOT / "scripts" / "run_sst_grasu_regraph_hls_residual_pagerank.py",
            args.grasu_profile,
            args.capability_catalog,
        ]
    raise ValueError(f"unsupported system: {system}")


def _system_execution_sha256(args: argparse.Namespace, system: str) -> str:
    return hashlib.sha256(
        b"".join(
            path.resolve().read_bytes()
            for path in _system_fingerprint_paths(args, system)
        )
    ).hexdigest()


def _adopted_wall_seconds(system: str, payload: Mapping[str, object]) -> float:
    value = payload.get("sst_host_wall_seconds")
    if system == "spine" and value is None:
        value = payload.get("host_wall_seconds")
    try:
        wall_seconds = float(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError("adopted raw result has no valid SST wall time") from error
    if wall_seconds <= 0.0:
        raise RuntimeError("adopted raw result has non-positive SST wall time")
    return wall_seconds


def _run_system(
    run: dict[str, object],
    system: str,
    *,
    args: argparse.Namespace,
    spine_profile_id: str,
    spine_mhz: float,
    grasu_profile_id: str,
    grasu_mhz: float,
    execution_sha256: str,
) -> dict[str, object]:
    out_dir = args.out_dir / str(run["run_id"]) / system
    out_dir.mkdir(parents=True, exist_ok=True)
    command = _command(run, system, args=args, out_dir=out_dir)
    cache_path = out_dir / "comparison_cache.json"
    raw_result_path = out_dir / ("summary.json" if system == "spine" else "manifest.json")
    input_sha256 = hashlib.sha256(
        json.dumps(run, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    reusable = False
    adopted = False
    wall_seconds = -1.0
    if args.resume and cache_path.is_file():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        reusable = (
            cache.get("status") == "PASS"
            and cache.get("command") == command
            and cache.get("input_sha256") == input_sha256
            and cache.get("execution_sha256") == execution_sha256
        )
        if reusable:
            wall_seconds = float(cache["wall_seconds"])
    if (
        not reusable
        and args.resume
        and args.adopt_validated_results
        and raw_result_path.is_file()
    ):
        adopted = True
    if not reusable and not adopted:
        wall_seconds = _run_process(
            command, out_dir / "parent_driver.log", args.timeout_seconds
        )

    if system == "spine":
        result = json.loads(raw_result_path.read_text(encoding="utf-8"))
        problems = validate_spine_residual_result(
            run,
            result,
            expected_profile_id=spine_profile_id,
            expected_core_mhz=spine_mhz,
            damping=PAGERANK_DAMPING,
            epsilon=PAGERANK_EPSILON,
            max_iterations=RESIDUAL_MAX_ITERATIONS,
        )
        provenance_problems = []
        if result.get("architecture_profile_sha256") != sha256_file(
            args.spine_profile
        ):
            provenance_problems.append("profile_sha256")
        spine_plugin = getattr(args, "adopt_spine_plugin", None)
        expected_plugin = (
            Path(spine_plugin)
            if spine_plugin is not None
            else args.lib_dir / "libspine_cycle.so"
        )
        if result.get("sst_plugin_sha256") != sha256_file(expected_plugin):
            provenance_problems.append("sst_plugin_sha256")
        graph = ROOT / run["graph"]["path"]  # type: ignore[index]
        update = ROOT / run["update"]["path"]  # type: ignore[index]
        embedded_workload_hashes = all(
            key in result
            for key in ("workload_sha256", "update_workload_sha256")
        )
        if embedded_workload_hashes and result.get(
            "workload_sha256"
        ) != sha256_file(graph):
            provenance_problems.append("workload_sha256")
        if embedded_workload_hashes and result.get(
            "update_workload_sha256"
        ) != sha256_file(update):
            provenance_problems.append("update_workload_sha256")
        if adopted:
            wall_seconds = _adopted_wall_seconds(system, result)
        dram = {
            "reads": result["dram_reads"],
            "writes": result["dram_writes"],
            "activates": result["dram_activates"],
            "precharges": result["dram_precharges"],
            "total_energy_pj": result["dram_total_energy_pj"],
        }
        profile_id = spine_profile_id
    else:
        child = json.loads(raw_result_path.read_text(encoding="utf-8"))
        problems = validate_grasu_residual_result(
            run,
            child,
            expected_profile_sha256=sha256_file(args.grasu_profile),
            expected_core_mhz=grasu_mhz,
            damping=PAGERANK_DAMPING,
            epsilon=PAGERANK_EPSILON,
            max_iterations=RESIDUAL_MAX_ITERATIONS,
        )
        provenance_problems = []
        graph = ROOT / run["graph"]["path"]  # type: ignore[index]
        update = ROOT / run["update"]["path"]  # type: ignore[index]
        expected_provenance = {
            "workload_sha256": sha256_file(graph),
            "update_workload_sha256": sha256_file(update),
            "profile_sha256": sha256_file(args.grasu_profile),
            "sst_plugin_sha256": sha256_file(args.lib_dir / "libspine_cycle.so"),
        }
        provenance_problems.extend(
            key for key, expected in expected_provenance.items()
            if child.get(key) != expected
        )
        if adopted:
            wall_seconds = _adopted_wall_seconds(system, child)
        result = child["result"]
        dram = child["dram"]
        profile_id = grasu_profile_id
    problems.extend(provenance_problems)
    if problems:
        raise RuntimeError(f"{run['run_id']}/{system} failed gates: {problems}")
    row = residual_system_row(
        run,
        system=system,
        result=result,
        dram=dram,
        wall_seconds=wall_seconds,
        profile_id=profile_id,
    )
    row["raw_result_path"] = _display_path(raw_result_path)
    row["raw_result_sha256"] = sha256_file(raw_result_path)
    if not reusable:
        cache_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "status": "PASS",
                    "command": command,
                    "input_sha256": input_sha256,
                    "execution_sha256": execution_sha256,
                    "wall_seconds": wall_seconds,
                    "adopted_validated_result": adopted,
                    "embedded_workload_hashes": (
                        embedded_workload_hashes if system == "spine" else True
                    ),
                    "raw_result_sha256": sha256_file(raw_result_path),
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
    parser.add_argument("--input-manifest", type=Path, default=DEFAULT_INPUT_MANIFEST)
    parser.add_argument(
        "--profile-set", choices=tuple(PROFILE_SETS), default="legacy"
    )
    parser.add_argument("--spine-profile", type=Path)
    parser.add_argument("--grasu-profile", type=Path)
    parser.add_argument("--capability-catalog", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sst", type=Path, default=DEFAULT_SST)
    parser.add_argument("--lib-dir", type=Path, default=ROOT / "build" / "sst")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--run-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--max-cycles", type=int, default=100_000_000)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--adopt-validated-results",
        action="store_true",
        help=(
            "with --resume, accept an existing raw result only after current "
            "profile/plugin/workload and correctness-ledger validation"
        ),
    )
    parser.add_argument(
        "--adopt-spine-plugin",
        type=Path,
        help=(
            "reconstructed historical libspine_cycle.so accepted only for "
            "Spine raw-result adoption; its hash must match the raw summary"
        ),
    )
    parser.add_argument(
        "--adopt-spine-plugin-source-revision",
        help="auditable source revision used to rebuild --adopt-spine-plugin",
    )
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument(
        "--instantiate-all-hbm-channels",
        action="store_true",
        help="instantiate all 32 HBM controllers so DRAM background energy is comparable",
    )
    args = parser.parse_args()
    if args.jobs <= 0 or args.timeout_seconds <= 0.0 or args.max_cycles <= 0:
        raise ValueError("jobs, timeout, and max cycles must be positive")
    if args.adopt_validated_results and not args.resume:
        raise ValueError("--adopt-validated-results requires --resume")
    if (args.adopt_spine_plugin is None) != (
        args.adopt_spine_plugin_source_revision is None
    ):
        raise ValueError(
            "--adopt-spine-plugin and its source revision must be provided together"
        )
    if args.adopt_spine_plugin is not None:
        if not args.resume or not args.adopt_validated_results:
            raise ValueError(
                "--adopt-spine-plugin requires --resume --adopt-validated-results"
            )
        args.adopt_spine_plugin = args.adopt_spine_plugin.resolve()
        if not args.adopt_spine_plugin.is_file():
            raise FileNotFoundError(args.adopt_spine_plugin)
        revision_check = subprocess.run(
            [
                "git",
                "cat-file",
                "-e",
                f"{args.adopt_spine_plugin_source_revision}^{{commit}}",
            ],
            cwd=ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if revision_check.returncode != 0:
            raise ValueError("adopted Spine plugin source revision is not a commit")
    profile_set = PROFILE_SETS[args.profile_set]
    custom_spine_profile = args.spine_profile is not None
    custom_grasu_profile = args.grasu_profile is not None
    args.spine_profile = args.spine_profile or profile_set["spine_profile"]
    args.grasu_profile = args.grasu_profile or profile_set["grasu_profile"]
    args.capability_catalog = (
        args.capability_catalog or profile_set["capability_catalog"]
    )

    manifest = _validate_input_manifest(args.input_manifest)
    selected = _select_runs(list(manifest["runs"]), args.run_id, args.limit)
    if args.adopt_spine_plugin is not None:
        missing_raw = [
            str(run["run_id"])
            for run in selected
            if not (
                args.out_dir / str(run["run_id"]) / "spine" / "summary.json"
            ).is_file()
        ]
        if missing_raw:
            raise FileNotFoundError(
                "historical Spine plugin adoption requires existing summaries: "
                + ", ".join(missing_raw)
            )
    spine_profile, spine_mhz = _profile(
        args.spine_profile,
        None if custom_spine_profile else str(profile_set["spine_profile_id"]),
    )
    grasu_profile, grasu_mhz = _profile(
        args.grasu_profile,
        None if custom_grasu_profile else str(profile_set["grasu_profile_id"]),
    )
    parameters = grasu_profile["parameters"]
    if (
        abs(float(parameters["pagerank_damping"]) - PAGERANK_DAMPING) > 1.0e-9
        or abs(float(parameters["pagerank_epsilon"]) - PAGERANK_EPSILON) > 1.0e-15
        or int(parameters["pagerank_residual_max_iterations"])
        != RESIDUAL_MAX_ITERATIONS
    ):
        raise ValueError("GraSU profile does not match the residual contract")
    capabilities = json.loads(args.capability_catalog.read_text(encoding="utf-8"))
    grasu_capability = next(
        item
        for item in capabilities["profiles"]
        if item["profile_id"] == grasu_profile["profile_id"]
    )
    if grasu_capability["profile_sha256"] != sha256_file(args.grasu_profile):
        raise ValueError("GraSU capability/profile hash mismatch")
    if not args.no_build:
        subprocess.run(["make", "-C", "cpp/sst", "-j2"], cwd=ROOT, check=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    system_execution_sha256 = {
        system: _system_execution_sha256(args, system)
        for system in ("spine", "grasu_regraph")
    }
    execution_sha256 = hashlib.sha256(
        json.dumps(
            system_execution_sha256, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
    ).hexdigest()
    started = time.monotonic()
    rows: list[dict[str, object]] = []
    futures = {}
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        for run in selected:
            for system in ("spine", "grasu_regraph"):
                future = executor.submit(
                    _run_system,
                    run,
                    system,
                    args=args,
                    spine_profile_id=str(spine_profile["profile_id"]),
                    spine_mhz=spine_mhz,
                    grasu_profile_id=str(grasu_profile["profile_id"]),
                    grasu_mhz=grasu_mhz,
                    execution_sha256=system_execution_sha256[system],
                )
                futures[future] = (run["run_id"], system)
        for future in as_completed(futures):
            run_id, system = futures[future]
            row = future.result()
            rows.append(row)
            print(
                f"PASS {run_id}/{system}: e2e_ms={float(row['e2e_ms']):.6f} "
                f"iterations={row['iterations']}",
                flush=True,
            )
    rows.sort(key=lambda row: (str(row["run_id"]), str(row["system"])))
    by_run: dict[str, dict[str, dict[str, object]]] = {}
    for row in rows:
        by_run.setdefault(str(row["run_id"]), {})[str(row["system"])] = row
    pairs = [
        residual_pair_row(systems["spine"], systems["grasu_regraph"])
        for _, systems in sorted(by_run.items())
        if set(systems) == {"spine", "grasu_regraph"}
    ]
    if len(pairs) != len(selected):
        raise RuntimeError("residual comparison lacks one complete pair per run")
    vector_fields = {"ranks", "residuals", "frontier_in", "frontier_out"}
    csv_rows = [
        {key: value for key, value in row.items() if key not in vector_fields}
        for row in rows
    ]
    _write_csv(args.out_dir / "system_rows.csv", csv_rows)
    _write_csv(args.out_dir / "pairs.csv", pairs)
    complete = len(selected) == len(manifest["runs"]) and not args.run_id
    matrix_manifest = {
        "schema_version": 1,
        "matrix_id": "hls_residual_pagerank_real_compact_comparison_20260726",
        "status": "PASS",
        "complete_matrix": complete,
        "claim_class": "profile_clock_adjusted_real_compact_execution_driven",
        "profile_set": args.profile_set,
        "algorithm": "thresholded_residual_pagerank",
        "pagerank_damping": PAGERANK_DAMPING,
        "pagerank_epsilon": PAGERANK_EPSILON,
        "residual_max_iterations": RESIDUAL_MAX_ITERATIONS,
        "input_manifest": str(args.input_manifest.resolve()),
        "input_manifest_sha256": sha256_file(args.input_manifest),
        "spine_profile_id": spine_profile["profile_id"],
        "spine_profile_sha256": sha256_file(args.spine_profile),
        "grasu_profile_id": grasu_profile["profile_id"],
        "grasu_profile_sha256": sha256_file(args.grasu_profile),
        "capability_catalog_sha256": sha256_file(args.capability_catalog),
        "sst_plugin_path": str(
            (args.lib_dir / "libspine_cycle.so").resolve()
        ),
        "sst_plugin_sha256": sha256_file(
            args.lib_dir / "libspine_cycle.so"
        ),
        "adopted_spine_plugin": (
            {
                "path": str(args.adopt_spine_plugin),
                "sha256": sha256_file(args.adopt_spine_plugin),
                "source_revision": args.adopt_spine_plugin_source_revision,
            }
            if args.adopt_spine_plugin is not None
            else None
        ),
        "execution_sha256": execution_sha256,
        "system_execution_sha256": system_execution_sha256,
        "validated_raw_result_adoption_enabled": args.adopt_validated_results,
        "selected_run_ids": [run["run_id"] for run in selected],
        "instantiate_all_hbm_channels": args.instantiate_all_hbm_channels,
        "hbm_controller_instances": (
            32 if args.instantiate_all_hbm_channels else None
        ),
        "system_rows": len(rows),
        "pairs": len(pairs),
        "all_correct": all(int(row["correctness_mismatches"]) == 0 for row in rows)
        and all(bool(pair["cross_system_state_match"]) for pair in pairs),
        "matrix_wall_seconds": time.monotonic() - started,
        "system_rows_sha256": sha256_file(args.out_dir / "system_rows.csv"),
        "pairs_sha256": sha256_file(args.out_dir / "pairs.csv"),
        "limitations": [
            "Inputs are compact real-edge slices, not full datasets.",
            (
                "The Candidate10 comparison uses frozen HLS-derived normalized "
                "profiles; whole-system implementation evidence is reported separately."
                if args.profile_set == "candidate10_hls_v3"
                else "GraSU/ReGraph residual PageRank is proposed, not a compiled xclbin."
            ),
            "Simulator cycles are not calibrated cycle-for-cycle against hw.",
            (
                "DRAM energy includes all 32 HBM controller instances."
                if args.instantiate_all_hbm_channels
                else "DRAM energy covers active channels only and excludes idle-channel energy."
            ),
            (
                "Contiguous/repeated/discontinuous classes describe accepted "
                "backend requests per initiator and operation; they are not "
                "DRAM row-hit classifications."
            ),
            (
                "Actual requested bytes exclude DRAM burst amplification; "
                "complete DRAM plus on-chip energy remains open."
            ),
        ],
    }
    (args.out_dir / "matrix_manifest.json").write_text(
        json.dumps(matrix_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"PASS real residual PageRank comparison: pairs={len(pairs)} "
        f"complete={complete} wall_s={matrix_manifest['matrix_wall_seconds']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
