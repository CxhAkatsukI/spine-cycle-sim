"""Admit host layout extents, scheduling metadata and exact repeated captures."""

from __future__ import annotations

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file

STATUS = "ORIGINAL_HOST_LAYOUT_PASS_NOT_DEVICE_TIMING"


def records(text: str, prefix: str) -> list[dict]:
    result = [json.loads(line.removeprefix(prefix)) for line in text.splitlines() if line.startswith(prefix)]
    if not result or any(type(row) is not dict for row in result):
        raise ValueError("original layout is missing structured results")
    return result


def analyze_layout(stdout: str, directory: Path, topology: dict, graph: dict, contract: dict) -> dict:
    summaries = records(stdout, "PUBLICATION_LAYOUT ")
    if len(summaries) != 1:
        raise ValueError("original layout needs one summary")
    summary = summaries[0]
    if summary.get("passed") is not True or summary.get("kind") != "original_regraph_host_layout":
        raise ValueError("original layout did not pass")
    for key, value in summary.items():
        if key not in ("passed", "kind") and (type(value) is not int or value < 0):
            raise ValueError("original layout counters must be nonnegative integers")
    if (any(summary[key] != topology[key] for key in ("little", "big")) or summary["seed"] != contract["seed"] or
            any(summary[key] != graph[key] for key in ("vertices", "logical_edges")) or
            summary["aligned_vertices"] != (summary["vertices"] + 65535) // 65536 * 65536 or
            not 0 < summary["partitions"] <= summary["aligned_vertices"] // 65536 or
            summary["task_physical_edges"] - summary["task_dummy_edges"] != summary["logical_edges"] or
            summary["source_allocation_rejections"] or summary["initial_arithmetic_rejections"] or
            summary["edge_bytes_max_channel"] >= 256 * 1024**2):
        raise ValueError("original layout work, extent, memory or initial arithmetic admission failed")
    dense = summary["partitions"] if topology["big"] == 0 else min(
        topology["dense_partitions_argument"], summary["partitions"])
    sparse = (summary["partitions"] - dense + 7) // 8
    if (summary["dense_partitions"], summary["sparse_groups"]) != (dense, sparse):
        raise ValueError("original dense/sparse scheduling boundary changed")
    partitions = records(stdout, "ORIGINAL_LAYOUT_PARTITION ")
    tasks = records(stdout, "ORIGINAL_LAYOUT_TASK ")
    partition_words = _check_partitions(partitions, summary)
    task_words = _check_tasks(tasks, topology, dense, sparse)
    if task_words // 2 != summary["task_physical_edges"]:
        raise ValueError("task descriptors disagree with physical edge count")
    expected_words = {
        "original_to_reordered.u32le": summary["vertices"], "csr_offsets.u32le": summary["vertices"] + 1,
        "csr_destinations.u32le": summary["logical_edges"], "initial.u32le": summary["aligned_vertices"],
        "degrees.u32le": summary["aligned_vertices"], "partitions.u32le": partition_words, "tasks.u32le": task_words,
    }
    if set(contract["capture_files"]) != set(expected_words):
        raise ValueError("layout capture schema changed")
    files = []
    for name in contract["capture_files"]:
        path = directory / name
        if path.is_symlink() or path.stat().st_size != expected_words[name] * 4:
            raise ValueError("layout capture extent or file type mismatch")
        files.append({"path": name, "words": expected_words[name], "bytes": path.stat().st_size,
                      "sha256": sha256_file(path), "format": "u32le"})
    return {"status": STATUS, "summary": summary, "partitions": partitions, "tasks": tasks,
            "files": files, "device_cycles": None, "publication_rate_error_pct": None}


def _check_partitions(rows: list[dict], summary: dict) -> int:
    offset = 0
    if [row.get("id") for row in rows] != list(range(summary["partitions"])):
        raise ValueError("original partition descriptors missing, reordered or duplicated")
    for row in rows:
        if any(type(value) is not int or value < 0 for value in row.values()):
            raise ValueError("partition metadata must use nonnegative integer words")
        if (row["offset_words"] != offset or row["words"] == 0 or row["words"] % 16 or
                row["dst_offset"] != row["id"] * 65536 or row["dst_len"] != 65536):
            raise ValueError("original partition offsets/extents/alignment invalid")
        offset += row["words"]
    return offset


def _check_tasks(rows: list[dict], topology: dict, dense: int, sparse: int) -> int:
    expected = [(kind, part, sub) for kind, count, kernels in (
        ("dense", dense, topology["little"]), ("sparse", sparse, topology["big"]))
        for part in range(count) for sub in range(kernels)]
    if [(row.get("kind"), row.get("partition"), row.get("subpartition")) for row in rows] != expected:
        raise ValueError("original task descriptors missing, reordered or duplicated")
    offset = 0
    for row in rows:
        if any(type(value) is not int or value < 0 for key, value in row.items() if key != "kind"):
            raise ValueError("task metadata must use nonnegative integer words")
        little = row["kind"] == "dense"
        kernels = topology["little"] if little else topology["big"]
        kernel = row["subpartition"] if row["partition"] % 2 == 0 else kernels - 1 - row["subpartition"]
        kernel += 0 if little else topology["little"]
        destination = row["partition"] * 65536 if little else (dense + row["partition"] * 8) * 65536
        if (row["kernel"] != kernel or row["offset_words"] != offset or not row["words"] or row["words"] % 16 or
                row["dst_offset"] != destination or row["dst_len"] != (65536 if little else 524288)):
            raise ValueError("original task kernel/range/offset/alignment invalid")
        offset += row["words"]
    return offset
