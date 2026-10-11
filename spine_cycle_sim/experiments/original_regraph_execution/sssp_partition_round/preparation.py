"""Deterministic induced real topology, without synthesizing missing edges."""

from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.shared_workloads import SliceGraph, SliceRecord

SOURCE_SHA256 = "60b383901873b49883d0c67d8b524244ada1977719d25c834014b75238f3a815"
VERTICES = 4 * 65536 - 4096


def select(source: Path, target: Path, *, vertices: int = VERTICES,
           expected_sha256: str = SOURCE_SHA256) -> tuple[SliceGraph, dict]:
    if source.is_symlink() or sha256_file(source) != expected_sha256:
        raise ValueError("source Amazon identity differs")
    if not 0 < vertices <= VERTICES or target.exists():
        raise ValueError("invalid induced extent or existing output")
    pairs = set()
    total = duplicates = excluded = 0
    with source.open(encoding="ascii") as stream:
        for line in stream:
            fields = line.split()
            if len(fields) != 2:
                raise ValueError("source requires exactly two integer columns")
            src, dst = map(int, fields)
            if min(src, dst) < 0:
                raise ValueError("negative source vertex")
            total += 1
            # Select external IDs [1, N], then subtract one, not degree compacting.
            if not (1 <= src <= vertices and 1 <= dst <= vertices):
                excluded += 1
                continue
            pair = (src - 1, dst - 1)
            if pair in pairs:
                duplicates += 1
            pairs.add(pair)
    if not pairs:
        raise ValueError("empty selected topology")
    inferred_vertices = max(max(pair) for pair in pairs) + 1
    if not any(src == 0 for src, _ in pairs):
        raise ValueError("selected source 0 has no outgoing edge")
    records = tuple(SliceRecord(src, dst, 1 + ((src * 17 + dst * 13) % 31))
                    for src, dst in sorted(pairs))
    graph = SliceGraph("amazon_induced_four_partitions", inferred_vertices, records)
    with target.open("x", encoding="ascii") as stream:
        for edge in records:
            stream.write(f"{edge.src} {edge.dst}\n")
    if sha256_file(source) != expected_sha256:
        raise ValueError("source changed during selection")
    return graph, {"source": {"path": str(source), "sha256": expected_sha256},
        "source_rows": total, "excluded_rows": excluded, "duplicate_rows_removed": duplicates,
        "vertices": inferred_vertices, "requested_external_id_upper_bound": vertices,
        "trailing_unused_IDs_omitted_by_author_loader": vertices - inferred_vertices,
        "logical_edges": len(records),
        "original_source_lookahead_padding_vertices": 4096,
        "external_id_range_inclusive": [1, vertices], "id_transform": "subtract_one_then_author_DBG",
        "selection": "directed_induced_unique_pairs_no_degree_cap_no_synthetic_edges",
        "weight_rule": "1 + ((normalized_source * 17 + normalized_destination * 13) % 31)",
        "topology": {"path": str(target), "sha256": sha256_file(target)},
        "not_claimed": ["full_original_graph", "physical_ID_locality", "original_published_SSSP_weights"]}
