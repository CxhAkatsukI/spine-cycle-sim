"""Audit frozen Fig. 7 winners against post-update lower bounds."""

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
K4_FRONTENDS = 4
EDGES_PER_BEAT = 8
ROWS_PER_DIRECTORY_BEAT = 8
PARTITION_VERTICES = 65536
K4_CLOCK_CEILING_MHZ = 150
EXECUTIONS_KEY = {
    "weighted_sssp": "executed_supersteps",
    "connected_components": "executed_supersteps",
    "residual_pagerank": "pipeline_executions",
}
FIELDS = ("algorithm", "dataset", "gr_wall_ms", "spine_wall_ms", "g_span_ms",
          "remaining_budget_to_tie_ms", "survives_zero_post_update_cost",
          "final_edges", "k4_one_scan_floor_ms", "g_plus_k4_one_scan_floor_ms",
          "survives_one_k4_full_scan", "destination_partitions",
          "compact_directory_one_scan_floor_ms", "g_plus_compact_one_scan_floor_ms",
          "survives_one_compact_full_scan",
          "receipt_sha256", "gr_log_sha256", "spine_log_sha256")


def fields(log, tag):
    lines = [line for line in log.splitlines() if line.startswith(tag + " ")]
    if len(lines) != 1:
        raise ValueError(f"expected one {tag} line, found {len(lines)}")
    return dict(field.split("=", 1) for field in lines[0].split()[1:])


def ceil_div(count, width):
    return (count + width - 1) // width


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
    graph_input = fields(gr_text, f"{tag}_PMA_NATIVE_SHARDED_INPUT")
    result = fields(gr_text, f"{tag}_PMA_NATIVE_SHARDED_RESULT")
    repeat = fields(gr_text, "GRASU_SHARDED_UPDATE_REPEAT_CONFIG")
    spine = fields(spine_log.read_text(), "SPINE_RESIDENT_BENCHMARK_PASS")
    g_span = Decimal(gr[g_key])
    final_edges = int(result["final_edges"])
    vertices = int(result["vertices"])
    partitions = int(result["destination_partitions"])
    executions = int(result[EXECUTIONS_KEY[algorithm]])
    if (result["status"] != "PASS" or result["resident_state"] != "old_graph_converged"
            or result["hardware_converged"] != "1" or result["oracle_converged"] != "1"
            or int(result["k4_frontends"]) != K4_FRONTENDS or executions < 1
            or final_edges <= 0 or final_edges != int(graph_input["final_edges"])
            or vertices <= 0 or vertices != int(graph_input["vertices"])
            or not 1 <= partitions <= 255 or partitions != ceil_div(vertices, PARTITION_VERTICES)
            or partitions != int(graph_input["destination_partitions"])
            or repeat["repeats"] != "1" or spine["boundary"] != BOUNDARY
            or spine["case"] != config["graph"] + ":final"
            or any(int(result[key]) != summary[key] or int(spine[key]) != summary[key]
                   for key in ("vertices", "logical_updates", "physical_updates"))
            or Decimal(gr["setup_inclusive_ms"]) != gr_wall
            or Decimal(spine["wall_ms"]) != spine_wall
            or not 0 < g_span <= gr_wall or not 0 < spine_wall < gr_wall):
        raise ValueError(f"frozen raw timing does not match {algorithm}/{dataset}")

    # Keep only one post-G scan of live edges. No padding or additional rounds.
    edges_per_cycle = K4_FRONTENDS * EDGES_PER_BEAT
    cycles_per_ms = K4_CLOCK_CEILING_MHZ * 1000
    scan_floor = Decimal(ceil_div(final_edges, edges_per_cycle)) / cycles_per_ms
    total_floor = g_span + scan_floor
    if total_floor > gr_wall:
        raise ValueError(f"frozen wall time is below the K4 scan floor for {algorithm}/{dataset}")

    # The span reader probes the extent, then rereads the entire directory.
    # At least one frontend must serve ceil(partitions / 4) shards serially.
    directory_beats = 1 + ceil_div(vertices, ROWS_PER_DIRECTORY_BEAT)
    directory_cycles = ceil_div(partitions, K4_FRONTENDS) * directory_beats
    directory_floor = Decimal(directory_cycles) / cycles_per_ms
    compact_floor = g_span + max(scan_floor, directory_floor)
    return dict(algorithm=algorithm, dataset=dataset, gr_wall_ms=gr_wall, spine_wall_ms=spine_wall,
                g_span_ms=g_span, remaining_budget_to_tie_ms=spine_wall - g_span,
                survives_zero_post_update_cost=g_span > spine_wall,
                final_edges=final_edges, k4_one_scan_floor_ms=scan_floor,
                g_plus_k4_one_scan_floor_ms=total_floor,
                survives_one_k4_full_scan=total_floor > spine_wall,
                destination_partitions=partitions, compact_directory_one_scan_floor_ms=directory_floor,
                g_plus_compact_one_scan_floor_ms=compact_floor,
                survives_one_compact_full_scan=compact_floor > spine_wall,
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
