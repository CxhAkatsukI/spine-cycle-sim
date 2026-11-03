"""Count resident PMA slots for the no-update, unit-weight R board control."""

from array import array
import sys


def csr_words(path):
    words = array("I")
    words.frombytes(path.read_bytes())
    if sys.byteorder != "little":
        words.byteswap()
    return words


def slot_counts(offsets, destinations, partition_vertices=65536):
    vertices = len(offsets) - 1
    if (vertices < 1 or offsets[0] != 0 or offsets[-1] != len(destinations)
            or any(a > b for a, b in zip(offsets, offsets[1:]))):
        raise ValueError("invalid resident CSR offsets")
    # With no updates, nonempty sources have density zero and empty sources
    # have density -1. Both retain increasing external ID within each group.
    nonempty = [v for v in range(vertices) if offsets[v] < offsets[v + 1]]
    order = nonempty + [v for v in range(vertices) if offsets[v] == offsets[v + 1]]
    partition = array("I", [0]) * vertices
    for i, external in enumerate(order):
        partition[external] = i // partition_vertices
    shards = (vertices + partition_vertices - 1) // partition_vertices
    slots = [0] * shards
    edges = [0] * shards
    for source in nonempty:
        counts = {}
        seen = set()
        for destination in destinations[offsets[source]:offsets[source + 1]]:
            if not 0 <= destination < vertices or destination in seen:
                raise ValueError("resident R control requires in-range unique edges")
            seen.add(destination)
            shard = partition[destination]
            counts[shard] = counts.get(shard, 0) + 1
        for shard, count in counts.items():
            edges[shard] += count
            slots[shard] += ((count + 15) // 16) * 16
        if source == order[0]:
            for shard in range(shards):
                if shard not in counts:
                    slots[shard] += 16
    if not nonempty:
        slots = [16] * shards
    return edges, slots


def replay_layout(directory, expected):
    offsets = csr_words(directory / "csr_offsets.u32le")
    destinations = csr_words(directory / "csr_destinations.u32le")
    edges, slots = slot_counts(offsets, destinations)
    if (len(offsets) - 1, len(slots), sum(edges), sum(slots)) != (
            expected["vertices"], expected["shards"], expected["edges"], expected["pma_slots"]):
        raise ValueError("CSR and candidate configuration disagree")
    return {
        "shard_logical_edges": edges, "shard_pma_slots": slots,
        "worker_pma_slots": [sum(slots[worker::4]) for worker in range(4)],
    }
