"""Explain retained work and serial model floors; do not attribute FPGA stalls."""

import argparse
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from .analysis import matrix


def natural(value, label):
    if type(value) is not int or value < 0:
        raise ValueError("invalid nonnegative count: " + label)
    return value


def worker_floors(layout: dict, fixed: dict, empty_exit: int) -> list[dict]:
    """Disjoint adapter phases give a floor, not an additive stall breakdown."""
    expected = {"unique_pairs_no_reserved_updates": True, "segment_slots": 16,
                "prefetch_rows": 8, "stop_after_last": True, "row_control_cycles": 6,
                "empty_segment_exit_cycles": 73}
    if not same_typed(layout["assumptions"], expected) or type(empty_exit) is not int or empty_exit not in (0, 73):
        raise ValueError("unsupported retained layout contract")
    timing = {"adapter_min_read_to_use": 71, "adapter_row_control": 6,
              "adapter_empty_segment_exit_cycles": 73}
    if not same_typed({key: fixed[key] for key in timing}, timing):
        raise ValueError("unsupported serial-phase timing contract")
    rows = layout["partitions"]
    if [row["partition"] for row in rows] != list(range(4)):
        raise ValueError("expected four distinct shards, one per worker")
    result = []
    for row in rows:
        for key, value in row.items():
            natural(value, key)
        visited, empty = row["rows_visited"], row["empty_rows_visited"]
        occupied = row["nonempty_sources"] + row["forced_dummy_source_zero_segments"]
        requests = row["row_read_requests"]
        groups = (visited + 7) // 8
        if (visited <= 0 or empty + occupied != visited or not visited <= requests <= groups * 8
                or requests <= (groups - 1) * 8 or row["segments"] < occupied
                or row["physical_slots"] != row["segments"] * 16
                or row["physical_slots"] != row["dummy_slots"] + row["live_edges"]):
            raise ValueError("inconsistent occupied/empty row or segment work")
        # Source selection waits for a whole row group; segments of the next
        # occupied source cannot issue until the current source finishes.
        terms = {"extent_read_floor": 71, "row_group_read_floor": groups * 71,
                 "row_control_floor": visited * 6,
                 "occupied_row_first_read_floor": occupied * 71,
                 "empty_helper_floor": empty * empty_exit}
        result.append({"worker": row["partition"], "occupied_rows": occupied,
                       "row_groups": groups, **terms, "serial_model_floor": sum(terms.values())})
    return result


def traffic(a4: dict, k4: dict, geometry: dict, layout: dict) -> dict:
    vertices = natural(geometry["padded_vertices"], "padded_vertices")
    if not vertices or vertices % 16:
        raise ValueError("invalid padded state geometry")
    for counters in (a4, k4):
        for key, value in counters.items():
            if key not in {"path", "passed", "full_state_and_traffic_pass"}:
                natural(value, key)
    rows = layout["partitions"]
    if (k4["extent_reads"] != 4 or k4["row_reads"] != sum(r["row_read_requests"] for r in rows)
            or k4["segment_reads"] != sum(r["segments"] for r in rows)
            or k4["live_edges"] != sum(r["live_edges"] for r in rows)
            or k4["dummy_edges"] != sum(r["dummy_slots"] for r in rows)
            or k4["physical_packets"] * 8 != k4["live_edges"] + k4["dummy_edges"]):
        raise ValueError("layout and runtime work differ")
    a4_reads = {"edges": a4["edge_read_bytes"], "source_state": a4["source_read_bytes"],
                "old_state": vertices * 4}
    k4_reads = {"extent": k4["extent_reads"] * 64, "rows": k4["row_reads"] * 64,
                "segments": k4["segment_reads"] * 64, "source_state": k4["source_lines"] * 64,
                "old_state": vertices * 4}
    if (sum(a4_reads.values()) != a4["read_bytes"] or sum(k4_reads.values()) != k4["read_bytes"]
            or a4["replicas"] != 4 or k4["replicas"] != 3
            or a4["write_bytes"] != vertices * 4 * 4 or k4["write_bytes"] != vertices * 4 * 3 + 4
            or a4["physical_edges"] * 8 != a4_reads["edges"]
            or a4["physical_edges"] - a4["dummy_edges"] != k4["live_edges"]):
        raise ValueError("read/write or logical edge accounting differs")
    return {"a4_reads": a4_reads, "k4_reads": k4_reads,
            "a4_read_bytes": a4["read_bytes"], "k4_read_bytes": k4["read_bytes"],
            "k4_over_a4_read_bytes": k4["read_bytes"] / a4["read_bytes"],
            "k4_row_share_of_read_bytes": k4_reads["rows"] / k4["read_bytes"],
            "a4_physical_slots": a4["physical_edges"],
            "k4_physical_slots": k4["physical_packets"] * 8}


