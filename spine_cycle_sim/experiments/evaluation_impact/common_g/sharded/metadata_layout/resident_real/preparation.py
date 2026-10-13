"""Declare chronological sequences and independently count fixed-reservation work."""

from bisect import bisect_right
from pathlib import Path

from spine_cycle_sim.experiments.shared_workloads import load_slice
from ...chronological_contract import contract as chronological_contract
from ..lifecycle.preparation import ARMS, LATENCIES

STATUS = "RESIDENT_CHRONOLOGICAL_G_CHECKED_NOT_BASELINE_ADMISSION"
PARTITION = 8192
DATASETS = ("AU", "SU", "WK")


def facts(graph, updates, *, partition=PARTITION, first=4096):
    if (graph.vertices != updates.vertices or partition <= 0 or partition > 2**19
            or not 0 < first < len(updates.records)):
        raise ValueError("resident chronological geometry differs")
    live, reserved = set(), {}
    for records in (graph.records, updates.records):
        for r in records:
            if (r.diff != 1 or not 0 <= r.src < graph.vertices or not 0 <= r.dst < graph.vertices
                    or not 1 <= r.weight <= 4095):
                raise ValueError("resident chronological insertion ABI differs")
            key = r.src, r.dst, r.weight
            if key in live:
                raise ValueError("resident chronological insertion is duplicate")
            live.add(key)
            row = r.dst // partition, r.src
            reserved.setdefault(row, set()).add(r.weight << 19 | r.dst % partition)
    heads = {key: sorted(words)[::16] for key, words in reserved.items()}
    vertices = graph.vertices + 1
    shards = (vertices + partition - 1) // partition
    batches = []
    for records in (updates.records[:first], (), updates.records[first:]):
        probes = multi = 0
        counts = [0] * shards
        for r in records:
            shard = r.dst // partition
            counts[shard] += 1
            row = heads[shard, r.src]
            begin, end = 0, len(row)
            multi += end > 1
            word = r.weight << 19 | r.dst % partition
            while begin != (begin + end) // 2:
                probes += 1
                mid = (begin + end) // 2
                if row[mid] <= word:
                    begin = mid
                else:
                    end = mid
            if begin != bisect_right(row, word) - 1:
                raise ValueError("resident independent segment search differs")
        batches.append({"physical_updates": len(records), "updated_shards": sum(n > 0 for n in counts),
                        "shard_updates": counts, "binary_probes": probes, "multi_segment_updates": multi})
    return {"vertices": vertices, "total_shards": shards, "live_edges": len(graph.records),
            "final_edges": len(live), "partition_vertices": partition, "batches": batches,
            "reserved_live_segments": sum(map(len, heads.values()))}


def contract(prepared):
    source = chronological_contract(prepared)
    cases = {}
    for dataset in DATASETS:
        selected = source["cases"][f"{dataset}-chronological-insert-65536"]
        data = facts(load_slice(Path(selected["graph"])), load_slice(Path(selected["updates"])))
        if (not 2 <= data["total_shards"] <= 3 or data["live_edges"] != 8192
                or data["final_edges"] != 73728):
            raise ValueError("resident chronological predeclared graph scope differs")
        cases[f"{dataset}-resident-chronological"] = {
            "graph": selected["graph"], "updates": selected["updates"], **data}
    source.update({"cases": cases, "batch_count": 3,
        "matrix": [{"case": name, "latency": latency, "arm": arm}
                   for latency in LATENCIES for name in cases for arm in ARMS],
        "updates": "continuous next 4096 contacts, empty batch, remaining 61440 contacts",
        "geometry": "8192-vertex destination shards; immutable union reservation; full two-half hot cache per touched shard",
        "residency": "one persistent backend and physical allocation across all three batches; no interbatch metadata upload",
        "control": "original source16 model per shard, prepared from preceding checked state; fresh control allocation per batch",
        "metadata_copies": "four extra row and binary copies per shard on channels 3,9,15,20; originals retained",
        "acceptance": "full payload/traffic/resource/state gates; absolute cycle difference <=10% per nonempty batch AND sequence total",
        "limitations": ["bounded compact chronological prefixes, not complete graphs or original GraSU paper operations",
            "8K partition diagnostic, not routed 64K configuration", "all edited segments hot; full cache transfers charged",
            "immutable future union reservation, not dynamic reservation refresh/coherence",
            "copy storage/upload charged in ledger, but host/init/DMA/orchestration time not measured",
            "G update cycles only; ReGraph, convergence, seeds and application computation excluded",
            "source16 original, not paper8", "prediction only; no candidate HLS, FPGA timing or publication admission"]})
    return source
