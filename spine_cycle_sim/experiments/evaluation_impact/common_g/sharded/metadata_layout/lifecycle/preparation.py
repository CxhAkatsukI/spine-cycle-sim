"""Declare synthetic lifecycle coverage before executing any prediction."""

ARMS = ("original-prepared-shards", "candidate-runtime-23", "runtime-both-copies")
CASES = {"staggered": (128, 0, 192), "all-active": (192, 0, 192)}
LATENCIES = (64, 128)
STATUS = "RESIDENT_METADATA_LIFECYCLE_CHECKED_NOT_BASELINE_ADMISSION"


def contract():
    return {"schema_version": 1, "matrix": [
        {"case": case, "latency": latency, "arm": arm}
        for latency in LATENCIES for case in CASES for arm in ARMS],
        "cases": {case: list(counts) for case, counts in CASES.items()}, "batch_count": 3,
        "input": "deterministic synthetic 161 vertices, three 64-destination shards; no ID reorder",
        "initial": "sources 0..31 each have 24 weight-3 edges to local destinations 0..23 in every shard",
        "batches": "weight-3 delete/weight-1 insert on first two or all shards; empty; delete current weight/insert weight-5 on all shards",
        "reservation": "one immutable union reservation for all declared batches; full 262144-segment padding per shard",
        "runtime": "fixed plan reserves maximum per-shard update buffer across the sequence; shared/both-copy physical memory retained",
        "request_identity": "unique per batch/shard for permanent backend traffic registration; previous masters drained and destroyed, no additional concurrent ports",
        "original": "independent source16 model on each prepared shard; current logical state supplied untimed each batch",
        "clock_mhz": 200, "cache_segments_per_half": 131072,
        "boundary": "resident batch through acknowledged final writes; no artificial gaps between shards",
        "excluded": ["allocation/upload", "metadata replication wall time", "reservation/reorder", "DMA", "host orchestration", "R/seed"],
        "replica_channels": [3, 9, 15, 20], "bank_capacity_bytes": 512 * 1024**2,
        "repetitions": 1, "scope": "lifecycle correctness, not broad performance or FPGA admission"}
