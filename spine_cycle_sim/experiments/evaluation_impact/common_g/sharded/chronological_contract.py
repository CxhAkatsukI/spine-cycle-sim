"""Validate chronological provenance and declare the complete G comparison."""

import csv
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.shared_workloads import load_slice
from .chronological_inputs import AUTHORITY, BASE_EDGES, BATCHES, DATASETS, compact_contacts, source_spec
from .preparation import ARMS, LATENCIES, input_contract
from .real_inputs import facts


def case_names():
    return {f"{dataset}-chronological-insert-{size}" for dataset in DATASETS for size in BATCHES}


def contract(prepared):
    report = json.loads((prepared / "preparation.json").read_text())
    if report["status"] != "PREPARED" or report["datasets"] != list(DATASETS) or len(report["steps"]) != 3:
        raise ValueError("complete chronological preparation required")
    pins = [{"path": str(AUTHORITY), "member": "inputs/authority.json", "sha256": sha256_file(AUTHORITY)}]
    cases = {}
    for dataset in DATASETS:
        folder = prepared / dataset
        manifest = json.loads((folder / "manifest.json").read_text())
        spec, _ = source_spec(dataset)
        if (manifest["dataset"] != dataset or manifest["base_edges"] != BASE_EDGES or
                manifest["batches"] != list(BATCHES) or manifest["ordering"] != "timestamp_then_file_order" or
                manifest["authority_sha256"] != sha256_file(AUTHORITY) or
                manifest["source_sha256"] != spec["sha256"] or sha256_file(Path(manifest["source"])) != spec["sha256"]):
            raise ValueError("chronological source or declaration changed")
        expected_files = {"base.slice", "contacts.csv", "mapping.csv", *(f"insert-{n}.slice" for n in BATCHES)}
        if (len(manifest["artifacts"]) != len(expected_files) or
                {Path(p["path"]).name for p in manifest["artifacts"]} != expected_files):
            raise ValueError("incomplete chronological input pins")
        for pin in manifest["artifacts"]:
            if Path(pin["path"]).parent != folder or sha256_file(Path(pin["path"])) != pin["sha256"]:
                raise ValueError("chronological input changed")
        with (folder / "contacts.csv").open(newline="", encoding="ascii") as stream:
            contacts = [tuple(map(int, (r[key] for key in (
                "source_event_index", "timestamp", "external_src", "external_dst")))) for r in csv.DictReader(stream)]
        orders = [(r[1], r[0]) for r in contacts]
        if (len(contacts) != BASE_EDGES + max(BATCHES) or orders != sorted(set(orders)) or
                len({r[2:] for r in contacts}) != len(contacts) or any(r[2] == r[3] or min(r) < 0 for r in contacts)):
            raise ValueError("chronological first-contact provenance differs")
        selection = manifest["selection"]
        if (selection["scanned_events"] != len(contacts) + selection["excluded_self_loops"] +
                selection["excluded_repeat_contacts"] or manifest["ingestion"]["source_sha256"] != spec["sha256"]):
            raise ValueError("chronological filtering or source ledger differs")
        ids, records = compact_contacts(contacts)
        with (folder / "mapping.csv").open(newline="", encoding="ascii") as stream:
            mapping = [(int(r["external_id"]), int(r["compact_id"])) for r in csv.DictReader(stream)]
        if mapping != list(ids.items()) or len(ids) != manifest["compact_vertices"]:
            raise ValueError("chronological fixed compact-ID mapping differs")
        graph = load_slice(folder / "base.slice")
        if graph.vertices != len(ids) or graph.records != records[:BASE_EDGES]:
            raise ValueError("chronological base differs from provenance")
        for size in BATCHES:
            batch = load_slice(folder / f"insert-{size}.slice")
            if batch.records != records[BASE_EDGES:BASE_EDGES + size]:
                raise ValueError("chronological insertion prefix differs from provenance")
            data = facts(graph, batch)
            if data["physical_updates"] != size or data["final_edges"] != BASE_EDGES + size:
                raise ValueError("chronological mutation count differs")
            cases[f"{dataset}-chronological-insert-{size}"] = {
                "graph": str(folder / "base.slice"), "updates": str(folder / f"insert-{size}.slice"), **data}
        pins.extend(manifest["artifacts"])
        pins.append({"path": str(folder / "manifest.json"), "member": f"inputs/{dataset}/manifest.json",
                     "sha256": sha256_file(folder / "manifest.json")})
    logs = [prepared / "preparation.json"]
    for step in report["steps"]:
        if step["exit_code"] or step["timed_out"] or step["memory_limit_gib"] != 2 or step["reserve_gib"] < 8:
            raise ValueError("unsafe or unsuccessful chronological preparation")
        logs.extend(Path(step[key]) for key in ("stdout", "stderr"))
        logs.append(Path(step["stdout"].replace(".stdout.txt", ".resources.json")))
    pins.extend({"path": str(p), "member": "preparation/" + p.name, "sha256": sha256_file(p)} for p in logs)
    result = input_contract()
    result.update({"cases": cases, "matrix": [{"case": case, "latency": latency, "arm": arm}
        for latency in LATENCIES for case in cases for arm in ARMS], "input_pins": pins,
        "graph_kind": "AU/SU/WK chronological first-contact directed simple-graph prefixes; compact IDs",
        "initial": "8192 chronological unique non-self edges; fixed IDs cover the largest future batch",
        "updates": "next 4096/65536 unique contacts, unit weights, independent prefixes from the same base",
        "geometry": "single shard; trace-aware reservation; isolated padding source; complete two-half cache",
        "limitations": ["not recovered original GraSU insertion/deletion conversion or paper denominator",
            "repeated contacts and self loops excluded explicitly, not claimed original semantics",
            "compact IDs and future-ID allocation change partition occupancy", "all edited segments hot",
            "fixed complete cache costs paid; not isolated search timing", "source16 original, not paper8",
            "host reservation, orchestration, DMA and ReGraph excluded", "prediction only, not HLS or FPGA timing"]})
    return result
