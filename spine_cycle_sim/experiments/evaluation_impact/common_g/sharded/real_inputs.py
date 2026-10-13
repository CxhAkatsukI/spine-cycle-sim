"""Validate pinned compact real-topology inputs and count exact search work."""

from bisect import bisect_right
import json

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.shared_workloads import load_slice
from ..study import ROOT
from .preparation import ARMS, LATENCIES, input_contract

STATUS = "REAL_TOPOLOGY_G_PREDICTIONS_CHECKED_NOT_BASELINE_ADMISSION"
SELECTION = (("AU", "sx_askubuntu"), ("SU", "sx_superuser"), ("WK", "wiki_talk_temporal"))
SCENARIOS = (("mixed", 512), ("weight_change", 4096))
SOURCE = "configs/experiments/candidate10_grasu_temporal_compact_batches_v1_20260727.json"


def facts(graph, batch):
    if graph.vertices != batch.vertices or graph.vertices >= 65535:
        raise ValueError("real input must fit the declared single shard")
    live = {(r.src, r.dst, r.weight) for r in graph.records}
    if len(live) != len(graph.records) or any(r.diff != 1 for r in graph.records):
        raise ValueError("initial real graph must be a distinct positive edge set")
    reserved = {}
    for r in (*graph.records, *batch.records):
        if not (0 <= r.src < graph.vertices and 0 <= r.dst < graph.vertices and 1 <= r.weight <= 4095):
            raise ValueError("real edge does not fit weighted source/destination ABI")
        if r.diff == 1:
            reserved.setdefault(r.src, set()).add(r.weight << 19 | r.dst)
    heads = {source: sorted(words)[::16] for source, words in reserved.items()}
    probes = multi = 0
    for r in batch.records:
        key = r.src, r.dst, r.weight
        if r.diff == -1 and key in live:
            live.remove(key)
        elif r.diff == 1 and key not in live:
            live.add(key)
        else:
            raise ValueError("real operation is not a distinct successful mutation")
        row = heads[r.src]
        begin, end = 0, len(row)
        multi += end > 1
        word = r.weight << 19 | r.dst
        while begin != (begin + end) // 2:
            probes += 1
            mid = (begin + end) // 2
            if row[mid] <= word:
                begin = mid
            else:
                end = mid
        if begin != bisect_right(row, word) - 1:
            raise ValueError("real reservation and search oracle differ")
    if not probes or not multi:
        raise ValueError("real input lacks multi-segment search coverage")
    return {"vertices": graph.vertices + 1, "live_edges": len(graph.records),
            "final_edges": len(live), "physical_updates": len(batch.records),
            "binary_probes": probes, "multi_segment_updates": multi,
            "reserved_live_segments": sum(len(row) for row in heads.values())}


def contract():
    source = ROOT / SOURCE
    manifest = json.loads(source.read_text())
    inputs = {SOURCE: source}
    cases = {}
    for abbreviation, dataset in SELECTION:
        for scenario, size in SCENARIOS:
            rows = [r for r in manifest["runs"] if (r["dataset_id"], r["scenario"], r["batch_size"])
                    == (dataset, scenario, size)]
            if len(rows) != 1:
                raise ValueError("missing unique frozen real input")
            row = rows[0]
            paths = {}
            for key, label in (("graph", "graph"), ("update", "updates")):
                entry = row[key]
                path = ROOT / entry["path"]
                if sha256_file(path) != entry["sha256"]:
                    raise ValueError("frozen real input changed")
                paths[label] = str(path)
                inputs[entry["path"]] = path
            data = facts(load_slice(ROOT / row["graph"]["path"]), load_slice(ROOT / row["update"]["path"]))
            if data["physical_updates"] != row["physical_records"] or data["final_edges"] != row["final_edges"]:
                raise ValueError("real operation facts differ from frozen source contract")
            cases[f"{abbreviation}-{scenario}-{size}"] = {**paths, **data}
        mapping = next(r for r in manifest["datasets"] if r["dataset_id"] == dataset)
        path = ROOT / mapping["mapping_path"]
        if sha256_file(path) != mapping["mapping_sha256"]:
            raise ValueError("real compact-ID mapping changed")
        inputs[mapping["mapping_path"]] = path
    result = input_contract()
    result.update({"cases": cases,
        "matrix": [{"case": case, "latency": latency, "arm": arm}
                   for latency in LATENCIES for case in cases for arm in ARMS],
        "graph_kind": "AU/SU/WK compact file-order real-topology slices; derived mixed and weight edits",
        "initial": "8192 live edges from frozen source contract; existing compact IDs retained",
        "updates": "unchanged frozen mixed-512 and weight-change-4096 records, in file order",
        "geometry": "single shard; trace-aware reserved segments; one appended isolated source owns empty cache padding",
        "limitations": manifest["limitations"] + ["not recovered original temporal operations", "all edited segments hot"],
        "input_pins": [{"path": str(path), "member": "inputs/" + name, "sha256": sha256_file(path)}
                       for name, path in sorted(inputs.items())]})
    return result
