"""Estimate one effective request-path delay using development rows only."""

import argparse
import json
from pathlib import Path

from ...original_regraph_execution.hardware.source_retention.runtime import identity, save


def freeze(board_path, simulation_path, base_profile, output, reader_only=False):
    board = json.loads(board_path.read_text())
    simulation = json.loads(simulation_path.read_text())
    if board["status"] != "COMPLETE" or simulation["status"] != "COMPLETE":
        raise ValueError("calibration requires complete development campaigns")
    estimates = []
    for row in board["rows"]:
        if row["split"] != "development" or row["status"] != "MEASURED":
            raise ValueError("calibration accepts measured development cases only")
        sim = next(candidate for candidate in simulation["rows"] if candidate["name"] == row["name"])
        if sim["split"] != "development" or sim["status"] != "PASS":
            raise ValueError("calibration accepts passing development simulations only")
        result = json.loads(Path(sim["result_path"]).read_text())
        lines = Path(row["stdout"]["path"]).read_text().splitlines()
        first = next(line for line in lines if line.startswith("SPINE_HW_ROUND_TIMING round=1 "))
        timing = dict(field.split("=", 1) for field in first.split()[1:])
        measured = float(timing["reader_ms"]) * row["clock"]["driver_reported_mhz"][0] * 1000
        predicted = result["reader_active_cycles_per_round"][0]
        requests = result["reader_memory_requests_issued_per_round"][0]
        estimates.append(dict(case=row["name"], measured_reader_cycles=measured,
                              predicted_reader_cycles=predicted, reader_requests=requests,
                              effective_added_cycles=(measured - predicted) / requests))
    delay = max(0, 10 * round(sum(row["effective_added_cycles"] for row in estimates) / len(estimates) / 10))
    profile = json.loads(base_profile.read_text())
    profile["profile_id"] = "spine_sssp_transport_development_20261107"
    profile["status"] = "experimental"
    profile["evidence_tier"] = "development_calibrated_pending_holdout"
    key = "axi_reader_transport_read_cycles" if reader_only else "axi_transport_read_cycles"
    profile["parameters"][key] = delay
    profile["limitations"].append(
        "Effective AXI request-path delay is estimated from first-round reader event spans, not an isolated HBM latency counter. Validate on unseen cases; do not generalize to other algorithms or traffic regimes.")
    output.mkdir(parents=True, exist_ok=False)
    save(output / "profile.json", profile)
    save(output / "freeze.json", dict(
        method="mean first-round (FPGA reader cycles - baseline reader cycles) / reader requests; rounded to nearest 10 cycles",
        calibration_scope="development only; identical 380-request first-round work",
        transport_read_cycles=delay, estimates=estimates,
        scope="reader/maintenance ports only" if reader_only else "all AXI ports (development diagnostic)",
        board=identity(board_path), simulation=identity(simulation_path),
        base_profile=identity(base_profile), frozen_profile=identity(output / "profile.json")))
    print("Frozen request-path delay:", delay, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("board", "simulation", "base_profile", "output"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    parser.add_argument("--reader-only", action="store_true")
    args = parser.parse_args()
    freeze(args.board, args.simulation, args.base_profile, args.output, args.reader_only)
