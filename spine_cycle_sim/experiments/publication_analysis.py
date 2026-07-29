"""Correctness-gated analysis of formal publication campaign results."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PUBLICATION_RESULT_SYSTEMS = (
    "spine",
    "grasu_regraph_k1",
    "grasu_regraph_k4_shared",
)


def _stable_digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _case_group_identity(case: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "dataset_id": case["dataset_id"],
        "algorithm": case["algorithm"],
        "scenario": case["scenario"],
        "batch_size": case["batch_size"],
        "graph_sha256": case["graph"]["sha256"],
        "update_sha256": case["update"]["sha256"],
        "source": case["source"],
        "algorithm_parameters": case["algorithm_parameters"],
    }


def _scientific_signature(result: Mapping[str, Any]) -> str:
    row = result["row"]
    return _stable_digest(
        {
            "case": result["case"],
            "cycles": row["cycles"],
            "final_state": result["final_state"],
            "scalar_metrics": result.get("scalar_metrics", {}),
            "backend_arbitration": result.get("backend_arbitration"),
            "backend_traffic": result.get("backend_traffic"),
            "dram": result.get("dram"),
            "plugin_sha256": result["plugin_sha256"],
        }
    )


def _validate_case_result(result: Mapping[str, Any]) -> None:
    if result.get("schema_version") != 1 or result.get("status") != "pass":
        raise ValueError("publication case result is not passing schema v1")
    case = result.get("case")
    row = result.get("row")
    final = result.get("final_state")
    if not all(isinstance(value, Mapping) for value in (case, row, final)):
        raise ValueError("publication case result lacks case, row, or final state")
    if case.get("system") not in PUBLICATION_RESULT_SYSTEMS:
        raise ValueError(f"unknown publication result system: {case.get('system')}")
    row_system = row.get("system")
    compatible_internal_alias = (
        str(case.get("system", "")).startswith("grasu_regraph_")
        and row_system == "grasu_regraph"
    )
    if row_system != case.get("system") and not compatible_internal_alias:
        raise ValueError("publication case and row systems differ")
    if row.get("run_id") != case.get("execution_id"):
        raise ValueError("publication case and row execution IDs differ")
    if int(row.get("cycles", 0)) <= 0:
        raise ValueError("publication result cycles must be positive")
    if int(final.get("count", -1)) != int(case["graph"]["vertices"]):
        raise ValueError("publication final-state vector is incomplete")
    for key in (
        "architecture_correctness_mismatches",
        "mathematical_correctness_mismatches",
    ):
        if int(row.get(key, -1)) != 0:
            raise ValueError(f"publication result failed {key}")
    plugin_hash = result.get("plugin_sha256")
    if not (
        isinstance(plugin_hash, str)
        and len(plugin_hash) == 64
        and all(character in "0123456789abcdef" for character in plugin_hash)
    ):
        raise ValueError("publication result lacks a valid plugin hash")
    admission = result.get("admission", {})
    if admission.get("child_returncode") != 0:
        raise ValueError("publication child process did not pass")
    parent_checks = admission.get("parent_checks")
    if isinstance(parent_checks, Mapping) and not all(parent_checks.values()):
        raise ValueError("publication parent checks did not all pass")
    parent_problems = admission.get("parent_problems")
    if isinstance(parent_problems, list) and parent_problems:
        raise ValueError("publication parent admission has problems")
    arbitration = result.get("backend_arbitration")
    if isinstance(arbitration, Mapping) and arbitration.get("ledger_closed") is not True:
        raise ValueError("publication backend arbitration ledger is open")


def _metric(row: Mapping[str, Any], *keys: str, default: Any = 0) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return default


def _normalized_system_row(result: Mapping[str, Any]) -> dict[str, Any]:
    case = result["case"]
    raw = result["row"]
    scalar = result.get("scalar_metrics", {})
    traffic = result.get("backend_traffic") or {}
    combined = traffic.get("combined", {}) if isinstance(traffic, Mapping) else {}
    reads = traffic.get("reads", {}) if isinstance(traffic, Mapping) else {}
    writes = traffic.get("writes", {}) if isinstance(traffic, Mapping) else {}
    cycles = int(raw["cycles"])
    clock_mhz = float(_metric(raw, "clock_mhz", "core_mhz"))
    update_cycles = int(
        _metric(scalar, "update_cycles", "maintenance_cycles", default=0)
    )
    logical_mutations = int(case["update"]["user_mutations"])
    requests = int(_metric(combined, "requests", default=raw.get("backend_requests", 0)))
    contiguous = int(_metric(combined, "contiguous_requests", default=0))
    discontinuous = int(_metric(combined, "discontinuous_requests", default=0))
    classified = contiguous + discontinuous
    return {
        "execution_id": case["execution_id"],
        "logical_views": "+".join(sorted(set(result.get("logical_views", [])))),
        "group_id": _stable_digest(_case_group_identity(case))[:20],
        "dataset_id": case["dataset_id"],
        "dataset_kind": raw["dataset_kind"],
        "role": raw["role"],
        "algorithm": case["algorithm"],
        "scenario": case["scenario"],
        "batch_size": int(case["batch_size"]),
        "system": case["system"],
        "vertices": int(case["graph"]["vertices"]),
        "initial_edges": int(case["graph"]["records"]),
        "logical_user_mutations": logical_mutations,
        "physical_update_records": int(case["update"]["physical_records"]),
        "cycles": cycles,
        "clock_mhz": clock_mhz,
        "simulated_us": cycles / clock_mhz,
        "update_cycles": update_cycles,
        "update_mups": (
            logical_mutations * clock_mhz / update_cycles
            if update_cycles > 0
            else 0.0
        ),
        "e2e_mups": logical_mutations * clock_mhz / cycles,
        "backend_requests": requests,
        "read_bytes": int(_metric(reads, "bytes", default=raw.get("read_bytes", 0))),
        "write_bytes": int(_metric(writes, "bytes", default=raw.get("write_bytes", 0))),
        "contiguous_requests": contiguous,
        "discontinuous_requests": discontinuous,
        "sequential_request_fraction": contiguous / classified if classified else 0.0,
        "random_request_fraction": discontinuous / classified if classified else 0.0,
        "hbm_queue_stalls": int(
            _metric(raw, "hbm_queue_stalls", "backend_arbitration_request_waits")
        ),
        "dram_energy_pj": float(
            _metric(raw, "dram_energy_pj", "dram_total_energy_pj", default=0.0)
        ),
        "host_wall_seconds": float(
            _metric(raw, "host_wall_seconds", "wall_seconds", default=0.0)
        ),
        "final_state_sha256": result["final_state"]["sha256"],
        "plugin_sha256": result["plugin_sha256"],
    }


def _external_final_vector(result: Mapping[str, Any]) -> list[int | float]:
    path = Path(str(result.get("raw_result_path", "")))
    expected_hash = result.get("raw_result_sha256")
    if not path.is_file() or not isinstance(expected_hash, str):
        raise ValueError("publication result lacks its hashed raw result")
    if _sha256_file(path) != expected_hash:
        raise ValueError(f"publication raw result changed: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    algorithm = str(result["case"]["algorithm"])
    if algorithm == "weighted_sssp":
        keys = ("distances_external", "final_values")
    elif algorithm == "connected_components":
        keys = ("labels_external", "labels")
    else:
        keys = ("ranks_external", "ranks", "final_values")
    raw_values = next(
        (payload[key] for key in keys if isinstance(payload.get(key), list)),
        None,
    )
    if raw_values is None:
        raise ValueError(f"publication raw result lacks external {algorithm} state")
    if len(raw_values) != int(result["case"]["graph"]["vertices"]):
        raise ValueError("publication raw external vector is incomplete")
    if algorithm == "weighted_sssp":
        return [
            0xFFFFFFFF if int(value) >= 0x7FFFFFFE else int(value)
            for value in raw_values
        ]
    if algorithm == "connected_components":
        return [int(value) for value in raw_values]
    return [float(value) for value in raw_values]


def _cross_system_final_state(
    results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    hashes = {str(result["final_state"]["sha256"]) for result in results}
    if len(hashes) == 1:
        return {
            "passed": True,
            "method": "canonical_exact_sha256",
            "exact_match": True,
            "max_abs_error": 0.0,
            "l1_error": 0.0,
            "tolerance": 0.0,
        }
    algorithm = str(results[0]["case"]["algorithm"])
    vectors = [_external_final_vector(result) for result in results]
    reference = vectors[0]
    if algorithm in {"weighted_sssp", "connected_components"}:
        exact = all(vector == reference for vector in vectors[1:])
        return {
            "passed": exact,
            "method": "canonical_external_integer_vector",
            "exact_match": exact,
            "max_abs_error": 0.0 if exact else math.inf,
            "l1_error": 0.0 if exact else math.inf,
            "tolerance": 0.0,
        }
    tolerance = 1.0e-6
    max_abs = 0.0
    l1_error = 0.0
    exact = True
    for vector in vectors[1:]:
        for expected, actual in zip(reference, vector, strict=True):
            difference = abs(float(expected) - float(actual))
            max_abs = max(max_abs, difference)
            l1_error += difference
            exact &= difference == 0.0
    return {
        "passed": math.isfinite(max_abs) and max_abs <= tolerance,
        "method": "canonical_external_float_vector_tolerance",
        "exact_match": exact,
        "max_abs_error": max_abs,
        "l1_error": l1_error,
        "tolerance": tolerance,
    }


def analyze_publication_case_results(
    results: Sequence[Mapping[str, Any]],
    *,
    expected_execution_ids: Iterable[str] = (),
    require_complete: bool = False,
) -> dict[str, Any]:
    """Validate, de-duplicate, pair, and summarize formal case results."""

    by_execution: dict[str, Mapping[str, Any]] = {}
    signatures: dict[str, str] = {}
    duplicate_counts: dict[str, int] = {}
    for result in results:
        _validate_case_result(result)
        execution_id = str(result["case"]["execution_id"])
        signature = _scientific_signature(result)
        if execution_id in signatures and signatures[execution_id] != signature:
            raise ValueError(
                f"duplicate publication execution changed scientific result: {execution_id}"
            )
        signatures[execution_id] = signature
        by_execution[execution_id] = result
        duplicate_counts[execution_id] = duplicate_counts.get(execution_id, 0) + 1

    system_rows = [_normalized_system_row(result) for result in by_execution.values()]
    system_rows.sort(
        key=lambda row: (
            row["dataset_id"],
            row["algorithm"],
            row["scenario"],
            row["batch_size"],
            row["system"],
        )
    )
    groups: dict[str, dict[str, dict[str, Any]]] = {}
    for row in system_rows:
        groups.setdefault(row["group_id"], {})[row["system"]] = row

    correctness_groups: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    for group_id, systems in sorted(groups.items()):
        sample = next(iter(systems.values()))
        missing_systems = sorted(set(PUBLICATION_RESULT_SYSTEMS) - set(systems))
        group_results = [
            by_execution[row["execution_id"]] for row in systems.values()
        ]
        equivalence = _cross_system_final_state(group_results)
        if not equivalence["passed"]:
            raise ValueError(f"cross-system final state mismatch for {group_id}")
        correctness_groups.append(
            {
                "group_id": group_id,
                "dataset_id": sample["dataset_id"],
                "algorithm": sample["algorithm"],
                "scenario": sample["scenario"],
                "batch_size": sample["batch_size"],
                "systems_present": "+".join(sorted(systems)),
                "missing_systems": "+".join(missing_systems),
                "complete_triplet": not missing_systems,
                "final_state_match": equivalence["passed"],
                "final_state_method": equivalence["method"],
                "final_state_exact_match": equivalence["exact_match"],
                "cross_system_max_abs_error": equivalence["max_abs_error"],
                "cross_system_l1_error": equivalence["l1_error"],
                "cross_system_tolerance": equivalence["tolerance"],
            }
        )
        spine = systems.get("spine")
        if spine is None:
            continue
        for competitor in ("grasu_regraph_k1", "grasu_regraph_k4_shared"):
            other = systems.get(competitor)
            if other is None:
                continue
            pair_rows.append(
                {
                    "group_id": group_id,
                    "dataset_id": sample["dataset_id"],
                    "dataset_kind": sample["dataset_kind"],
                    "algorithm": sample["algorithm"],
                    "scenario": sample["scenario"],
                    "batch_size": sample["batch_size"],
                    "competitor": competitor,
                    "spine_cycles": spine["cycles"],
                    "competitor_cycles": other["cycles"],
                    "spine_speedup": other["cycles"] / spine["cycles"],
                    "spine_update_cycles": spine["update_cycles"],
                    "competitor_update_cycles": other["update_cycles"],
                    "spine_update_speedup": (
                        other["update_cycles"] / spine["update_cycles"]
                        if spine["update_cycles"] > 0
                        and other["update_cycles"] > 0
                        else 0.0
                    ),
                    "spine_memory_bytes": spine["read_bytes"] + spine["write_bytes"],
                    "competitor_memory_bytes": other["read_bytes"] + other["write_bytes"],
                    "spine_random_request_fraction": spine["random_request_fraction"],
                    "competitor_random_request_fraction": other["random_request_fraction"],
                    "spine_dram_energy_pj": spine["dram_energy_pj"],
                    "competitor_dram_energy_pj": other["dram_energy_pj"],
                    "spine_energy_advantage": (
                        other["dram_energy_pj"] / spine["dram_energy_pj"]
                        if spine["dram_energy_pj"] > 0
                        else 0.0
                    ),
                }
            )

    expected = set(expected_execution_ids)
    observed = set(by_execution)
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected) if expected else []
    incomplete_groups = sum(
        not row["complete_triplet"] for row in correctness_groups
    )
    complete = not missing and incomplete_groups == 0
    if require_complete and not complete:
        raise ValueError(
            "publication result set is incomplete: "
            f"missing_executions={len(missing)} incomplete_groups={incomplete_groups}"
        )
    return {
        "schema_version": 1,
        "analysis_id": "large_graph_publication_results_v1",
        "status": "PASS" if complete else "PARTIAL",
        "observed_executions": len(observed),
        "expected_executions": len(expected),
        "duplicate_executions": sum(count - 1 for count in duplicate_counts.values()),
        "complete_triplets": sum(
            bool(row["complete_triplet"]) for row in correctness_groups
        ),
        "incomplete_triplets": incomplete_groups,
        "missing_execution_ids": missing,
        "unexpected_execution_ids": unexpected,
        "system_rows": system_rows,
        "pair_rows": pair_rows,
        "correctness_groups": correctness_groups,
    }


def load_case_results(roots: Sequence[Path]) -> list[dict[str, Any]]:
    paths: set[Path] = set()
    for root in roots:
        paths.update(root.resolve().glob("runs/*/case_result.json"))
    return [json.loads(path.read_text(encoding="ascii")) for path in sorted(paths)]


def expected_execution_ids(manifests: Sequence[Path]) -> set[str]:
    expected: set[str] = set()
    for path in manifests:
        payload = json.loads(path.read_text(encoding="ascii"))
        views = payload.get("execution_views")
        if not isinstance(views, Mapping):
            raise ValueError(f"campaign manifest lacks execution_views: {path}")
        expected.update(str(value) for value in views)
    return expected


def write_publication_analysis(output_dir: Path, analysis: Mapping[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    compact = {key: value for key, value in analysis.items() if not key.endswith("_rows")}
    (output_dir / "summary.json").write_text(
        json.dumps(compact, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    for name in ("system_rows", "pair_rows", "correctness_groups"):
        rows = list(analysis[name])
        path = output_dir / f"{name}.csv"
        if not rows:
            path.write_text("", encoding="ascii")
            continue
        with path.open("w", encoding="ascii", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
