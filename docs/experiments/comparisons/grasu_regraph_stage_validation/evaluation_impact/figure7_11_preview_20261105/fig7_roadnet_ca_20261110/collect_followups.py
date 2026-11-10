"""Export RN measurements and workload identities without treating a missing arm as zero."""

import argparse
import csv
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.evaluation_impact.affected_fraction.work import records


HEADLINE = {
    "weighted_sssp": "board-weighted_sssp-cap1024",
    "connected_components": "board-cc-preloaded",
    "residual_pagerank": "board-respr-memavailable",
}
FPGA_COLUMNS = (
    "status", "boundary", "spine_ms", "gr_ms", "speedup_gr_over_spine",
    "spine_rounds", "gr_rounds", "spine_processed_edges", "spine_source_requests",
    "spine_cc_relax_edges", "spine_cc_row_queries", "gr_slots_per_execution",
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
TIMING_COLUMNS = ("algorithm", "name", "arm", "record", "record_index", "field", "ms")
FIG7_COLUMNS = (
    "dataset", "algorithm", "status", "boundary", "spine_wall_ms", "gr_wall_ms",
    "speedup_gr_over_spine", "spine_rounds", "gr_rounds", "source_csv",
)
RAW_NAMES = {"campaign.json", "sample.json", "inputs.json"}
RAW_SUFFIXES = (".stdout.txt", ".stderr.txt", ".clock.json", ".clock-raw.json", ".xclbin-info.txt")


def read(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def write_csv(path, columns, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, columns, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def work_fields(log_dir, arm, record_names):
    path = log_dir / (arm + ".stdout.txt")
    return [item for item in records(path.read_text()) if item["record"] in record_names]


def fpga(path, name, point, algorithm, timing_rows):
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
    log_dir = path.parent / name / f"sample-{sample['sample_index']}"
    gr_results = work_fields(log_dir, "gr", {
        "WEIGHTED_PMA_NATIVE_SHARDED_RESULT", "CC_PMA_NATIVE_SHARDED_RESULT",
        "RESIDUAL_PR_PMA_NATIVE_SHARDED_RESULT",
    })
    gr = gr_results[-1]["fields"] if gr_results else {}
    cc_results = work_fields(log_dir, "spine", {"CC_UPDATE_PASS", "CC_RESIDENT_WALL"}) if (
        algorithm == "connected_components") else []
    cc = next((item["fields"] for item in cc_results if item["record"] == "CC_UPDATE_PASS"), {})
    for arm in ("spine", "gr"):
        timing = sample.get("counters", {}).get(arm, {}).get("timing_records", {})
        entries = [(record, index, entry) for record, group in timing.items()
                   for index, entry in enumerate(group)]
        if arm == "spine":
            entries.extend((item["record"], 0, item["fields"]) for item in cc_results
                           if item["record"] not in timing)
        for record, index, entry in entries:
            timing_rows.extend(
                dict(algorithm=algorithm, name=point["name"], arm=arm,
                     record=record, record_index=index, field=field, ms=value)
                for field, value in entry.items() if field.endswith("_ms")
            )
    return dict(result, boundary=pair["boundary"], spine_ms=pair["spine_wall_ms"],
                gr_ms=pair["gr_wall_ms"],
                speedup_gr_over_spine=pair["gr_wall_ms"] / pair["spine_wall_ms"],
                spine_rounds=pair.get("spine_rounds"), gr_rounds=pair.get("gr_rounds"),
                spine_processed_edges=counters.get("processed_edges"),
                spine_source_requests=counters.get("source_requests"),
                spine_cc_relax_edges=cc.get("relax_edges"),
                spine_cc_row_queries=cc.get("row_queries"),
                gr_slots_per_execution=gr.get("processed_edge_slots_per_execution",
                                              gr.get("processed_edge_slots_per_superstep")),
                fpga_clock_mhz=sample["arms"]["spine"]["clock"]["driver_reported_mhz"][0])


def impact_summary(board_rows):
    points = [
        dict({key: row.get(key) for key in WORKLOAD_COLUMNS + FPGA_COLUMNS},
             dataset="RN", speedup=row.get("speedup_gr_over_spine"))
        for row in board_rows
    ]
    controlled = sorted(
        (row for row in points if row["kind"] != "ordinary" and row["status"] == "MEASURED"),
        key=lambda row: row["changed_fraction"],
    )
    crossings = []
    for left, right in zip(controlled, controlled[1:]):
        if ((left["speedup"] < 1 < right["speedup"])
                or (right["speedup"] < 1 < left["speedup"])):
            crossings.append([
                {key: row[key] for key in ("name", "changed_fraction", "speedup")}
                for row in (left, right)
            ])
    return {
        "points": points,
        "controlled_sssp_measured_brackets": crossings,
        "controlled_sssp_measured_1x": [row["name"] for row in controlled if row["speedup"] == 1],
    }


def collect_fig7(previous, board_rows):
    with previous.open(newline="") as stream:
        old = list(csv.DictReader(stream))
    current = [
        dict(row, dataset="RN", source_csv="rn_fpga_sweep.csv",
             spine_wall_ms=row["spine_ms"], gr_wall_ms=row["gr_ms"])
        for row in board_rows if row["name"] == "ordinary-8" and row["status"] == "MEASURED"
    ]
    keys = {(row["dataset"], row["algorithm"]) for row in old + current}
    if len(old) != 24 or len(current) != 3 or len(keys) != 27:
        raise ValueError("expected 24 frozen and 3 independently validated RN Fig. 7 rows")
    return [
        dict(row, algorithm="connected_components" if row["algorithm"] == "cc" else row["algorithm"],
             source_csv="../../" + row["source_csv"])
        for row in old
    ] + current


def collect(scratch, output):
    output.mkdir(parents=True, exist_ok=True)
    board_rows, cpu_rows, timing_rows = [], [], []
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
                       "insert-u8" if headline else name, point, algorithm, timing_rows)))
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
    write_csv(output / "rn_fpga_timing_records.csv", TIMING_COLUMNS, timing_rows)
    write_csv(output / "rn_ligra_trifoliate.csv",
              ("algorithm", "name", "logical_insertions", "graph_sha256") + CPU_COLUMNS, cpu_rows)
    (output / "rn_impact_summary.json").write_text(json.dumps(impact_summary(board_rows), indent=2) + "\n")
    old_fig7 = Path(__file__).resolve().parents[1] / "fig7_complete.csv"
    write_csv(output / "fig7_nine_datasets.csv", FIG7_COLUMNS, collect_fig7(old_fig7, board_rows))


def archive_logs(scratch, output):
    series = [scratch / f"board-sweep-{name}" for name in (*HEADLINE, "sssp-control")]
    for path in series:
        status = read(path / "campaign.json").get("status")
        if status not in {"COMPLETED", "COMPLETED_WITH_FAILURES", "FAILED_RETAINED"}:
            raise ValueError(f"cannot archive a missing or live campaign: {path} ({status})")
    with tarfile.open(output / "fpga_raw.tar.gz", "w:gz") as archive:
        for path in sorted(file for folder in series for file in folder.rglob("*") if file.is_file()):
            if path.name in RAW_NAMES or path.name.endswith(RAW_SUFFIXES):
                archive.add(path, arcname=path.relative_to(scratch))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scratch", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--archive-logs", action="store_true")
    args = parser.parse_args()
    collect(args.scratch, args.output)
    if args.archive_logs:
        archive_logs(args.scratch, args.output)
