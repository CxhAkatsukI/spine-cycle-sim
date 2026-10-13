"""Keep observed registrations, port configuration and declarations distinct."""

import json


def analyze(stdout):
    groups = {key: [] for key in ("RESOURCE_PORT", "RESOURCE_A4", "RESOURCE_K4")}
    for line in stdout.splitlines():
        tag, _, body = line.partition(" ")
        if tag not in groups:
            raise ValueError("undeclared resource observation")
        groups[tag].append(json.loads(body))
    ports, a4_rows, k4 = (groups[key] for key in groups)
    if len(ports) != 13 or len(a4_rows) != 1 or len(k4) != 2:
        raise ValueError("incomplete resource audit")
    a4 = a4_rows[0]
    roles = {(row["role"], row["index"]) for row in ports}
    expected = {(role, i) for role in ("edge", "source", "write") for i in range(4)} | {("apply_read", 0)}
    ids = {row["initiator"] for row in ports}
    banks = {row["channel"] for row in ports}
    source_banks = {row["channel"] for row in ports if row["role"] == "source"}
    if (roles != expected or len(ids) != 13 or len(a4["registered_ids"]) != 13
            or a4["distinct_masters"] != 13 or ids != set(a4["registered_ids"])
            or banks != set(a4["physical_banks"]) or len(banks) != 9
            or source_banks != set(a4["source_banks"]) or len(source_banks) != 4):
        raise ValueError("A4 endpoint/master/bank accounting disagrees")
    if any(row["parent_credits"] != 2 or row["burst_credits"] != 16
           or row["data_width_bytes"] != 64 or row["request_fifo"] != 8
           or row["response_fifo"] != 8 or row["independent_read_write"] for row in ports):
        raise ValueError("A4 port configuration differs from preceding control")
    if {row["arm"] for row in k4} != {"cross_row", "candidate"}:
        raise ValueError("duplicate or missing K4 arm")
    for row in [a4] + k4:
        if row["clock_period_fs"] != 6_666_667 or row["constructor_only"] is not True:
            raise ValueError("audit clock/boundary differs")
    for row in k4:
        if (row["registered_ids"] != list(range(600, 609))
                or row["declared_parent_credits"] != 16 or row["declared_burst_credits"] != 16
                or row["declared_apply_window"] != 16 or row["declared_source_banks"] != [23, 24]
                or row["declared_primary_bank"] != 30 or row["declared_graph_bank_budget"] != 23
                or row["declared_shared_capacity"] != 32):
            raise ValueError("K4 registrations or declared resource budget differs")
        candidate = row["arm"] == "candidate"
        if (row["declared_directory_rows"] != (1024 if candidate else 8)
                or row["declared_bank_fifo_lines"] != (256 if candidate else 0)):
            raise ValueError("K4 adapter buffer declaration differs")
        regions = row["regions"]
        if (not regions or {r["shard"] for r in regions} != set(range(4))
                or any(not 0 <= r["channel"] < 23 or r["allocated_bytes"] <= 0 for r in regions)):
            raise ValueError("K4 four-shard placement is missing or outside graph budget")
    return {"status": "RESOURCE_ACCOUNTING_VERIFIED_NOT_PERFORMANCE_ADMISSION",
            "a4": a4, "a4_ports": ports, "k4": k4,
            "a4_master_count": 13, "a4_physical_bank_count": 9, "k4_master_count": 9,
            "k4_config_visibility": "declared input, not introspected private AxiMaster configs",
            "strict_resource_match_admitted": False, "performance_admitted": False,
            "publication_match_admitted": False, "hardware_timing_admitted": False}
