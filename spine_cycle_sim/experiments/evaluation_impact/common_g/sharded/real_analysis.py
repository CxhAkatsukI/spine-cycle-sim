"""Check the complete real-input matrix without fitting its timing results."""

from .preparation import ARMS, LATENCIES
from .real_inputs import SCENARIOS, SELECTION


def analyze(rows, contract, *, names=None):
    names = ({f"{label}-{scenario}-{size}" for label, _ in SELECTION for scenario, size in SCENARIOS}
             if names is None else set(names))
    expected = {(case, latency, arm) for latency in LATENCIES for case in names for arm in ARMS}
    identities = [(r["case"], r["latency"], r["arm"]) for r in rows]
    declared = [(r["case"], r["latency"], r["arm"]) for r in contract["matrix"]]
    if (set(contract["cases"]) != names or len(identities) != len(expected) or
            set(identities) != expected or len(declared) != len(expected) or set(declared) != expected):
        raise ValueError("missing, duplicate or undeclared real-G observation")
    for row in rows:
        observation = row["observation"]
        if any(observation[key] != row[key] for key in ("case", "latency", "arm")):
            raise ValueError("real-G execution identity differs")
        case = contract["cases"][row["case"]]
        work = ("vertices", "live_edges", "physical_updates", "binary_probes", "multi_segment_updates")
        if any(observation[key] != case[key] for key in work):
            raise ValueError("real-G input or operation count differs")
        physical, probes = case["physical_updates"], case["binary_probes"]
        pma = 2 * 131072 * 64
        required = {"total_shards": 1, "updated_shards": 1, "cache_updates": physical,
            "ddr_updates": 0, "row_reads": physical, "pma_read_bytes": pma,
            "pma_write_bytes": pma, "read_bytes": pma + physical * 16 + probes * 8,
            "write_bytes": pma, "full_payload_pass": True, "timing_kind": "declared_prediction"}
        if (not physical or not probes or not case["multi_segment_updates"] or
                any(observation[key] != value for key, value in required.items()) or observation["cycles"] <= 0):
            raise ValueError("real-G state, cache cost, search or byte ledger differs")
        digest = row["state_sha256"]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("missing complete real-G canonical state digest")
    comparisons = []
    for case in contract["cases"]:
        if len({r["state_sha256"] for r in rows if r["case"] == case}) != 1:
            raise ValueError("complete real-G PMA state differs across arms or memory latencies")
        for latency in LATENCIES:
            group = [r for r in rows if r["case"] == case and r["latency"] == latency]
            cycles = {r["arm"]: r["observation"]["cycles"] for r in group}
            original, four, runtime = (cycles[arm] for arm in ARMS)
            comparisons.append({"case": case, "latency": latency, "cycles": cycles,
                "four_bank_over_original": four / original, "runtime_over_original": runtime / original,
                "runtime_over_four_bank": runtime / four})
    return {"prediction_rows": len(rows), "comparisons": comparisons,
        "four_bank_ten_percent_target_met": all(0.9 <= r["four_bank_over_original"] <= 1.1 for r in comparisons),
        "runtime_ten_percent_diagnostic_met": all(0.9 <= r["runtime_over_original"] <= 1.1 for r in comparisons),
        "full_payload_and_traffic_pass": True, "production_baseline_admitted": False,
        "hardware_timing_admitted": False, "publication_match_admitted": False,
        "host_inclusive_timing_admitted": False}
