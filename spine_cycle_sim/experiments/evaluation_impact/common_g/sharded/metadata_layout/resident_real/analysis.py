"""Admit only complete resident input, state, traffic and resource diagnostics."""

from ..lifecycle.analysis import identity
from ..lifecycle.preparation import ARMS, LATENCIES
from ..lifecycle.resources import check_resources


def check_row(row, expected):
    value = row["observation"]
    if (identity(value) != identity(row) or value["vertices"] != expected["vertices"]
            or value["total_shards"] != expected["total_shards"]
            or value["timing_kind"] != "declared_prediction"):
        raise ValueError("resident chronological identity differs")
    if len(value["batches"]) != 3 or len(row["batch_states"]) != 3:
        raise ValueError("resident chronological sequence is incomplete")
    for batch, fact in zip(value["batches"], expected["batches"]):
        count, probes = fact["physical_updates"], fact["binary_probes"]
        pma = fact["updated_shards"] * 2 * 131072 * 64
        required = {"physical_updates": count, "updated_shards": fact["updated_shards"],
            "cache_updates": count, "ddr_updates": 0, "row_reads": count,
            "binary_probes": probes, "multi_segment_updates": fact["multi_segment_updates"],
            "pma_read_bytes": pma, "pma_write_bytes": pma,
            "read_bytes": pma + count * 16 + probes * 8, "write_bytes": pma, "full_payload_pass": True}
        if (any(batch[key] != v for key, v in required.items())
                or type(batch["cycles"]) is not int or batch["cycles"] < 0
                or (batch["cycles"] == 0) != (count == 0)):
            raise ValueError("resident chronological work or traffic differs")
    digests = [item["sha256"] for item in row["batch_states"]]
    if (digests[0] != digests[1] or digests[1] == digests[2] or digests[2] != row["state_sha256"]
            or any(len(d) != 64 or set(d) - set("0123456789abcdef") for d in digests)):
        raise ValueError("resident chronological empty/reactivated state differs")
    if row["arm"] == ARMS[0]:
        if value["resources"] is not None:
            raise ValueError("original resource scope changed")
    else:
        check_resources(value["resources"], row["arm"] == ARMS[2], shards=expected["total_shards"])
        for region in value["resources"]["regions"]:
            if region["name"].startswith(("row", "binary")):
                size = (expected["vertices"] + 1) * 8 if region["name"].startswith("row") else 262144 * 8
                if region["logical_bytes"] != size:
                    raise ValueError("resident chronological table geometry differs")


def comparison(case, latency, batch, times):
    reference = times[ARMS[0]]
    return {"case": case, "latency": latency, "batch": batch, "cycles": times,
            "shared_over_original": times[ARMS[1]] / reference if reference else None,
            "copies_over_original": times[ARMS[2]] / reference if reference else None}


def within_ten(rows, key):
    return all(row[key] is None or 0.9 <= row[key] <= 1.1 for row in rows)


def analyze(rows, *, contract):
    if (len(rows) != 18 or len(contract["matrix"]) != 18
            or {identity(r) for r in rows} != {identity(r) for r in contract["matrix"]}):
        raise ValueError("resident chronological matrix is incomplete or undeclared")
    for row in rows:
        check_row(row, contract["cases"][row["case"]])
    comparisons, totals = [], []
    for latency in LATENCIES:
        for case in contract["cases"]:
            group = {r["arm"]: r for r in rows if r["case"] == case and r["latency"] == latency}
            shared = group[ARMS[1]]["observation"]["resources"]["regions"]
            copies = group[ARMS[2]]["observation"]["resources"]["regions"]
            if shared != [r for r in copies if "-cu" not in r["name"]]:
                raise ValueError("resident chronological original allocations changed")
            for batch in range(3):
                if len({r["batch_states"][batch]["sha256"] for r in group.values()}) != 1:
                    raise ValueError("resident chronological complete states differ between arms")
                times = {arm: r["observation"]["batches"][batch]["cycles"] for arm, r in group.items()}
                comparisons.append(comparison(case, latency, batch, times))
            totals.append(comparison(case, latency, "sequence", {
                arm: sum(b["cycles"] for b in r["observation"]["batches"]) for arm, r in group.items()}))
    return {"prediction_rows": len(rows), "batch_observations": len(rows) * 3,
        "comparisons": comparisons, "sequence_comparisons": totals,
        "four_bank_ten_percent_target_met": None,
        "runtime_ten_percent_diagnostic_met": within_ten(comparisons + totals, "shared_over_original"),
        "copies_ten_percent_diagnostic_met": within_ten(comparisons + totals, "copies_over_original"),
        "lifecycle_payload_and_traffic_pass": True, "production_baseline_admitted": False,
        "hardware_timing_admitted": False, "publication_match_admitted": False,
        "host_inclusive_timing_admitted": False, "production_layout_changed": False}
