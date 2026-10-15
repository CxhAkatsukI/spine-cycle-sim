"""Compare explicit PR divisor bindings over frozen CSR and author tasks."""

import array
from pathlib import Path
import sys

from spine_cycle_sim.experiments.campaign_runtime import sha256_file

LIMIT = 2**31 - 1


def read_words(path: Path, words: int) -> array.array:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != words * 4:
        raise ValueError("frozen author capture extent or type changed")
    values = array.array("I")
    if values.itemsize != 4:
        raise ValueError("32-bit array words required")
    with path.open("rb") as stream:
        values.fromfile(stream, words)
        if stream.read(1):
            raise ValueError("author capture grew during read")
    if sys.byteorder != "little":
        values.byteswap()
    return values


def apply(sums, divisors) -> tuple[array.array, int]:
    if len(sums) != len(divisors):
        raise ValueError("PR sums and divisors have different extents")
    values, rejections = array.array("I"), 0
    for total, divisor in zip(sums, divisors):
        if total < 0 or divisor < 0 or divisor > LIMIT:
            raise ValueError("PR input outside nonnegative signed domain")
        damped = total * 108
        product = (damped >> 7) * (65536 // divisor if divisor else 0)
        if max(total, damped, product) > LIMIT:
            rejections += 1
            values.append(0)
        else:
            values.append(product >> 16)
    return values, rejections


def digest(values: array.array) -> str:
    import hashlib
    if sys.byteorder == "little":
        return hashlib.sha256(values.tobytes()).hexdigest()
    copy = array.array("I", values)
    copy.byteswap()
    return hashlib.sha256(copy.tobytes()).hexdigest()


def audit(directory: Path, layout: dict) -> dict:
    summary = layout["summary"]
    vertices, aligned = summary["vertices"], summary["aligned_vertices"]
    if (type(vertices) is not int or type(aligned) is not int or not 0 < vertices <= 255 * 65536 or
            aligned != (vertices + 65535) // 65536 * 65536):
        raise ValueError("unsupported bounded author geometry")
    captures = {}
    expected = {"csr_offsets.u32le": vertices + 1,
                "csr_destinations.u32le": summary["logical_edges"],
                "initial.u32le": aligned, "degrees.u32le": aligned,
                "tasks.u32le": summary["task_physical_edges"] * 2,
                "original_to_reordered.u32le": vertices,
                "partitions.u32le": sum(row["words"] for row in layout["partitions"])}
    files = layout["files"]
    if len(files) != len(expected) or {item["path"] for item in files} != set(expected):
        raise ValueError("exact seven author captures required")
    pins = []
    for item in files:
        path = directory / item["path"]
        words = expected[item["path"]]
        if (type(words) is not int or not 0 <= words <= 2**27 or item["words"] != words or
                item["bytes"] != words * 4 or item["format"] != "u32le" or
                sha256_file(path) != item["sha256"]):
            raise ValueError("author capture identity differs from admitted layout")
        values = read_words(path, words)
        if item["path"] in ("initial.u32le", "degrees.u32le", "csr_offsets.u32le",
                             "csr_destinations.u32le", "tasks.u32le"):
            captures[item["path"]] = values
        pins.append({"path": str(path.resolve()), "sha256": item["sha256"]})
    initial, degrees = captures["initial.u32le"], captures["degrees.u32le"]
    offsets, targets = captures["csr_offsets.u32le"], captures["csr_destinations.u32le"]
    if offsets[0] or offsets[-1] != len(targets):
        raise ValueError("CSR offset endpoints changed")
    sums = array.array("Q", [0]) * aligned
    for source in range(vertices):
        if (not offsets[source] <= offsets[source + 1] <= len(targets) or
                degrees[source] != offsets[source + 1] - offsets[source] or initial[source] > LIMIT):
            raise ValueError("CSR offsets, degrees or initial domain changed")
        for index in range(offsets[source], offsets[source + 1]):
            target = targets[index]
            if target >= vertices:
                raise ValueError("CSR destination outside graph")
            sums[target] += initial[source]
    if any(initial[vertices:]) or any(degrees[vertices:]):
        raise ValueError("author padded state must be zero")
    task_sums = array.array("Q", [0]) * aligned
    task_words, cursor, logical = captures["tasks.u32le"], 0, 0
    for task in layout["tasks"]:
        count, base = task["words"], task["offset_words"]
        if base != cursor or not count or count % 16 or base + count > len(task_words):
            raise ValueError("task ranges do not cover admitted physical words")
        for index in range(base, base + count, 2):
            source, target = task_words[index] & 0x7fffffff, task_words[index + 1]
            if source >= vertices:
                raise ValueError("task source outside graph")
            if target == 0xffffffff:
                continue
            if not task["dst_offset"] <= target < min(vertices, task["dst_offset"] + task["dst_len"]):
                raise ValueError("task destination outside graph or partition")
            task_sums[target] += initial[source]
            logical += 1
        cursor += count
    if cursor != len(task_words) or logical != len(targets) or sums != task_sums:
        raise ValueError("author tasks and CSR first-superstep gather differ")
    original, original_overflow = apply(sums, initial)
    corrected, corrected_overflow = apply(sums, degrees)
    published = (summary["dense_partitions"] + 8 * summary["sparse_groups"]) * 65536
    comparison = None if original_overflow or corrected_overflow else {
        "different_logical_vertices": sum(a != b for a, b in zip(original[:vertices], corrected[:vertices])),
        "original_host_result_sha256": digest(original), "csr_degree_result_sha256": digest(corrected)}
    return {"status": "PR_BINDING_AUDIT_NOT_BOARD_CORRECTNESS", "vertices": vertices,
            "logical_edges": len(targets), "physical_edges": len(task_words) // 2,
            "csr_task_gather_equal": True,
            "different_logical_divisors": sum(a != b for a, b in zip(initial[:vertices], degrees[:vertices])),
            "original_host_signed_overflow_vertices": original_overflow,
            "csr_degree_signed_overflow_vertices": corrected_overflow,
            "one_superstep_comparison": comparison,
            "original_allocation_words": aligned, "device_publication_words": published,
            "publication_excess_words": max(0, published - aligned),
            "original_output_allocation_covers_publication": published <= aligned,
            "padding_control_applied": False, "pins": pins,
            "scope": "one author fixed-point PR superstep; no convergence, FPGA timing or publication match"}
