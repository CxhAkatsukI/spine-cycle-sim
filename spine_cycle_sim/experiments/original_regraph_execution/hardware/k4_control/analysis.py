"""Independent CSR values and complete-matrix checks, not a timing fit."""

import array
import itertools
from pathlib import Path
import struct

from .. import oracle
from ..semantics import arithmetic
from .inputs import GRAPHS

BINDINGS = ("author_initial", "csr_degree")
BUILDS = ("release", "ubsan")
PASS = "OFFLINE_MATCHED_K4_A4_MODEL_PASS_NOT_FPGA"
UNSUPPORTED = "UNSUPPORTED_DUPLICATE_EDGES_NOT_PERFORMANCE_EVIDENCE"
ASSERTIONS = {"csr_task_edges_equal", "permutation_bijection", "pma_conservation",
              "packed_gather_equal", "full_capacity_and_trailing_guards", "guarded_bank_capacity"}


def prepare(item):
    directory = Path(item["directory"])
    descriptor_path = directory / "execution.u32le"
    if descriptor_path.stat().st_size % 4:
        raise ValueError("complete descriptor words required")
    descriptor = oracle.read_words(descriptor_path, descriptor_path.stat().st_size // 4)
    if len(descriptor) < 8 or list(descriptor[:2]) != [0x3447524F, 1]:
        raise ValueError("versioned A4 descriptor required")
    vertices, edges, aligned, published = descriptor[2:6]
    read = lambda name, count: oracle.read_words(directory / name, count)
    offsets = read("csr_offsets.u32le", vertices + 1)
    destinations = read("csr_destinations.u32le", edges)
    initial, degrees = read("initial.u32le", aligned), read("degrees.u32le", aligned)
    sums = arithmetic.csr_sums(offsets, destinations, initial, vertices)
    if (aligned != ((vertices + 65535) // 65536) * 65536 or published > aligned or
            any(degrees[vertices:]) or
            any(degrees[v] != offsets[v + 1] - offsets[v] for v in range(vertices))):
        raise ValueError("complete zero-padded A4 CSR geometry required")
    duplicates, first_duplicate = 0, None
    for source in range(vertices):
        seen = set()
        for index in range(offsets[source], offsets[source + 1]):
            destination = destinations[index]
            if destination in seen:
                duplicates += 1
                if first_duplicate is None:
                    first_duplicate = [source, destination]
            seen.add(destination)
    expected = {}
    for binding, divisors in (("author_initial", initial), ("csr_degree", degrees)):
        current = arithmetic.compare(sums, divisors, vertices)
        if current != item["arithmetic"][binding]:
            raise ValueError("independent fresh CSR arithmetic differs from audit")
        expected[binding] = current["float_logical_bits_sha256"]
    gathered = array.array("I", (struct.unpack("<I", struct.pack("<f", value))[0]
                                for value in sums[:vertices]))
    return {"vertices": vertices, "logical_edges": edges, "capacity_vertices": aligned,
            "a4_published_vertices": published, "duplicates": duplicates,
            "first_duplicate": first_duplicate, "expected_payload": expected,
            "expected_gather_sha256": oracle.digest(gathered)}


def profile(expected, binding):
    geometry = {key: expected[key] for key in
                ("vertices", "logical_edges", "capacity_vertices", "a4_published_vertices")}
    return {"schema_version": 1, "binding": binding, **geometry,
               "partitions": expected["capacity_vertices"] // 65536,
               "partition_vertices": 65536, "graph_channels": 23, "cache_segments": 131072,
               "row_line_read": True, "iterations": 1, "damping_numerator": 108,
               "damping_denominator": 128, "base": 0, "dangling_share": 0,
               "rank_initial": 0, "updates": 0, "g_skipped": True,
               "source_prepare_skipped": True}


def inspect(report, directory, expected, binding):
    required = {**profile(expected, binding), "status": PASS,
                "external_binary_encoding": "logical-V-u32le-binary32-bits",
                "permutation_encoding": "logical-V-u32le-external-to-internal"}
    if any(type(report.get(key)) is not type(value) or report[key] != value
           for key, value in required.items()):
        raise ValueError("exact matched K4 offline profile/geometry required")
    if (set(report.get("assertions", {})) != ASSERTIONS or
            any(value is not True for value in report["assertions"].values()) or
            any(report.get(key) is not False for key in ("board_programmed", "hardware_timing_measured",
                                                       "publication_match", "default_profile_equivalence")) or
            any("cycle" in key or "seconds" in key for key in report)):
        raise ValueError("complete offline assertions and no-hardware/no-timing claims required")
    return values(directory, expected, binding)


def values(directory, expected, binding, *, gather="gathered_external.u32le", payload="payload_external.u32le"):
    vertices = expected["vertices"]
    read = lambda name: oracle.read_words(directory / name, vertices)
    gathered, published = read(gather), read(payload)
    permutation = read("external_to_internal.u32le")
    if sorted(permutation) != list(range(vertices)):
        raise ValueError("complete external/internal permutation bijection required")
    digests = {"gather_sha256": oracle.digest(gathered), "payload_sha256": oracle.digest(published),
               "permutation_sha256": oracle.digest(permutation)}
    if (digests["gather_sha256"] != expected["expected_gather_sha256"] or
            digests["payload_sha256"] != expected["expected_payload"][binding]):
        raise ValueError("K4 output differs from independent CSR binary32 arithmetic")
    return digests


def matrix(rows):
    keys = [(row["build"], row["graph"], row["binding"], row["repetition"]) for row in rows]
    expected = set(itertools.product(BUILDS, GRAPHS, BINDINGS, range(2)))
    if len(keys) != len(expected) or set(keys) != expected:
        raise ValueError("complete 24-row predeclared K4 control matrix required")
    for graph, binding in itertools.product(GRAPHS, BINDINGS):
        selected = [row for row in rows if row["graph"] == graph and row["binding"] == binding]
        if len({row["status"] for row in selected}) != 1:
            raise ValueError("repeat/build eligibility differs")
        if selected[0]["status"] == PASS:
            if any(row["analysis"] != selected[0]["analysis"] for row in selected):
                raise ValueError("repeat/build K4 outputs differ")
        elif selected[0]["status"] != UNSUPPORTED:
            raise ValueError("failed or unknown row cannot pass offline matrix audit")
