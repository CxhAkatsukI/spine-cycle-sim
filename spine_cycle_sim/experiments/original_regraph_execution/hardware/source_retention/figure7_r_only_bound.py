"""Audit which frozen Fig. 7 winners survive a zero-cost post-update path."""

import argparse
import csv
from decimal import Decimal
import json
from pathlib import Path
import sys

from . import active_min_resident
from .runtime import identity


BOUNDARY = "resident_update_to_final_readback_wall_including_host_relaunch"
LOG_TAGS = {
    "weighted_sssp": ("sssp", "WEIGHTED", "grasu_ms"),
    "connected_components": ("cc", "CC", "grasu_ms"),
    "residual_pagerank": ("respr", "RESIDUAL_PR", "update_ms"),
}
HOST_SOURCES = {
    "sharded_k4_native_host.cpp": "18993bfb7af2f3bc02a2861b9d26c4f7c3de4a7337b6fe42167578bd8352f7ee",
    "sharded_k4_pagerank_native_host.cpp": "5f37a2fea3b0fdb71220df8b4764cbf442aacc3ed6464a595cc5c6f30750fe05",
}
FIELDS = ("algorithm", "dataset", "gr_wall_ms", "spine_wall_ms", "g_span_ms",
          "remaining_budget_to_tie_ms", "survives_zero_post_update_cost",
          "receipt_sha256", "gr_log_sha256", "spine_log_sha256")


def fields(log, tag):
    lines = [line for line in log.splitlines() if line.startswith(tag + " ")]
    if len(lines) != 1:
        raise ValueError(f"expected one {tag} line, found {len(lines)}")
    return dict(field.split("=", 1) for field in lines[0].split()[1:])


def audit_row(row, run):
    algorithm, dataset = row["algorithm"], row["dataset"]
    slug, tag, g_key = LOG_TAGS[algorithm]
    receipt_path = run / f"{slug}-{dataset.lower()}" / "results.json"
    receipt = json.loads(receipt_path.read_text(), parse_float=Decimal)
    summary = receipt["summary"]
    config = receipt["config"]
    host_pins = {Path(pin["path"]).name: pin["sha256"] for pin in config["expected_pins"]
                 if Path(pin["path"]).name in HOST_SOURCES}
    gr_wall, spine_wall = (Decimal(row[key]) for key in ("gr_wall_ms", "spine_wall_ms"))
    samples = receipt["samples"]
    if (row["status"] != "RESIDENT_PAIR_PASS" or receipt["status"] != row["status"]
            or config["dataset"] != dataset or summary["algorithm"] != algorithm or host_pins != HOST_SOURCES
            or receipt["boundary"] != BOUNDARY or summary["boundary"] != BOUNDARY
            or receipt["board_tested"] is not True or len(samples) != 1
            or samples[0]["warmup"] is not False or summary["measured_pairs"] != 1
            or summary["excluded_warmup_pairs"] != 0
            or summary["gr_wall_ms"] != gr_wall or summary["spine_wall_ms"] != spine_wall):
        raise ValueError(f"frozen pair receipt does not match {algorithm}/{dataset}")

    gr_log = receipt_path.parent / "sample-1" / "gr.stdout.txt"
    spine_log = receipt_path.parent / "sample-1" / "spine.stdout.txt"
    gr_text = gr_log.read_text()
    gr = fields(gr_text, f"{tag}_PMA_NATIVE_SHARDED_TIMING")
    result = fields(gr_text, f"{tag}_PMA_NATIVE_SHARDED_RESULT")
    repeat = fields(gr_text, "GRASU_SHARDED_UPDATE_REPEAT_CONFIG")
    spine = fields(spine_log.read_text(), "SPINE_RESIDENT_BENCHMARK_PASS")
    g_span = Decimal(gr[g_key])
    if (result["status"] != "PASS" or result["resident_state"] != "old_graph_converged"
            or result["hardware_converged"] != "1" or result["oracle_converged"] != "1"
            or repeat["repeats"] != "1" or spine["boundary"] != BOUNDARY
            or spine["case"] != config["graph"] + ":final"
            or any(int(result[key]) != summary[key] or int(spine[key]) != summary[key]
                   for key in ("vertices", "logical_updates", "physical_updates"))
            or Decimal(gr["setup_inclusive_ms"]) != gr_wall
            or Decimal(spine["wall_ms"]) != spine_wall
            or not 0 < g_span <= gr_wall or not 0 < spine_wall < gr_wall):
        raise ValueError(f"frozen raw timing does not match {algorithm}/{dataset}")

    # Count only the G event span, which ends before the first R launch.
    return dict(algorithm=algorithm, dataset=dataset, gr_wall_ms=gr_wall, spine_wall_ms=spine_wall,
                g_span_ms=g_span, remaining_budget_to_tie_ms=spine_wall - g_span,
                survives_zero_post_update_cost=g_span > spine_wall,
                receipt_sha256=identity(receipt_path)["sha256"], gr_log_sha256=identity(gr_log)["sha256"],
                spine_log_sha256=identity(spine_log)["sha256"])


def audit_matrix(frozen_csv, run):
    with frozen_csv.open(newline="") as source:
        rows = list(csv.DictReader(source))
    expected = {(algorithm, dataset) for algorithm in LOG_TAGS for dataset in active_min_resident.DATASETS}
    if len(rows) != len(expected) or {(row["algorithm"], row["dataset"]) for row in rows} != expected:
        raise ValueError("frozen handoff is not the full three-algorithm, eight-graph matrix")
    return [audit_row(row, run) for row in rows]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen_csv", type=Path)
    parser.add_argument("matrix_run", type=Path)
    args = parser.parse_args()
    rows = audit_matrix(args.frozen_csv, args.matrix_run)
    writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)


if __name__ == "__main__":
    main()
