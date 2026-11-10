"""Export RN measurements and workload identities without treating a missing arm as zero."""

import argparse
import csv
import json
from pathlib import Path


HEADLINE = {
    "weighted_sssp": "board-weighted_sssp-cap1024",
    "connected_components": "board-cc-preloaded",
    "residual_pagerank": "board-respr-memavailable",
}
FPGA_COLUMNS = (
    "status", "boundary", "spine_ms", "gr_ms", "speedup_gr_over_spine",
    "spine_rounds", "gr_rounds", "spine_processed_edges", "spine_source_requests",
    "fpga_clock_mhz", "evidence",
)
WORKLOAD_COLUMNS = (
    "algorithm", "kind", "name", "logical_insertions", "updates", "updated_sources",
    "actual_vertices", "changed_vertices", "changed_fraction", "target_vertices",
    "cpu_warm_frontier_rounds", "graph_sha256",
)
CPU_COLUMNS = (
    "status", "residual_contract", "threads", "total_ms", "normalize_ms",
    "csr_rebuild_ms", "correction_ms", "propagation_ms", "rounds",
    "propagated_edge_visits", "source_services", "changed_vertices",
)


def read(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def write_csv(path, columns, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, columns, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def fpga(path, name, point):
    campaign = read(path)
    row = next((item for item in campaign.get("cases", []) if item["name"] == name), {})
    if row.get("graph") and row["graph"]["sha256"] != point["graph"]["sha256"]:
        raise ValueError(f"input hash differs for {path}:{name}")
    status = row.get("status")
    if status is None:
        status = "FAILED_RETAINED" if campaign.get("status") == "FAILED_RETAINED" else "NOT_RUN"
    result = dict(status=status, evidence=path.parent.name + "/campaign.json")
    if status != "MEASURED":
        return result
    sample, = [s for s in row["samples"] if not s["warmup"]]
    if sample["status"] != "PASS" or row["batch"] != point["batch"]:
        raise ValueError(f"unvalidated sample or changed batch for {path}:{name}")
    pair = sample["pair"]
    counters = sample.get("counters", {}).get("spine", {})
    return dict(result, boundary=pair["boundary"], spine_ms=pair["spine_wall_ms"],
                gr_ms=pair["gr_wall_ms"],
                speedup_gr_over_spine=pair["gr_wall_ms"] / pair["spine_wall_ms"],
                spine_rounds=pair.get("spine_rounds"), gr_rounds=pair.get("gr_rounds"),
                spine_processed_edges=counters.get("processed_edges"),
                spine_source_requests=counters.get("source_requests"),
                fpga_clock_mhz=sample["arms"]["spine"]["clock"]["driver_reported_mhz"][0])


def collect(scratch, output):
    output.mkdir(parents=True, exist_ok=True)
    board_rows, cpu_rows = [], []
    for series in (*HEADLINE, "sssp-control"):
        manifest = read(scratch / "rn-sweep" / series / "workloads.json")
        algorithm = manifest["algorithm"]
        for point in manifest["points"]:
            name = point["name"]
            headline = name == "ordinary-8"
            campaign = HEADLINE[algorithm] if headline else f"board-sweep-{series}"
            board_rows.append(dict(
                point, algorithm=algorithm, actual_vertices=manifest["actual_vertices"],
                graph_sha256=point["graph"]["sha256"],
                cpu_warm_frontier_rounds=point["cpu"].get("warm_frontier_rounds"),
                **fpga(scratch / campaign / "campaign.json",
                       "insert-u8" if headline else name, point)))
            if point["kind"] != "ordinary":
                continue
            cpu = read(scratch / "ligra" / f"{algorithm}-{name}.json")
            trial = cpu["repetitions"][0] if cpu.get("repetitions") else {}
            if trial.get("passed") and trial["changed_vertices"] != point["changed_vertices"]:
                raise ValueError(f"Ligra and the independent impact oracle disagree for {algorithm}:{name}")
            cpu_rows.append(dict(trial, algorithm=algorithm, name=name,
                                 logical_insertions=point["logical_insertions"],
                                 graph_sha256=point["graph"]["sha256"],
                                 status=cpu.get("status", "NOT_RUN"), threads=cpu.get("threads"),
                                 residual_contract=cpu.get("residual_contract")))
    write_csv(output / "rn_fpga_sweep.csv", WORKLOAD_COLUMNS + FPGA_COLUMNS, board_rows)
    write_csv(output / "rn_ligra_trifoliate.csv",
              ("algorithm", "name", "logical_insertions", "graph_sha256") + CPU_COLUMNS, cpu_rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scratch", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    collect(args.scratch, args.output)
