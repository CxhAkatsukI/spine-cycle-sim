"""Accept only complete CPU preparation, never hardware timing or admission."""

from .preparation import ALGORITHMS, DATASETS, PREFIXES

PASS = "FULLGRAPH_HOST_PREPARATION_PASS_NOT_BOARD_OR_PERFORMANCE"


def fields(line):
    tokens = line.split()
    pairs = [token.split("=", 1) for token in tokens[1:]]
    if any(len(pair) != 2 for pair in pairs) or len({pair[0] for pair in pairs}) != len(pairs):
        raise ValueError("unique key=value fields required")
    return dict(pairs)


def analyze(row, stdout, stderr):
    prefix = PREFIXES[row["algorithm"]]
    lines = stdout.splitlines()
    if stderr.strip() or len(lines) < 2 or not lines[0].startswith(prefix + "_INPUT ") or not lines[-1].startswith(prefix + "_PREP "):
        raise ValueError("complete, diagnostic-free prepare-only output required")
    initial, prepared = fields(lines[0]), fields(lines[-1])
    expected = {"vertices": row["vertices"], "static_edges": row["initial_edges"],
                "logical_updates": row["updates"], "oracle_converged": 1}
    if any(int(initial[key]) != value for key, value in expected.items()):
        raise ValueError("input dimensions or CPU convergence disagree")
    partitions = (row["vertices"] + 65535) // 65536
    if (prepared["status"] != "PASS" or
            prepared["pma_destination_abi"] != "local_dst19" or
            prepared["k4_frontends"] != "4" or prepared["shared_regraph_downstream"] != "1" or
            prepared["conversion_cost"] != "absent" or
            any(int(record["vertices"]) != row["vertices"] or int(record["destination_partitions"]) != partitions
                for record in (initial, prepared)) or
            int(initial["pma_slots_total"]) != int(prepared["pma_slots_total"]) or
            not 0 < int(prepared["pma_slots_max_shard"]) <= int(prepared["pma_slots_total"])):
        raise ValueError("partition, PMA or shared K4 contract disagreement")
    if row["algorithm"] != "residual_pagerank":
        if (initial["resident_state"] != "old_graph_converged" or prepared["oracle_converged"] != "1" or
                int(prepared["hbm_graph_channels"]) != 23 or
                not 0 < int(prepared["hbm_max_channel_bytes"]) <= 512 * 1024**2 or
                int(initial["source_external"]) != row["source"]):
            raise ValueError("resident state, source or HBM graph capacity disagreement")
    seen, updates = set(), 0
    for line in lines[1:-1]:
        if not line.startswith("GRASU_SHARDED_UPDATE_LAYOUT "):
            raise ValueError("unexpected output; hardware execution is forbidden")
        layout = fields(line)
        shard = int(layout["shard"])
        if shard in seen or not 0 <= shard < partitions or int(layout["destination_base"]) != shard * 65536:
            raise ValueError("invalid or repeated destination shard")
        seen.add(shard)
        count = int(layout["updates"])
        hot, cold = int(layout["cache_updates"]), int(layout["ddr_updates"])
        if count <= 0 or min(hot, cold) < 0 or hot + cold != count:
            raise ValueError("hot/cold physical update conservation failed")
        updates += count
    if updates != int(initial["physical_updates"]) or updates != row["updates"]:
        raise ValueError("physical update count disagreement")
    return {"dataset": row["dataset"], "algorithm": row["algorithm"], "status": "PASS",
            "input": initial, "prepared": prepared, "layout_shards": len(seen),
            "claim": "CPU_oracle_and_graph_HBM_layout_only_not_board_timing"}


def decision(cases):
    keys = {(row["dataset"], row["algorithm"]) for row in cases}
    complete = keys == {(d, a) for d in DATASETS for a in ALGORITHMS}
    return PASS if complete and len(cases) == 24 and all(row["status"] == "PASS" for row in cases) else "FAILED_RETAINED"
