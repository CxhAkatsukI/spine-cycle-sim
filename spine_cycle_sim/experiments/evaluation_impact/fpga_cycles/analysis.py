"""Pair complete device-event windows, preserving development/holdout roles."""

import argparse
import csv
import json
from pathlib import Path

from ...original_regraph_execution.hardware.source_retention.runtime import save


def resolve(path, relocate=None):
    path = Path(path)
    if relocate:
        original, archived = map(Path, relocate)
        try:
            return archived / path.relative_to(original)
        except ValueError:
            pass
    return path


def simulation_window(result):
    """Exclude inter-round acknowledgements, just as the host event sum does."""
    rounds = zip(result["reader_start_cycles_per_round"],
                 result["compute_start_cycles_per_round"],
                 result["reader_end_cycles_per_round"],
                 result["compute_end_cycles_per_round"], strict=True)
    propagation = sum(max(re, ce) - min(rs, cs) for rs, cs, re, ce in rounds)
    return result["maintenance_end_cycle"] - result["maintenance_start_cycle"] + propagation


def validate_work(hardware, result, relocate=None):
    log = resolve(hardware["stdout"]["path"], relocate).read_text()
    rounds = [dict(field.split("=", 1) for field in line.split()[1:] if "=" in field)
              for line in log.splitlines() if line.startswith("KERNEL_PAIR_RESULT ")]
    if len(rounds) != result["rounds"] or not result["converged"]:
        raise ValueError("round count or convergence mismatch")
    for field, key in (("processed_edges", "processed_edges_per_round"),
                       ("source_requests", "reader_source_requests_per_round"),
                       ("task_count", "reader_range_tasks_per_round")):
        if [int(row[field]) for row in rounds] != result[key]:
            raise ValueError(f"FPGA/simulator work mismatch: {field}")
    if int(hardware["timing"]["iterations"]) != len(rounds):
        raise ValueError("propagation round mismatch")


def pair(board_paths, simulation_paths, relocate=None):
    hardware = {}
    for path in board_paths:
        report = json.loads(path.read_text())
        if report["status"] != "COMPLETE":
            raise ValueError(f"incomplete FPGA campaign: {path}")
        for row in report["rows"]:
            if row["name"] in hardware or row["status"] != "MEASURED":
                raise ValueError("duplicate or unmeasured FPGA case")
            hardware[row["name"]] = row
            row["board_report"] = str(path)
    rows = []
    for path in simulation_paths:
        report = json.loads(path.read_text())
        if report["status"] != "COMPLETE":
            raise ValueError(f"incomplete simulator campaign: {path}")
        for row in report["rows"]:
            hw = hardware.pop(row["name"])
            if hw["split"] != row["split"] or row["status"] != "PASS":
                raise ValueError("case role or correctness mismatch")
            result = json.loads(resolve(row["result_path"], relocate).read_text())
            validate_work(hw, result, relocate)
            clock = hw["clock"]["driver_reported_mhz"][0]
            measured = float(hw["timing"]["dynamic_kernel_ms"]) * clock * 1000
            predicted = simulation_window(result)
            error = (predicted - measured) / measured
            rows.append(dict(case=row["name"], split=row["split"],
                             vertices=row["vertices"], edges=row["initial_edges"],
                             rounds=result["rounds"], fpga_mhz=clock,
                             fpga_cycles=measured, simulator_cycles=predicted,
                             processed_edges=sum(result["processed_edges_per_round"]),
                             served_sources=sum(result["reader_source_requests_per_round"]),
                             work_match=True,
                             signed_error_percent=100 * error,
                             abs_error_percent=100 * abs(error), within_20=abs(error) <= .2,
                             board_report=hw["board_report"], simulator_result=row["result_path"]))
    if hardware:
        raise ValueError(f"unpaired FPGA cases: {sorted(hardware)}")
    return rows


def write(rows, output):
    output.mkdir(parents=True, exist_ok=True)
    with (output / "cycles.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    holdout = [row for row in rows if row["split"] == "holdout"]
    save(output / "summary.json", dict(
        status="PASS" if holdout and all(row["within_20"] for row in holdout) else "FAILED_RETAINED",
        boundary="maintenance kernel event plus per-round reader/compute event spans; excludes DMA and host gaps",
        holdout_cases=len(holdout),
        holdout_max_abs_error_percent=max((row["abs_error_percent"] for row in holdout), default=None),
        all_rows=rows))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, nargs="+", required=True)
    parser.add_argument("--simulation", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--relocate-root", nargs=2, metavar=("ORIGINAL", "ARCHIVED"),
                        help="resolve archived raw paths without rewriting frozen receipts")
    args = parser.parse_args()
    write(pair(args.board, args.simulation, args.relocate_root), args.output)
