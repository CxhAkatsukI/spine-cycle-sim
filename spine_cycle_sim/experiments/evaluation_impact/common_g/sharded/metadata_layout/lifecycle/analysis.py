"""Require complete resident batch states, work, resources and controls."""

from .preparation import ARMS, CASES, LATENCIES, contract
from .resources import check_resources


def identity(row):
    return tuple(row[key] for key in ("case", "latency", "arm"))


def check_row(row):
    value = row["observation"]
    if (identity(value) != identity(row) or value["vertices"] != 161
            or value["total_shards"] != 3 or value["timing_kind"] != "declared_prediction"):
        raise ValueError("resident input identity differs")
    if len(value["batches"]) != 3 or len(row["batch_states"]) != 3:
        raise ValueError("resident batch sequence is incomplete")
    for batch, count in zip(value["batches"], CASES[row["case"]]):
        touched = count // 64
        pma = touched * 2 * 131072 * 64
        required = {"physical_updates": count, "updated_shards": touched,
            "cache_updates": count, "ddr_updates": 0, "row_reads": count,
            "binary_probes": count, "multi_segment_updates": count,
            "pma_read_bytes": pma, "pma_write_bytes": pma, "read_bytes": pma + count * 24,
            "write_bytes": pma, "full_payload_pass": True}
        if (any(batch[key] != expected for key, expected in required.items())
                or not isinstance(batch["cycles"], int) or batch["cycles"] < 0
                or (batch["cycles"] == 0) != (count == 0)):
            raise ValueError("resident batch work, complete cache or traffic differs")
    digests = [item["sha256"] for item in row["batch_states"]]
    if (digests[0] != digests[1] or digests[1] == digests[2]
            or digests[2] != row["state_sha256"]
            or any(len(d) != 64 or set(d) - set("0123456789abcdef") for d in digests)):
        raise ValueError("resident empty/reactivated canonical state differs")
    if row["arm"] == ARMS[0]:
        if value["resources"] is not None:
            raise ValueError("original resource scope changed")
    else:
        check_resources(value["resources"], row["arm"] == ARMS[2])


def analyze(rows):
    if (len(rows) != 12
            or {identity(r) for r in rows} != {identity(r) for r in contract()["matrix"]}):
        raise ValueError("resident matrix is incomplete or undeclared")
    for row in rows:
        check_row(row)
    comparisons = []
    for latency in LATENCIES:
        for case in CASES:
            group = {r["arm"]: r for r in rows if r["case"] == case and r["latency"] == latency}
            shared = group[ARMS[1]]["observation"]["resources"]["regions"]
            copies = group[ARMS[2]]["observation"]["resources"]["regions"]
            if shared != [r for r in copies if "-cu" not in r["name"]]:
                raise ValueError("resident original allocations changed between arms")
            for batch in range(3):
                if len({r["batch_states"][batch]["sha256"] for r in group.values()}) != 1:
                    raise ValueError("resident complete state differs between arms")
                times = {arm: r["observation"]["batches"][batch]["cycles"] for arm, r in group.items()}
                comparisons.append({"case": case, "latency": latency, "batch": batch, "cycles": times,
                    "shared_over_original": times[ARMS[1]] / times[ARMS[0]] if times[ARMS[0]] else None,
                    "copies_over_original": times[ARMS[2]] / times[ARMS[0]] if times[ARMS[0]] else None})
    return {"prediction_rows": len(rows), "batch_observations": 36, "comparisons": comparisons,
        "four_bank_ten_percent_target_met": None,
        "runtime_ten_percent_diagnostic_met": all(r["shared_over_original"] is None
            or 0.9 <= r["shared_over_original"] <= 1.1 for r in comparisons),
        "copies_ten_percent_diagnostic_met": all(r["copies_over_original"] is None
            or 0.9 <= r["copies_over_original"] <= 1.1 for r in comparisons),
        "lifecycle_payload_and_traffic_pass": True, "production_baseline_admitted": False,
        "hardware_timing_admitted": False, "publication_match_admitted": False,
        "host_inclusive_timing_admitted": False, "production_layout_changed": False}
