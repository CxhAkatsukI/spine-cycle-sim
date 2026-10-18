"""Compare fixed cache-service increments, not mock-memory and FPGA total time."""

import argparse
import hashlib
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .analysis import transactions


def compare(model, rtl_text):
    if (model.get("schema") != 1 or
            model.get("complete_state_and_traffic_checked") is not True or
            model.get("reverse_registration_checked") is not True or
            model.get("input_fifo_depth") != 2 or
            model.get("memory_backend") != "MockMemoryBackend"):
        raise ValueError("unexpected cache model control or missing conservation checks")
    rows = model.get("rows", [])
    stimuli = ((0, False), (16, False), (64, False), (4096, False),
               (65536, False), (4096, True))
    if not isinstance(rows, list) or len(rows) != len(stimuli):
        raise ValueError("incomplete cache model control scope")
    for index, (row, (updates, conflict)) in enumerate(zip(rows, stimuli)):
        if (not isinstance(row, dict) or row.get("index") != index or
                row.get("updates") != updates or row.get("conflict") is not conflict):
            raise ValueError("cache model stimulus/order mismatch")
        for field in ("index", "updates", "cycles", "load_complete", "store_issued",
                      "read_bytes", "write_bytes", "lane_queue_stalls"):
            if type(row.get(field)) is not int or row[field] < 0:
                raise ValueError("invalid cache model integer observation")
        if not 0 < row["load_complete"] < row["store_issued"] < row["cycles"]:
            raise ValueError("cache model phase ordering mismatch")
        if row["read_bytes"] != 8388608 or row["write_bytes"] != 8388608:
            raise ValueError("cache model omitted full preload/writeback")
    rtl = transactions(rtl_text, full=True, full_extended=True)
    if any(row["latency"] <= 0 for row in rtl):
        raise ValueError("invalid RTL transaction latency")

    def difference(left, right, divisor):
        predicted = (rows[right]["cycles"] - rows[left]["cycles"]) / divisor
        measured = (rtl[right]["latency"] - rtl[left]["latency"]) / divisor
        return {"model_cycles_per_update": predicted, "RTL_cycles_per_update": measured,
                "absolute_difference_cycles_per_update": abs(predicted - measured)}

    return {"status": "CACHE_SERVICE_CONTROL_ANALYZED_NOT_TOTAL_TIME_CALIBRATION",
            "rows": [{**row, "RTL_latency_cycles": reference["latency"]}
                     for row, reference in zip(rows, rtl)],
            "balanced_4096_to_65536_increment": difference(3, 4, 65536 - 4096),
            "same_count_single_bank_minus_balanced": difference(3, 5, 4096),
            "total_latency_comparable": False,
            "memory_boundary": "mock AXI/backend is not the XSim AXI memory model",
            "input_boundary": "model closes after committed last packet; RTL consumes END_EDGE",
            "hardware_timing_admitted": False, "integrated_g_admitted": False,
            "production_baseline_admitted": False, "publication_match_admitted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("model", "rtl_report", "output"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    model_bytes, rtl_bytes = args.model.read_bytes(), args.rtl_report.read_bytes()
    result = compare(json.loads(model_bytes), rtl_bytes.decode("ascii"))
    result["inputs"] = [{"path": str(path.resolve()), "sha256": hashlib.sha256(data).hexdigest()}
                        for path, data in ((args.model, model_bytes), (args.rtl_report, rtl_bytes))]
    atomic_write_json(args.output / "results.json", result)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
