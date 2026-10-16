"""Validate guarded offline host outputs without promoting FPGA claims."""

import array
from pathlib import Path

from . import oracle

STATUS = "ORIGINAL_R_CONTROL_OFFLINE_VALIDATED_NOT_FPGA"
GUARD = 0xA55A5AA5
BINDINGS = {"author_initial": "original_host_result_sha256",
            "csr_degree": "csr_degree_result_sha256"}
EXPECTED = {(topology, graph, binding)
            for topology in ("a4", "original_example")
            for graph in ("boundary_ring", "skewed_sources", "amazon")
            for binding in BINDINGS}


def inspect(report: dict, output: Path, reference: dict) -> dict:
    if (report.get("status") != "ORIGINAL_R_CONTROL_OFFLINE_PASS_NOT_FPGA" or
            any(report.get(name) is not False for name in
                ("board_programmed", "hardware_timing_measured", "publication_match")) or
            report.get("events") != [] or report.get("bdf") != "" or
            any(report.get(name) is not None for name in
                ("enqueue_to_completion_ms", "event_union_ns", "event_span_ns")) or
            report.get("binding") not in BINDINGS or report.get("iterations") != 1 or
            report.get("argument") != 0 or report.get("guard_words") != 16):
        raise ValueError("explicit offline one-superstep control required; no FPGA timing claim")
    names = ("vertices", "aligned_vertices", "published_vertices", "allocation_vertices")
    if any(type(report.get(name)) is not int or report[name] <= 0 for name in names):
        raise ValueError("positive bounded geometry required")
    vertices, aligned, published, allocation = [report[name] for name in names]
    if (not vertices <= aligned <= allocation < 2**26 or published > allocation or
            report.get("extra_padding_vertices") != allocation - aligned or
            vertices != reference["vertices"] or aligned != reference["original_allocation_words"] or
            published != reference["device_publication_words"] or
            report.get("logical_edges") != reference["logical_edges"] or
            report.get("physical_edges") != reference["physical_edges"] or
            report.get("dummy_edges") != reference["physical_edges"] - reference["logical_edges"]):
        raise ValueError("guarded control geometry differs from independent audit")
    words = oracle.read_words(output / "expected.u32le", allocation + 16)
    if (any(word != GUARD for word in words[published:]) or
            any(words[aligned:published])):
        raise ValueError("unpublished tail/guards changed or publication padding is nonzero")
    # The original audit stores zero for unpublished isolated suffix vertices.
    canonical = array.array("I", words[:aligned])
    if published < aligned:
        canonical[published:] = array.array("I", [0]) * (aligned - published)
    key = BINDINGS[report["binding"]]
    if oracle.digest(canonical) != reference["one_superstep_comparison"][key]:
        raise ValueError("guarded control differs from independent CSR/task PR oracle")
    return {"expected_sha256": oracle.digest(words), "canonical_aligned_sha256": oracle.digest(canonical),
            "logical_sha256": oracle.digest(canonical[:vertices]),
            "complete_guard_and_tail_checked": True, "publication_padding_checked": True}


def matrix(rows: list[dict]) -> None:
    if len(rows) != 48:
        raise ValueError("both builds and repeats of all twelve named controls required")
    for build in ("release", "ubsan"):
        for repetition in range(2):
            selected = [row for row in rows if row["build"] == build and row["repetition"] == repetition]
            if (len(selected) != len(EXPECTED) or
                    {(row["topology"], row["graph"], row["binding"]) for row in selected} != EXPECTED):
                raise ValueError("incomplete offline control matrix")
    for key in EXPECTED:
        selected = [row for row in rows if (row["topology"], row["graph"], row["binding"]) == key]
        if len({row["analysis"]["expected_sha256"] for row in selected}) != 1:
            raise ValueError("release, UBSan or repeated outputs differ")
    for graph in ("boundary_ring", "skewed_sources", "amazon"):
        for binding in BINDINGS:
            selected = [row for row in rows if row["graph"] == graph and row["binding"] == binding]
            if len({row["analysis"]["logical_sha256"] for row in selected}) != 1:
                raise ValueError("A4 and 11+3 logical outputs differ for the same divisor binding")
