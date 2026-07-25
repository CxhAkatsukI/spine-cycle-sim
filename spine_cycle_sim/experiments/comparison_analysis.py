"""Publication-facing analysis for a completed normalized comparison matrix."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Iterable, Mapping


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def geometric_mean(values: Iterable[float]) -> float:
    samples = list(values)
    if not samples or any(
        not math.isfinite(value) or value <= 0.0 for value in samples
    ):
        raise ValueError("geometric mean requires finite positive samples")
    return math.exp(sum(math.log(value) for value in samples) / len(samples))


def classify_phase_bottleneck(phase_cycles: int, total_cycles: int) -> str:
    if total_cycles <= 0 or not 0 <= phase_cycles <= total_cycles:
        raise ValueError("phase cycles must lie within positive total cycles")
    fraction = phase_cycles / total_cycles
    if fraction >= 0.55:
        return "structure_update_dominant"
    if fraction <= 0.45:
        return "compute_dominant"
    return "balanced"


def aggregate_dram_stats(dram_dir: Path) -> dict[str, int | float]:
    paths = sorted(dram_dir.glob("channel*/dramsim3.json"))
    if not paths:
        raise ValueError(f"no DRAMSim3 evidence under {dram_dir}")
    totals: dict[str, int | float] = {
        "channels": 0,
        "reads": 0,
        "writes": 0,
        "read_row_hits": 0,
        "write_row_hits": 0,
        "activates": 0,
        "precharges": 0,
        "total_energy_pj": 0.0,
        "weighted_read_latency": 0.0,
        "weighted_write_latency": 0.0,
        "write_latency_samples": 0,
    }
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if len(payload) != 1:
            raise ValueError(f"expected one DRAM channel record in {path}")
        row = next(iter(payload.values()))
        reads = int(row["num_reads_done"])
        writes = int(row["num_writes_done"])
        totals["channels"] += 1
        totals["reads"] += reads
        totals["writes"] += writes
        totals["read_row_hits"] += int(row["num_read_row_hits"])
        totals["write_row_hits"] += int(row["num_write_row_hits"])
        totals["activates"] += int(row["num_act_cmds"])
        totals["precharges"] += int(row["num_pre_cmds"])
        totals["total_energy_pj"] += float(row["total_energy"])
        totals["weighted_read_latency"] += reads * float(row["average_read_latency"])
        if writes:
            write_histogram = row.get("write_latency")
            if isinstance(write_histogram, dict):
                histogram_writes = sum(
                    int(count) for count in write_histogram.values()
                )
                totals["write_latency_samples"] += histogram_writes
                totals["weighted_write_latency"] += sum(
                    int(latency) * int(count)
                    for latency, count in write_histogram.items()
                )
    reads = int(totals["reads"])
    writes = int(totals["writes"])
    write_latency_samples = int(totals["write_latency_samples"])
    requests = reads + writes
    row_hits = int(totals["read_row_hits"]) + int(totals["write_row_hits"])
    totals["requests"] = requests
    totals["row_hit_rate"] = row_hits / requests if requests else 0.0
    totals["average_read_latency"] = (
        float(totals.pop("weighted_read_latency")) / reads if reads else 0.0
    )
    totals["average_write_latency"] = (
        float(totals.pop("weighted_write_latency")) / write_latency_samples
        if write_latency_samples
        else 0.0
    )
    totals["write_latency_coverage"] = (
        write_latency_samples / writes if writes else 1.0
    )
    return totals


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty analysis table: {path}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _load_raw_result(run_dir: Path, system: str) -> dict[str, object]:
    if system == "spine":
        return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    child = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    return dict(child["result"])


def _int(row: Mapping[str, object], key: str) -> int:
    return int(row[key])


def _float(row: Mapping[str, object], key: str) -> float:
    value = float(row[key])
    if not math.isfinite(value):
        raise ValueError(f"non-finite {key}: {row[key]}")
    return value


def enrich_system_row(
    output_root: Path, row: Mapping[str, object]
) -> dict[str, object]:
    run_id = str(row["run_id"])
    system = str(row["system"])
    run_dir = output_root / run_id / system
    result = _load_raw_result(run_dir, system)
    dram = aggregate_dram_stats(run_dir / "dram")
    cycles = _int(row, "cycles")
    backend_requests = _int(row, "backend_requests")
    phase_kind = "maintenance" if system == "spine" else "pma_update"
    phase_cycles = int(
        result.get("maintenance_cycles", 0)
        if system == "spine"
        else result.get("update_cycles", 0)
    )
    if int(dram["requests"]) != backend_requests:
        raise ValueError(f"{run_id}/{system}: raw DRAM request closure failed")
    if int(dram["channels"]) != _int(row, "bound_dram_channels"):
        raise ValueError(f"{run_id}/{system}: raw DRAM channel closure failed")
    if any(
        int(result.get(field, -1)) != 0
        for field in (
            "correctness_mismatches",
            "architecture_correctness_mismatches",
            "mathematical_correctness_mismatches",
        )
    ):
        raise ValueError(f"{run_id}/{system}: correctness mismatch in raw result")
    stream_stalls = int(
        result.get("edge_axis_push_stalls", 0)
        if system == "spine"
        else result.get("axis_push_stalls", 0)
    )
    return {
        "run_id": run_id,
        "fixture_id": row["fixture_id"],
        "dataset_kind": row["dataset_kind"],
        "role": row["role"],
        "algorithm": row["algorithm"],
        "system": system,
        "claim_class": row["claim_class"],
        "cycles": cycles,
        "simulated_ms": _float(row, "simulated_ms"),
        "phase_kind": phase_kind,
        "phase_cycles": phase_cycles,
        "compute_cycles": cycles - phase_cycles,
        "phase_fraction": phase_cycles / cycles,
        "phase_bottleneck": classify_phase_bottleneck(phase_cycles, cycles),
        "backend_requests": backend_requests,
        "backend_requests_per_cycle": backend_requests / cycles,
        "dram_reads": int(dram["reads"]),
        "dram_writes": int(dram["writes"]),
        "dram_row_hit_rate": float(dram["row_hit_rate"]),
        "dram_average_read_latency": float(dram["average_read_latency"]),
        "dram_average_write_latency": float(dram["average_write_latency"]),
        "dram_write_latency_coverage": float(dram["write_latency_coverage"]),
        "dram_activates": int(dram["activates"]),
        "dram_precharges": int(dram["precharges"]),
        "active_channel_dram_energy_pj": float(dram["total_energy_pj"]),
        "bound_dram_channels": int(dram["channels"]),
        "backend_submit_stalls": int(result.get("backend_submit_stalls", 0)),
        "backend_response_queue_stalls": int(
            result.get("backend_response_queue_stalls", 0)
        ),
        "stream_push_stalls": stream_stalls,
        "energy_claim": "sparse_active_channel_dramsim3_only",
    }


def build_pair_details(
    system_rows: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    by_run: dict[str, dict[str, Mapping[str, object]]] = {}
    for row in system_rows:
        by_run.setdefault(str(row["run_id"]), {})[str(row["system"])] = row
    pairs: list[dict[str, object]] = []
    for run_id in sorted(by_run):
        systems = by_run[run_id]
        if set(systems) != {"spine", "grasu_regraph"}:
            raise ValueError(f"unpaired comparison row: {run_id}")
        spine = systems["spine"]
        grasu = systems["grasu_regraph"]
        spine_cycles = _int(spine, "cycles")
        grasu_cycles = _int(grasu, "cycles")
        spine_requests = _int(spine, "backend_requests")
        grasu_requests = _int(grasu, "backend_requests")
        spine_energy = _float(spine, "active_channel_dram_energy_pj")
        grasu_energy = _float(grasu, "active_channel_dram_energy_pj")
        pairs.append(
            {
                "run_id": run_id,
                "fixture_id": spine["fixture_id"],
                "dataset_kind": spine["dataset_kind"],
                "role": spine["role"],
                "algorithm": spine["algorithm"],
                "spine_cycles": spine_cycles,
                "grasu_regraph_cycles": grasu_cycles,
                "spine_speedup_over_grasu": grasu_cycles / spine_cycles,
                "spine_backend_requests": spine_requests,
                "grasu_regraph_backend_requests": grasu_requests,
                "spine_request_advantage": grasu_requests / spine_requests,
                "spine_dram_row_hit_rate": spine["dram_row_hit_rate"],
                "grasu_regraph_dram_row_hit_rate": grasu["dram_row_hit_rate"],
                "spine_active_channel_dram_energy_pj": spine_energy,
                "grasu_regraph_active_channel_dram_energy_pj": grasu_energy,
                "spine_active_dram_energy_advantage": grasu_energy / spine_energy,
                "spine_phase_bottleneck": spine["phase_bottleneck"],
                "grasu_regraph_phase_bottleneck": grasu["phase_bottleneck"],
                "claim_label": "normalized_structural_execution_driven",
                "energy_claim": "sparse_active_channel_dramsim3_only",
            }
        )
    return pairs


def summarize_pairs(
    pairs: list[Mapping[str, object]], group_type: str, group_value: str
) -> dict[str, object]:
    if group_type == "overall":
        selected = pairs
    else:
        selected = [row for row in pairs if str(row[group_type]) == group_value]
    if not selected:
        raise ValueError(f"empty pair summary group: {group_type}={group_value}")
    speedups = [_float(row, "spine_speedup_over_grasu") for row in selected]
    traffic = [_float(row, "spine_request_advantage") for row in selected]
    energy = [_float(row, "spine_active_dram_energy_advantage") for row in selected]
    return {
        "group_type": group_type,
        "group_value": group_value,
        "pairs": len(selected),
        "spine_wins": sum(value > 1.0 for value in speedups),
        "ties": sum(abs(value - 1.0) <= 1.0e-12 for value in speedups),
        "grasu_regraph_wins": sum(value < 1.0 for value in speedups),
        "speedup_geomean": geometric_mean(speedups),
        "speedup_median": median(speedups),
        "speedup_min": min(speedups),
        "speedup_max": max(speedups),
        "request_advantage_geomean": geometric_mean(traffic),
        "request_advantage_median": median(traffic),
        "active_dram_energy_advantage_geomean": geometric_mean(energy),
        "active_dram_energy_advantage_median": median(energy),
        "energy_claim": "sparse_active_channel_dramsim3_only",
    }


def group_summaries(pairs: list[Mapping[str, object]]) -> list[dict[str, object]]:
    groups = [("overall", "all")]
    for key in ("algorithm", "dataset_kind", "role"):
        groups.extend(
            (key, value) for value in sorted({str(row[key]) for row in pairs})
        )
    return [summarize_pairs(pairs, key, value) for key, value in groups]


def analyze_completed_matrix(
    output_root: Path, analysis_dir: Path
) -> dict[str, object]:
    matrix_path = output_root / "comparison_manifest.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    if (
        matrix.get("status") != "PASS"
        or matrix.get("complete_matrix") is not True
        or matrix.get("failure") is not None
    ):
        raise ValueError("analysis requires a complete PASS comparison matrix")
    source_manifest_path = Path(str(matrix["source_manifest"]))
    if sha256_file(source_manifest_path) != matrix["source_manifest_sha256"]:
        raise ValueError("source workload manifest hash does not match matrix evidence")
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    expected_run_ids = {str(run["run_id"]) for run in source_manifest["runs"]}
    result_rows = _read_csv(output_root / "results.csv")
    original_pairs = _read_csv(output_root / "pairs.csv")
    expected_rows = 2 * len(expected_run_ids)
    if (
        len(result_rows) != expected_rows
        or len(original_pairs) != len(expected_run_ids)
    ):
        raise ValueError("matrix row counts do not cover the source workload manifest")
    identities = {(row["run_id"], row["system"]) for row in result_rows}
    if len(identities) != expected_rows:
        raise ValueError("duplicate system rows in comparison matrix")
    if {run_id for run_id, _ in identities} != expected_run_ids:
        raise ValueError("matrix run IDs do not match source workload manifest")

    enriched = [enrich_system_row(output_root, row) for row in result_rows]
    pairs = build_pair_details(enriched)
    original_speedups = {
        row["run_id"]: _float(row, "spine_speedup_over_grasu")
        for row in original_pairs
    }
    for row in pairs:
        if not math.isclose(
            _float(row, "spine_speedup_over_grasu"),
            original_speedups[str(row["run_id"])],
            rel_tol=1.0e-12,
        ):
            raise ValueError(f"pair speedup does not match parent: {row['run_id']}")
    summaries = group_summaries(pairs)
    bottlenecks: list[dict[str, object]] = []
    for system in ("spine", "grasu_regraph"):
        selected = [row for row in enriched if row["system"] == system]
        for label in ("structure_update_dominant", "balanced", "compute_dominant"):
            bottlenecks.append(
                {
                    "system": system,
                    "phase_bottleneck": label,
                    "runs": sum(row["phase_bottleneck"] == label for row in selected),
                    "total_runs": len(selected),
                }
            )

    analysis_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(analysis_dir / "system_details.csv", enriched)
    _write_csv(analysis_dir / "pair_details.csv", pairs)
    _write_csv(analysis_dir / "group_summary.csv", summaries)
    _write_csv(analysis_dir / "bottleneck_summary.csv", bottlenecks)
    output = {
        "schema_version": 1,
        "status": "PASS",
        "claim_class": "complete_normalized_structural_execution_driven_analysis",
        "matrix_manifest": str(matrix_path.resolve()),
        "matrix_manifest_sha256": sha256_file(matrix_path),
        "matrix_simulation_implementation": matrix["simulation_implementation"],
        "matrix_orchestration_implementation": matrix[
            "orchestration_implementation"
        ],
        "source_manifest": str(source_manifest_path.resolve()),
        "source_manifest_sha256": sha256_file(source_manifest_path),
        "analysis_module": str(Path(__file__).resolve()),
        "analysis_module_sha256": sha256_file(Path(__file__).resolve()),
        "runs": len(expected_run_ids),
        "system_rows": len(enriched),
        "pairs": len(pairs),
        "correctness": "all_rows_dual_oracle_zero_mismatch",
        "timing_claim": "normalized_conversion_free_structural_execution_driven",
        "energy_claim": "sparse_active_channel_dramsim3_only",
        "energy_not_claimed": "full_32_channel_idle_background_or_total_system_energy",
        "group_summary": summaries,
        "bottleneck_summary": bottlenecks,
        "outputs": {
            name: sha256_file(analysis_dir / name)
            for name in (
                "system_details.csv",
                "pair_details.csv",
                "group_summary.csv",
                "bottleneck_summary.csv",
            )
        },
    }
    (analysis_dir / "analysis_manifest.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return output