def derive(basis: dict, sensitivity: dict, profile: dict) -> dict:
    matrix(sensitivity["cases"])
    if (profile["profile_id"] != "grasu_regraph_routed_sssp_compute_v4"
            or sensitivity["model"] != basis["model"]):
        raise ValueError("retained model identity differs")
    geometry = basis["inputs"][0]
    fixed, layout = profile["fixed_model"], basis["layout_audit"]
    workers = {arm: worker_floors(layout, fixed, arm) for arm in (73, 0)}
    reference_traffic = None
    cases = []
    for case in sensitivity["cases"]:
        match, = [b for b in basis["cases"] if all(b[k] == case[k] for k in ("mode", "latency", "reverse"))]
        a4, legacy = match["paths"]
        observed = case["counters"]
        if {k: v for k, v in observed.items() if k != "cycles"} != {
                k: v for k, v in legacy.items() if k != "cycles"}:
            raise ValueError("retained sensitivity traffic differs from basis")
        measured_work = traffic(a4, observed, geometry, layout)
        if reference_traffic is not None and measured_work != reference_traffic:
            raise ValueError("traffic changed within retained matrix")
        reference_traffic = measured_work
        critical = max(workers[case["empty_exit"]], key=lambda w: w["serial_model_floor"])
        floor = critical["serial_model_floor"]
        if not 0 < floor <= observed["cycles"]:
            raise ValueError("observed model cycles violate serial floor")
        cases.append({k: case[k] for k in ("mode", "latency", "reverse", "empty_exit")} | {
            "a4_cycles": a4["cycles"], "k4_cycles": observed["cycles"],
            "k4_over_a4_cycles": observed["cycles"] / a4["cycles"],
            "floor_worker": critical["worker"], "serial_model_floor": floor,
            "floor_over_observed_cycles": floor / observed["cycles"]})
    return {"schema_version": 1, "status": "retained_work_accounted_not_FPGA_stall_attribution",
            "scope": "one_resident_synchronous_SSSP_round_uncalibrated_mock_memory",
            "traffic": reference_traffic, "worker_floors": {str(k): v for k, v in workers.items()},
            "cases": cases, "hardware_timing_admitted": False,
            "exclusive_stage_attribution_admitted": False, "strict_resource_match_admitted": False,
            "production_model_modified": False, "numerical_executor_rerun": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("fresh accounting output required")
    from .recheck import recheck
    root = Path(__file__).resolve().parents[5]
    report_path = args.run.resolve() / "results.json"
    report = recheck(root, args.run.resolve())
    basis_path = Path(report["basis"]["path"])
    basis = json.loads(basis_path.read_text())
    profile_path = root / basis["model"]["k4_profile_reference"]
    pins = [{"path": str(p), "sha256": sha256_file(p)}
            for p in (report_path, basis_path, profile_path, Path(__file__).resolve())]
    if pins[2]["sha256"] != basis["model"]["k4_profile_sha256"]:
        raise ValueError("profile differs from admitted basis")
    result = derive(basis, report, json.loads(profile_path.read_text()))
    if any(sha256_file(Path(pin["path"])) != pin["sha256"] for pin in pins):
        raise ValueError("accounting dependencies changed during derivation")
    result["sources"] = pins
    result["retained_evidence_rechecked"] = True
    atomic_write_json(args.output, result)
    print(json.dumps({"status": result["status"], "cases": len(result["cases"])}))


if __name__ == "__main__":
    main()
