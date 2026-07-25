"""Execution and result contracts for the shared normalized comparison matrix."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SYSTEMS = ("spine", "grasu_regraph")


@dataclass(frozen=True)
class RunInvocation:
    run_id: str
    system: str
    command: tuple[str, ...]
    out_dir: Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def implementation_fingerprint(paths: Iterable[Path]) -> dict[str, object]:
    files: list[dict[str, str]] = []
    for path in sorted({item.resolve() for item in paths}, key=str):
        if not path.is_file():
            raise ValueError(f"comparison implementation input is missing: {path}")
        files.append({"path": str(path), "sha256": sha256_file(path)})
    digest = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    return {"sha256": digest, "files": files}


def artifact_path(root: Path, artifact: Mapping[str, object]) -> Path:
    path = (root / str(artifact["path"])).resolve()
    if not path.is_file() or sha256_file(path) != artifact["sha256"]:
        raise ValueError(f"shared comparison artifact is missing or changed: {path}")
    return path


def select_runs(
    manifest: Mapping[str, object],
    *,
    roles: Sequence[str] = (),
    algorithms: Sequence[str] = (),
    run_ids: Sequence[str] = (),
    limit: int | None = None,
) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    for raw_run in manifest["runs"]:  # type: ignore[index]
        run = dict(raw_run)
        if roles and run["role"] not in roles:
            continue
        if algorithms and run["algorithm"] not in algorithms:
            continue
        if run_ids and run["run_id"] not in run_ids:
            continue
        selected.append(run)
    if limit is not None:
        if limit <= 0:
            raise ValueError("run limit must be positive")
        selected = selected[:limit]
    if not selected:
        raise ValueError("shared comparison selection is empty")
    return selected


def _spine_scenario(run: Mapping[str, object]) -> str:
    algorithm = str(run["algorithm"])
    if algorithm == "weighted_sssp":
        return "weighted_sssp"
    if algorithm == "weighted_dynamic_sssp":
        scenario = str(run["scenario"])
        if scenario == "incremental_insert":
            return "dynamic_sssp"
        if scenario == "full_rebuild_increase":
            return "dynamic_sssp_increase"
        return "dynamic_sssp_delete"
    if algorithm == "full_pagerank":
        return "full_pagerank"
    if algorithm == "thresholded_residual_pagerank":
        return "residual_pagerank"
    raise ValueError(f"unsupported shared algorithm: {algorithm}")


def build_invocation(
    root: Path,
    run: Mapping[str, object],
    *,
    system: str,
    output_root: Path,
    python: str,
    sst: Path,
    lib_dir: Path,
    spine_profile: Path,
) -> RunInvocation:
    if system not in SYSTEMS:
        raise ValueError(f"unsupported comparison system: {system}")
    run_id = str(run["run_id"])
    out_dir = (output_root / run_id / system).resolve()
    graph = artifact_path(root, run["graph"])  # type: ignore[arg-type]
    algorithm = str(run["algorithm"])
    common = [
        python,
        "",
        "--out-dir",
        str(out_dir),
        "--sst",
        str(sst.resolve()),
        "--lib-dir",
        str(lib_dir.resolve()),
        "--no-build",
    ]
    if system == "spine":
        common[1] = str(root / "scripts" / "run_sst_spine_vertical.py")
        command = common + [
            "--scenario",
            _spine_scenario(run),
            "--validation-mode",
            "generic",
            "--profile",
            str(spine_profile.resolve()),
            "--workload",
            str(graph),
            "--source",
            str(run.get("source", 0)),
            "--max-cycles",
            "100000000",
            "--max-rounds",
            str(run.get("max_rounds", 256)),
        ]
        if algorithm == "weighted_dynamic_sssp":
            update = artifact_path(root, run["update"])  # type: ignore[arg-type]
            command.extend(("--update-workload", str(update)))
        elif algorithm == "full_pagerank":
            command.extend(
                (
                    "--pagerank-iterations",
                    str(run["iterations"]),
                    "--pagerank-damping",
                    str(run["damping"]),
                )
            )
        elif algorithm == "thresholded_residual_pagerank":
            command.extend(
                (
                    "--pagerank-damping",
                    str(run["damping"]),
                    "--pagerank-epsilon",
                    str(run["epsilon"]),
                    "--residual-max-iterations",
                    str(run["max_iterations"]),
                )
            )
    elif algorithm in {"weighted_sssp", "weighted_dynamic_sssp"}:
        common[1] = str(root / "scripts" / "run_sst_grasu_regraph.py")
        update = artifact_path(root, run["update"])  # type: ignore[arg-type]
        command = common + [
            "--profile",
            str(
                root
                / "configs"
                / "architectures"
                / "grasu_regraph_normalized_weighted_spine23.json"
            ),
            "--workload",
            str(graph),
            "--update-workload",
            str(update),
            "--source",
            str(run.get("source", 0)),
            "--max-cycles",
            "100000000",
            "--max-rounds",
            str(run.get("max_rounds", 256)),
        ]
    elif algorithm == "full_pagerank":
        common[1] = str(root / "scripts" / "run_sst_grasu_regraph_pagerank.py")
        command = common + [
            "--profile",
            str(
                root
                / "configs"
                / "architectures"
                / "grasu_regraph_normalized_pagerank_spine23.json"
            ),
            "--workload",
            str(graph),
            "--iterations",
            str(run["iterations"]),
            "--damping",
            str(run["damping"]),
            "--max-cycles",
            "100000000",
        ]
    else:
        common[1] = str(
            root / "scripts" / "run_sst_grasu_regraph_residual_pagerank.py"
        )
        command = common + [
            "--profile",
            str(
                root
                / "configs"
                / "architectures"
                / "grasu_regraph_normalized_residual_pagerank_spine23.json"
            ),
            "--workload",
            str(graph),
            "--damping",
            str(run["damping"]),
            "--epsilon",
            str(run["epsilon"]),
            "--max-iterations",
            str(run["max_iterations"]),
            "--max-cycles",
            "100000000",
        ]
    return RunInvocation(run_id, system, tuple(command), out_dir)


def expected_oracles(algorithm: str) -> tuple[str, str]:
    if algorithm in {"weighted_sssp", "weighted_dynamic_sssp"}:
        return "synchronous_frontier_uint32", "uint64_dijkstra"
    if algorithm == "full_pagerank":
        return "iterative_float32", "iterative_float64"
    if algorithm == "thresholded_residual_pagerank":
        return (
            "thresholded_residual_float32",
            "full_pagerank_float64_200_iterations",
        )
    raise ValueError(f"unsupported algorithm: {algorithm}")


def load_system_result(
    invocation: RunInvocation,
) -> tuple[dict[str, object], dict[str, object]]:
    if invocation.system == "spine":
        summary_path = invocation.out_dir / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        result = dict(summary)
        dram = {
            "channels": summary.get("dram_channels"),
            "reads": summary.get("dram_reads"),
            "writes": summary.get("dram_writes"),
            "activates": summary.get("dram_activates"),
            "precharges": summary.get("dram_precharges"),
            "total_energy_pj": summary.get("dram_total_energy_pj"),
        }
    else:
        manifest_path = invocation.out_dir / "manifest.json"
        child = json.loads(manifest_path.read_text(encoding="utf-8"))
        result = dict(child["result"])
        dram = dict(child["dram"])
    return result, dram


def validate_system_result(
    run: Mapping[str, object],
    invocation: RunInvocation,
    result: Mapping[str, object],
    dram: Mapping[str, object],
    *,
    expected_clock_mhz: float = 150.0,
) -> list[str]:
    architecture_oracle, mathematical_oracle = expected_oracles(
        str(run["algorithm"])
    )
    expected_vertices = int(run["graph"]["vertices"])  # type: ignore[index]
    expected_edges = int(run["graph"]["records"])  # type: ignore[index]
    result_edges_key = (
        "input_edges" if invocation.system == "spine" else "initial_edges"
    )
    problems: list[str] = []
    checks = {
        "success": result.get("success") is True,
        "architecture_correctness": result.get(
            "architecture_correctness_mismatches"
        )
        == 0,
        "mathematical_correctness": result.get(
            "mathematical_correctness_mismatches"
        )
        == 0,
        "combined_correctness": result.get("correctness_mismatches") == 0,
        "architecture_oracle": result.get("architecture_oracle")
        == architecture_oracle,
        "mathematical_oracle": result.get("mathematical_oracle")
        == mathematical_oracle,
        "clock": abs(float(result.get("core_mhz", -1.0)) - expected_clock_mhz)
        < 1.0e-9,
        "vertices": result.get("vertices") == expected_vertices,
        "edges": result.get(result_edges_key) == expected_edges,
        "dram_channels": dram.get("channels") == 32,
        "dram_closure": int(dram.get("reads", -1))
        + int(dram.get("writes", -1))
        == result.get("backend_requests"),
    }
    if str(run["algorithm"]) == "weighted_dynamic_sssp":
        expected_updates = int(run["update"]["records"])  # type: ignore[index]
        checks["updates"] = (
            result.get("update_edges") == expected_updates
            if invocation.system == "spine"
            else result.get("updates") == expected_updates
        )
    for name, passed in checks.items():
        if not passed:
            problems.append(name)
    return problems


def result_row(
    run: Mapping[str, object],
    invocation: RunInvocation,
    result: Mapping[str, object],
    dram: Mapping[str, object],
    *,
    wall_seconds: float,
) -> dict[str, object]:
    cycles = int(result["cycles"])
    core_mhz = float(result["core_mhz"])
    return {
        "run_id": invocation.run_id,
        "fixture_id": run["fixture_id"],
        "dataset_kind": run["dataset_kind"],
        "role": run["role"],
        "algorithm": run["algorithm"],
        "system": invocation.system,
        "claim_class": result.get("claim_class", "normalized_structural_simulation"),
        "cycles": cycles,
        "core_mhz": core_mhz,
        "simulated_ms": cycles / (core_mhz * 1000.0),
        "wall_seconds": wall_seconds,
        "vertices": result["vertices"],
        "input_edges": run["graph"]["records"],  # type: ignore[index]
        "updates": run.get("update", {}).get("records", 0),  # type: ignore[union-attr]
        "backend_requests": result["backend_requests"],
        "dram_reads": dram["reads"],
        "dram_writes": dram["writes"],
        "dram_activates": dram.get("activates", 0),
        "dram_precharges": dram.get("precharges", 0),
        "dram_total_energy_pj": dram.get("total_energy_pj", 0.0),
        "architecture_correctness_mismatches": result[
            "architecture_correctness_mismatches"
        ],
        "mathematical_correctness_mismatches": result[
            "mathematical_correctness_mismatches"
        ],
    }


def pair_rows(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    by_run: dict[str, dict[str, Mapping[str, object]]] = {}
    for row in rows:
        by_run.setdefault(str(row["run_id"]), {})[str(row["system"])] = row
    paired: list[dict[str, object]] = []
    for run_id in sorted(by_run):
        systems = by_run[run_id]
        if set(systems) != set(SYSTEMS):
            continue
        spine = systems["spine"]
        grasu = systems["grasu_regraph"]
        if float(spine["core_mhz"]) != float(grasu["core_mhz"]):
            raise ValueError(f"normalized pair has mismatched clocks: {run_id}")
        paired.append(
            {
                "run_id": run_id,
                "fixture_id": spine["fixture_id"],
                "dataset_kind": spine["dataset_kind"],
                "role": spine["role"],
                "algorithm": spine["algorithm"],
                "spine_cycles": spine["cycles"],
                "grasu_regraph_cycles": grasu["cycles"],
                "spine_simulated_ms": spine["simulated_ms"],
                "grasu_regraph_simulated_ms": grasu["simulated_ms"],
                "spine_speedup_over_grasu": float(grasu["cycles"])
                / float(spine["cycles"]),
                "claim_label": "normalized_structural_execution_driven",
            }
        )
    return paired
