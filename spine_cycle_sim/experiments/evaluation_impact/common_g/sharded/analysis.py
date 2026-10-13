"""Validate every declared observation before interpreting predicted timing."""

from .preparation import ARMS, CASES, LATENCIES, matrix


def analyze(rows):
    identities = [(r["case"], r["latency"], r["arm"]) for r in rows]
    expected = {(r["case"], r["latency"], r["arm"]) for r in matrix()}
    if len(identities) != len(expected) or set(identities) != expected:
        raise ValueError("missing, duplicate or undeclared sharded-G observation")
    for row in rows:
        observation = row["observation"]
        if any(observation[key] != row[key] for key in ("case", "arm", "latency")):
            raise ValueError("sharded-G execution identity differs")
        case = CASES[row["case"]]
        if any(observation[key] != value for key, value in case.items()):
            raise ValueError("sharded-G input or operation count differs")
        physical = 2 * case["logical_updates"]
        pma = case["updated_shards"] * 2 * 131072 * 64 + case["ddr_updates"] * 64
        required = {"physical_updates": physical, "live_edges": case["vertices"] * case["total_shards"],
            "cache_updates": physical - case["ddr_updates"], "row_reads": physical, "binary_probes": 0,
            "pma_read_bytes": pma, "pma_write_bytes": pma, "read_bytes": pma + physical * 16,
            "write_bytes": pma, "full_payload_pass": True, "timing_kind": "declared_prediction"}
        if any(observation[key] != value for key, value in required.items()):
            raise ValueError("sharded-G state, cache cost or conserved byte ledger differs")
        if (observation["cycles"] == 0) != (physical == 0):
            raise ValueError("nonempty batch has zero timing or empty batch was launched")
        digest = row["state_sha256"]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("missing complete canonical state digest")
    comparisons = []
    for latency in LATENCIES:
        for name in CASES:
            group = [r for r in rows if r["case"] == name and r["latency"] == latency]
            if len({r["state_sha256"] for r in group}) != 1:
                raise ValueError("complete canonical PMA state differs across arms")
            values = {r["arm"]: r["observation"]["cycles"] for r in group}
            original = values[ARMS[0]]
            four = values[ARMS[1]]
            runtime = values[ARMS[2]]
            comparisons.append({"case": name, "latency": latency, "cycles": values,
                "four_bank_over_original": four / original if original else None,
                "runtime_over_original": runtime / original if original else None,
                "runtime_over_four_bank": runtime / four if four else None})
    numeric = [r for r in comparisons if r["four_bank_over_original"] is not None]
    return {"comparisons": comparisons, "prediction_rows": len(rows),
        "four_bank_ten_percent_target_met": all(0.9 <= r["four_bank_over_original"] <= 1.1 for r in numeric),
        "runtime_ten_percent_diagnostic_met": all(0.9 <= r["runtime_over_original"] <= 1.1 for r in numeric),
        "full_payload_and_traffic_pass": True, "production_baseline_admitted": False,
        "hardware_timing_admitted": False, "publication_match_admitted": False,
        "host_inclusive_timing_admitted": False}
