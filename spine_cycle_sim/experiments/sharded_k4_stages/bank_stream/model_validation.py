"""Independent bank-stream beat inventory, full-state and topology admission."""

from pathlib import Path
import re

from .model_contract import PROFILE_ID


def require_result(result: dict, geometry: dict, diagnostic: str) -> dict:
    if (result.get("profile_id") != PROFILE_ID
            or result.get("boundary") != "resident_compute_no_host_launch_gaps"
            or result.get("evidence") != "simulator_prediction_not_hardware_timing_admission"
            or any(result.get(key) is not True for key in ("success", "done", "replicas_equal", "ledger_closed"))
            or result.get("failed") is not False or result.get("mismatches") != 0):
        raise ValueError("bank-stream full-state correctness and ledger gate failed")
    if any(result.get(key) != geometry[key] for key in ("vertices", "partitions", "pma_slots", "live_edges_per_round")):
        raise ValueError("bank-stream fixture geometry differs")
    rounds = geometry["rounds"]
    if len(result["rounds"]) != rounds or result["expected_rounds"] != rounds:
        raise ValueError("bank-stream convergence differs")
    if ("source-services=2 physical-masters=7" not in diagnostic
            or len(set(re.findall(r"master=(\S+)", diagnostic))) != 7
            or any(not re.search(rf"worker={w}\b[^\n]*source-service=source{w % 2}\b", diagnostic)
                   for w in range(4))):
        raise ValueError("bank-stream physical source topology differs")
    c = result["counters"]
    padded = geometry["partitions"] * 65536
    rows = sum((min(geometry["vertices"], ((t["visited_rows"] + 1023) // 1024) * 1024) + 7) // 8
               if t["slots"] else 0 for t in geometry["tails"])
    expected = {"extent_reads": geometry["partitions"] * rounds, "row_reads": rows * rounds,
                "segment_reads": geometry["pma_slots"] // 16 * rounds,
                "packets": geometry["pma_slots"] // 8 * rounds,
                "live_edges": geometry["live_edges_per_round"] * rounds,
                "dummy_edges": (geometry["pma_slots"] - geometry["live_edges_per_round"]) * rounds,
                "source_lines": c["source_blocks"] * 256,
                "source_terminators": geometry["partitions"] * rounds,
                "gather_rows": padded // 2 * rounds, "mux_rows": padded // 2 * rounds,
                "apply_reads": padded // 16 * rounds, "apply_writes": padded // 16 * rounds,
                "source_writes": padded // 8 * rounds, "status_writes": rounds}
    reads = sum(c[key] for key in ("extent_reads", "row_reads", "segment_reads", "source_lines", "apply_reads"))
    writes = sum(c[key] for key in ("apply_writes", "source_writes", "status_writes"))
    expected.update(axi_beats=reads + writes, axi_completed_beats=reads + writes)
    changed = [key for key, value in expected.items() if c.get(key) != value]
    # Burst parents are not beats. Parent conservation is checked without
    # assuming the obsolete one-parent-per-directory-row/segment reader.
    if (changed or result["backend_reads"] != reads or result["backend_writes"] != writes
            or not 0 < c["axi_requests"] == c["axi_completions"] <= c["axi_beats"]):
        raise ValueError(f"bank-stream independent traffic conservation failed: {changed}")
    arbitration = result["arbitration"]
    if (arbitration["ledger_closed"] is not True or arbitration["pending_intents"] or arbitration["pending_grants"]
            or any(arbitration[key] != c["axi_beats"] for key in ("unique_intents", "grants", "consumed_grants"))):
        raise ValueError("bank-stream arbitration did not drain")
    cycles = c["end_cycle"] - c["start_cycle"]
    if cycles <= 0 or cycles != result["observed_cycles"]:
        raise ValueError("bank-stream cycle window differs")
    return {"status": "FUNCTIONAL_AND_TRAFFIC_PASS_NOT_HARDWARE_TIMING", "predicted_cycles": cycles,
            "directory_beats": c["extent_reads"] + c["row_reads"], "parents": c["axi_requests"],
            "beats": c["axi_beats"], "physical_masters": 7, "hardware_timing_admitted": False}


def require_values(actual: Path, expected: Path) -> None:
    if actual.read_bytes() != expected.read_bytes():
        raise ValueError("bank-stream full external output differs from the independent oracle")
