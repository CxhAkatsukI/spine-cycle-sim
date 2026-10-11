"""Production contracts and conservation for the default-off row-line mode."""

from collections import Counter
import re

from ..adapter_axi.analysis import ROW_BASE
from ..routing import adapter_interface


BASE_FLAGS = {"GRASU_REGRAPH_" + name: "1" for name in (
    "WEIGHTED_PMA", "SHARDED_PMA", "SHARE_ALL_MEMORY_PORTS", "ROW_PREFETCH",
    "STOP_AFTER_LAST", "SKIP_EMPTY_SEGMENT")}
FLAGS = BASE_FLAGS | {"GRASU_REGRAPH_ROW_LINE_READ": "1"}


def require_xos(reference, candidate) -> dict:
    before, old_flags = adapter_interface(reference)
    after, new_flags = adapter_interface(candidate)
    for flags, expected in ((old_flags, BASE_FLAGS), (new_flags, FLAGS)):
        if {key: value for key, value in flags.items() if key.startswith("GRASU_")} != expected:
            raise ValueError("exact production flags required, without test-only depths")
    if before != after:
        raise ValueError("external kernel/control/stream ABI must remain identical")
    return {"interface": after, "flags": {"reference": old_flags, "candidate": new_flags},
            "row_memory_contract": "64B_aligned_padded_packed_le_u64_rows_with_8_entries_per_line"}


def require_functional(text: str) -> None:
    records = re.findall(r"^ROW_PREFETCH_EQUIVALENCE status=PASS cases=(\d+) packets=(\d+) "
                         r"skip_empty=([01])( row_line=1)?$", text, re.M)
    counts = Counter((int(cases), int(packets), skip, bool(line)) for cases, packets, skip, line in records)
    expected = {(254, 1482, "0", False): 3, (254, 1482, "1", False): 3, (254, 1482, "1", True): 3}
    if counts != expected:
        raise ValueError("all nine exact packet-equivalence matrices required")


def compare_traffic(reference: list[dict], candidate: list[dict]) -> list[dict]:
    if len(reference) != 12 or len(candidate) != 12:
        raise ValueError("complete twelve-case matrix required")
    results = []
    for old, new in zip(reference, candidate):
        if any(old[key] != new[key] for key in (
            "trial", "vertices", "placement", "length", "latency", "stall",
            "packets", "pma_requests", "pma_beats", "pma_transfer_bytes")):
            raise ValueError("wide row reads must preserve case, packet and PMA traffic")
        vertices, placement = new["vertices"], new["placement"]
        if not vertices:
            expected_lines = []
        else:
            occupied = [src for src in range(vertices) if (
                placement == 0 or placement == 1 and src + 1 == vertices
                or placement == 2 and src == 0 or placement == 3 and src % 7 == 0)]
            expected_lines = [(vertices - 1) // 8]
            expected_lines += list(range(occupied[-1] // 8 + 1))
        row_reads = [request for request in new["requests"] if request["address"] >= ROW_BASE]
        if (any(request["size"] != 64 or request["beats"] != 1 for request in row_reads)
                or [(request["address"] - ROW_BASE) // 64 for request in row_reads] != expected_lines
                or new["row_transfer_bytes"] != len(expected_lines) * 64):
            raise ValueError("each visited block plus the extent must issue exactly one whole-line read")
        results.append({key: new[key] for key in (
            "trial", "vertices", "placement", "length", "latency", "stall", "packets")} | {
                "reference_cycles": old["cycles"], "candidate_cycles": new["cycles"],
                "reference_row_requests": old["row_requests"], "candidate_row_requests": new["row_requests"],
                "reference_row_bytes": old["row_transfer_bytes"], "candidate_row_bytes": new["row_transfer_bytes"],
                "pma_requests_both": new["pma_requests"],
            })
    return results
