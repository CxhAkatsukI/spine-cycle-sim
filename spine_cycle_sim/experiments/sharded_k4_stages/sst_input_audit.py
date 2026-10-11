"""Independent old-state/frontier audit and row-tail inventory, outside device time."""

import array
from pathlib import Path
import struct
import sys

INF = 0xffffffff
WIRE_INF = 0x7ffffffe


def synchronous_sssp(adjacency: list, source: int, limit: int = 256) -> tuple[list[int], int]:
    state = [INF] * len(adjacency)
    state[source] = 0
    active = [source]
    for step in range(1, limit + 1):
        pending = {}
        for vertex in active:
            for destination, weight in adjacency[vertex]:
                value = state[vertex] + weight
                if value < WIRE_INF and value < state[destination]:
                    pending[destination] = min(pending.get(destination, INF), value)
        for destination, value in pending.items():
            state[destination] = value
        active = list(pending)
        if not active:
            return state, step
    raise ValueError("old graph does not converge within the actual host's 256-round oracle cap")


def _words(stream, count: int) -> array.array:
    result = array.array("I")
    result.fromfile(stream, count)
    if result.itemsize != 4:
        raise ValueError("fixture audit requires four-byte unsigned integers")
    if sys.byteorder != "little":
        result.byteswap()
    return result


def audit_resident_input(graph: Path, fixture: Path, source: int) -> dict:
    with fixture.open("rb") as stream:
        magic, version, vertices, partitions, cache, rounds, active_count = struct.unpack("<7I", stream.read(28))
        if magic != 0x4b345331 or version != 1 or partitions != (vertices + 65535) // 65536:
            raise ValueError("unsupported audit fixture")
        mapping, old = _words(stream, vertices), _words(stream, vertices)
        active = _words(stream, active_count)
        _words(stream, vertices)  # New-state oracle is separately checked by SST and the FPGA result.
        tails = []
        for partition in range(partitions):
            updates, slots = struct.unpack("<2I", stream.read(8))
            bounds = _words(stream, vertices * 2)
            occupied = [v for v in range(vertices) if bounds[2 * v + 1] > bounds[2 * v]]
            last = occupied[-1] if occupied else -1
            stream.seek(slots * 4, 1)
            tails.append({"partition": partition, "slots": slots, "physical_updates": updates,
                          "last_occupied_source": last, "trailing_empty_rows": vertices - last - 1,
                          "prefetched_row_count": min(vertices, ((last + 8) // 8) * 8)})
        if stream.tell() != fixture.stat().st_size:
            raise ValueError("fixture size does not match row-tail inventory")
    if sorted(mapping) != list(range(vertices)) or len(set(active)) != len(active):
        raise ValueError("invalid fixture mapping or duplicate active vertex")
    adjacency = [[] for _ in range(vertices)]
    update_sources = set()
    with graph.open() as stream:
        graph_vertices, edge_count, update_count = map(int, stream.readline().split())
        if graph_vertices != vertices or not 0 <= source < vertices:
            raise ValueError("old-state audit graph/source differs")
        for _ in range(edge_count):
            src, dst, weight = map(int, stream.readline().split())
            if not (0 <= src < vertices and 0 <= dst < vertices and 1 <= weight <= 4095):
                raise ValueError("invalid old-state audit edge")
            adjacency[src].append((dst, weight))
        for _ in range(update_count):
            src, dst, weight, kind = map(int, stream.readline().split())
            if kind != 1 or not (0 <= src < vertices and 0 <= dst < vertices and 1 <= weight <= 4095):
                raise ValueError("audit expects resident insertion/decrease updates")
            update_sources.add(src)
        if stream.read().strip():
            raise ValueError("trailing graph data")
    expected, old_rounds = synchronous_sssp(adjacency, source)
    mismatches = sum(old[internal] != expected[external] for internal, external in enumerate(mapping))
    actual_sources = {mapping[internal] for internal in active}
    if mismatches or actual_sources != update_sources:
        raise ValueError("resident old state or update-source active set differs from hardware host semantics")
    return {"status": "PASS", "old_state_mismatches": mismatches,
            "old_graph_oracle_rounds": old_rounds, "old_graph_oracle_limit": 256,
            "active_source_count": len(update_sources), "cache_segments": cache,
            "expected_new_rounds": rounds, "tails": tails,
            "claim": "independent_synchronous_old_state_and_active_semantics_not_FPGA_internal_counter_measurement"}
