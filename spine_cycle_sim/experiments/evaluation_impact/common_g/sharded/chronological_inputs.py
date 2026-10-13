"""Prepare bounded first-contact insertions from disk-sorted temporal events."""

import argparse
import csv
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.publication_admission.temporal import connect, ingest
from spine_cycle_sim.experiments.shared_workloads import SliceGraph, SliceRecord, write_slice
from ..study import ROOT

AUTHORITY = ROOT / "configs/experiments/grasu_publication_workload_admission_v1.json"
SOURCE_ROOT = Path("/data/feiyang/Graph_Datasets")
DATASETS = ("AU", "SU", "WK")
BASE_EDGES = 8192
BATCHES = (4096, 65536)
STATUS = "CHRONOLOGICAL_G_PREDICTIONS_CHECKED_NOT_BASELINE_ADMISSION"


def select_contacts(events, base_edges=BASE_EDGES, updates=max(BATCHES)):
    if base_edges <= 0 or updates <= 0:
        raise ValueError("positive base and insertion counts required")
    seen, selected = set(), []
    counts = {"scanned_events": 0, "excluded_self_loops": 0, "excluded_repeat_contacts": 0}
    previous = None
    for seq, timestamp, packed in events:
        order = timestamp, seq
        if min(seq, timestamp, packed) < 0 or (previous is not None and order <= previous):
            raise ValueError("events are not strictly timestamp/file-position ordered")
        previous = order
        counts["scanned_events"] += 1
        src, dst = packed >> 32, packed & 0xffffffff
        if src == dst:
            counts["excluded_self_loops"] += 1
        elif packed in seen:
            counts["excluded_repeat_contacts"] += 1
        else:
            seen.add(packed)
            selected.append((seq, timestamp, src, dst))
            if len(selected) == base_edges + updates:
                return selected, counts
    raise ValueError("insufficient unique non-self first contacts; no silent downsizing")


def compact_contacts(contacts):
    ids, records = {}, []
    for _, _, src, dst in contacts:
        for vertex in (src, dst):
            if vertex not in ids:
                ids[vertex] = len(ids)
        records.append(SliceRecord(ids[src], ids[dst]))
    if len(ids) >= 65535:
        raise ValueError("chronological input exceeds the declared single-shard limit")
    return ids, tuple(records)


def source_spec(dataset):
    config = json.loads(AUTHORITY.read_text())
    rows = [r for r in config["datasets"] if r["id"] == dataset]
    if dataset not in DATASETS or len(rows) != 1:
        raise ValueError("undeclared temporal dataset")
    return rows[0], config["limits"]


def prepare(output, dataset):
    output.mkdir(parents=True, exist_ok=False)
    spec, limits = source_spec(dataset)
    source = SOURCE_ROOT / spec["source"]
    database = output / "events.sqlite"
    print("INGEST " + dataset, flush=True)
    ingestion = ingest(source, spec["sha256"], database, limits["max_events"], limits["sqlite_cache_kib"])
    with connect(database, limits["sqlite_cache_kib"]) as connection:
        contacts, selection = select_contacts(connection.execute(
            "SELECT seq,timestamp,edge FROM events ORDER BY timestamp,seq"))
    ids, records = compact_contacts(contacts)
    with (output / "contacts.csv").open("w", newline="", encoding="ascii") as stream:
        writer = csv.writer(stream)
        writer.writerow(("source_event_index", "timestamp", "external_src", "external_dst"))
        writer.writerows(contacts)
    with (output / "mapping.csv").open("w", newline="", encoding="ascii") as stream:
        writer = csv.writer(stream)
        writer.writerow(("compact_id", "external_id"))
        writer.writerows((compact, external) for external, compact in ids.items())
    write_slice(output / "base.slice", SliceGraph(dataset + "-chronological-base", len(ids), records[:BASE_EDGES]))
    for size in BATCHES:
        write_slice(output / f"insert-{size}.slice", SliceGraph(
            f"{dataset}-chronological-insert-{size}", len(ids), records[BASE_EDGES:BASE_EDGES + size]))
    artifacts = [{"path": str(path), "member": f"inputs/{dataset}/{path.name}",
                  "sha256": sha256_file(path)} for path in sorted(output.iterdir()) if path.suffix in (".csv", ".slice")]
    manifest = {"schema_version": 1, "dataset": dataset, "base_edges": BASE_EDGES, "batches": BATCHES,
        "ordering": "timestamp_then_file_order", "source": str(source), "source_sha256": spec["sha256"],
        "authority_sha256": sha256_file(AUTHORITY), "ingestion": ingestion, "selection": selection,
        "compact_vertices": len(ids), "artifacts": artifacts,
        "semantics": "first non-self directed contact inserts one unit-weight simple-graph edge; repeats excluded",
        "reservation": "fixed compact IDs cover base and largest batch; trace-aware PMA reservation per batch"}
    atomic_write_json(output / "manifest.json", manifest)
    database.unlink()
    print(json.dumps({"dataset": dataset, "vertices": len(ids), **selection}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--dataset", required=True, choices=DATASETS)
    args = parser.parse_args()
    prepare(args.output.resolve(), args.dataset)
