"""Predeclared deterministic graph and complete-batch comparison matrix."""

CASES = {
    "one-shard-64": {"vertices": 131105, "total_shards": 3, "updated_shards": 1,
                     "logical_updates": 64, "ddr_updates": 0},
    "three-shard-4096": {"vertices": 131105, "total_shards": 3, "updated_shards": 3,
                         "logical_updates": 4096, "ddr_updates": 0},
    "five-shard-mixed-512": {"vertices": 262177, "total_shards": 5, "updated_shards": 5,
                             "logical_updates": 512, "ddr_updates": 220},
    "empty": {"vertices": 131105, "total_shards": 3, "updated_shards": 0,
              "logical_updates": 0, "ddr_updates": 0},
}
ARMS = ("original-prepared-shards", "candidate-four-banks", "candidate-runtime-23")
LATENCIES = (64, 128)
STATUS = "SHARDED_G_PREDICTIONS_CHECKED_NOT_BASELINE_ADMISSION"


def matrix():
    return [{"case": case, "latency": latency, "arm": arm}
            for latency in LATENCIES for case in CASES for arm in ARMS]


def input_contract():
    return {"schema_version": 1, "cases": CASES, "matrix": matrix(),
        "graph_kind": "synthetic deterministic prepared destination shards; no vertex reorder",
        "initial": "one weight-3 edge per source per destination shard; dst=base+(17*src+shard)%shard_size",
        "updates": "exact weight-3 delete then weight-1 insert; unique source/shard pairs",
        "geometry": "one live 16-slot segment per source/shard; empty last-row tail pads each shard to at least 262144 segments; local destination, global source",
        "cache_segments_per_half": 131072, "clock_mhz": 200,
        "memory": {"bank_credits": 32, "accepts_per_bank_per_cycle": 1, "response_depth": 64},
        "candidate": {"contexts_per_cu": 64, "metadata_credits_per_cu": 32,
                      "finite_search": True, "complete_cache": True},
        "original": "independent source16 finite model, default cache timing; sequential prepared shards",
        "resources": "original and co-located candidate: four banks; runtime candidate: graph regions across 23 of 32 banks",
        "boundary": "resident prepared batch; all updated shards through acknowledged final writes; empty skips launch",
        "excluded": ["reservation/reorder", "PMA allocation/upload", "DMA", "host launch/wait/relaunch", "R/seed"],
        "repetitions": 1, "repeat_scope": "deterministic simulator cycles, not CPU throughput"}
