"""Package bounded board diagnostics without admitting a publication match."""

import argparse
import json
from pathlib import Path
import statistics

from .grasu import fields
from .regraph import identity, save


COMPLETE = "CORRECTNESS_PASS_DIAGNOSTIC_NOT_PUBLICATION_MATCH"


def update_timeline(lines, expected_ms):
    shards = [fields(line) for line in lines
              if line.startswith("GRASU_SHARDED_UPDATE_EVENTS ")]
    phases = [fields(line) for line in lines
              if line.startswith("GRASU_SHARDED_UPDATE_EVENTS_PHASE ")]
    if not shards or len(phases) != 9 * len(shards):
        raise ValueError("complete nine-CU timestamps are required for every shard")
    if len({row["shard"] for row in shards}) != len(shards):
        raise ValueError("duplicate shard observations")
    span = sum(float(row["union_ms"]) for row in shards)
    gaps = sum(float(row["gap_from_previous_ms"]) for row in shards)
    if abs(span + gaps - expected_ms) > 0.0001:
        raise ValueError("shard spans and gaps do not conserve the measured envelope")
    spreads = []
    for shard in shards:
        selected = [row for row in phases if row["shard"] == shard["shard"]]
        if len(selected) != 9 or len({row["cu"] for row in selected}) != 9:
            raise ValueError("nine distinct CU observations required per shard")
        starts = [float(row["start_offset_ms"]) for row in selected]
        spreads.append(max(starts) - min(starts))
    return {"shard_count": len(shards), "shard_span_sum_ms": span,
            "inter_shard_gap_sum_ms": gaps,
            "median_within_shard_cu_start_spread_ms": statistics.median(spreads),
            "shards": shards,
            "interpretation": "Observed start staggering, not an attribution of all waiting to host or device."}


def compare_rates(measured, reference):
    if measured <= 0 or reference <= 0:
        raise ValueError("positive rates required")
    return {"reference_over_measured_rate": reference / measured,
            "measured_fraction_of_reference": measured / reference,
            "publication_match": False,
            "interpretation": "Unmatched configuration diagnostic, not a controlled reproduction error."}


def package(grasu_path, regraph_path, output):
    g, r = json.loads(grasu_path.read_text()), json.loads(regraph_path.read_text())
    if any(report["status"] != COMPLETE or report["publication_match"]
           for report in (g, r)):
        raise ValueError("only complete, explicitly non-publication diagnostics may be packaged")
    if len(g["rows"]) != 3 or any(row["result"]["status"] != "PASS" for row in g["rows"]):
        raise ValueError("all three G repetitions must pass")
    matrix = {(topology, binding, repeat) for topology in ("a4", "original_example")
              for binding in ("author_initial", "csr_degree") for repeat in range(3)}
    observed = {(row["topology"], row["binding"], row["repeat"]) for row in r["rows"]}
    if observed != matrix or len(r["rows"]) != len(matrix):
        raise ValueError("the complete twelve-run R matrix is required")
    raw = [grasu_path, regraph_path]
    raw.extend(grasu_path.parent.glob("r*.stdout.txt"))
    raw.extend(grasu_path.parent.glob("r*.stderr.txt"))
    raw.extend(grasu_path.parent.glob("r*.result.txt"))
    raw.extend(regraph_path.parent.glob("*.stdout.txt"))
    raw.extend(regraph_path.parent.glob("*.stderr.txt"))
    timelines = [update_timeline(
        (grasu_path.parent / f"r{row['repeat']}.stdout.txt").read_text().splitlines(),
        row["update_ms"]) for row in g["rows"]]
    g_rate = g["summary"]["median_mupdates_per_second"]
    result = {"schema_version": 1, "publication_match": False,
              "status": COMPLETE, "raw_index": [identity(path) for path in sorted(set(raw))],
              "papers": [identity(Path("/data/feiyang/delta-hls-paper/related_papers") / name)
                         for name in ("2021_FPGA_GraSU.pdf", "2022_MICRO_ReGraph.pdf")],
              "grasu": {"summary": g["summary"], "workload": g["workload"],
                        "host": g["host"], "xclbin": g["xclbin"], "boundary": g["boundary"],
                        "repetitions": g["rows"], "timelines": timelines,
                        "paper_au_reference_mupdates_per_second": 190.77,
                        "diagnostic_ratio": compare_rates(g_rate, 190.77)},
              "regraph": {"summaries": r["summaries"], "boundary": r["boundary"],
                          "manifests": r["manifests"],
                          "paper_am_selected_reference_gteps_approximate": 4.0,
                          "note": "The 4 GTEPS chart reference is a selected 14-pipeline configuration, not an exact 11L3B reference.",
                          "diagnostic_ratios": [dict(topology=row["topology"], binding=row["binding"],
                              **compare_rates(row["event_gteps"], 4.0)) for row in r["summaries"]]},
              "latest_k4_adapter_r_publication_gap": None,
              "limitation": "Original-R port diagnostics do not measure the latest K4 adapter+R; G uses a different AU trace and launch boundary."}
    save(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grasu", required=True, type=Path)
    parser.add_argument("--regraph", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(package(args.grasu, args.regraph, args.output)["status"])
