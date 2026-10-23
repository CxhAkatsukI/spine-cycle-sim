"""Partial CPU preparation measurements, never a replacement for host-inclusive E2E."""

import json
import math
from pathlib import Path
from statistics import median

from ...original_regraph_inputs.analysis import records
from .analysis import summarize as summarize_device

REPETITIONS = 7
STATUS = "COMPLETE_PARTIAL_HOST_PREPARATION_MEASUREMENT"


def summarize(rows, warm_rows):
    device = summarize_device(warm_rows)
    if len(rows) != 2 * REPETITIONS:
        raise ValueError("all fourteen host executions required")
    measured = {}
    for workload in ("smoke", "amazon"):
        group = [r for r in rows if r["workload"] == workload]
        if len(group) != REPETITIONS or {r["repeat"] for r in group} != set(range(REPETITIONS)):
            raise ValueError("seven distinct process repetitions required")
        common = [r["input"] for r in warm_rows if r["workload"] == workload]
        identity = common[0]
        if any(row != identity for row in common):
            raise ValueError("device input identity differs")
        for row in group:
            result = row["result"]
            if (result["vertices"] != identity["vertices"] or result["updates"] != identity["updates"] or
                    result["self_test"] is not True or result["partition_vertices"] != 65536 or
                    result["iterations_per_sample"] != 1000 or result["warmup_blocks"] != 20 or
                    result["source_seed_count"] != len({u[0] for u in identity["updates"]}) or
                    result["spine_payload_bytes"] != 16 * len(identity["updates"])):
                raise ValueError("CPU preparation batch, ABI or protocol changed")
            shards = (identity["vertices"] + 65535) // 65536
            counts = [[0] * 4 for _ in range(shards)]
            used = [0] * shards
            for _, dst, _ in identity["updates"]:
                part = dst // 65536
                counts[part][used[part] % 4] += 1
                used[part] += 1
            if result["gr_lane_allocation_bytes"] != 8 * sum(max(c, 1) for part in counts for c in part):
                raise ValueError("GraSU lane padding or input count changed")
            for arm in ("spine", "gr"):
                samples = result[arm + "_ns_per_batch"]
                if len(samples) != 100 or any(not math.isfinite(v) or v <= 0 for v in samples):
                    raise ValueError("complete positive timing samples required")
        measured[workload] = {}
        for arm in ("spine", "gr"):
            medians = [median(row["result"][arm + "_ns_per_batch"]) for row in group]
            measured[workload][arm] = dict(median_ns=median(medians),
                process_median_ns=medians, min_process_median_ns=min(medians), max_process_median_ns=max(medians))
    comparisons = []
    for row in device:
        m = measured[row["workload"]]
        gr_ns = row["gr_cycles"] / 0.15
        spine_ns = row["spine_cycles"] / 0.15
        partial_gap = gr_ns + m["gr"]["median_ns"] - spine_ns - m["spine"]["median_ns"]
        comparisons.append(dict(**row, cpu_preparation=m,
            clock_mhz=150, device_gap_gr_minus_spine_ns=gr_ns - spine_ns,
            partial_gap_gr_minus_spine_ns=partial_gap,
            device_plus_partial_cpu_ratio=(gr_ns + m["gr"]["median_ns"]) / (spine_ns + m["spine"]["median_ns"]),
            break_even_extra_host_on="spine" if partial_gap > 0 else "gr",
            break_even_extra_host_ns=abs(partial_gap),
            full_host_inclusive_speedup=None))
    return comparisons


def validate(report, read):
    if (report["status"] != STATUS or report["pins_unchanged"] is not True or report["failures"] or
            report["baseline_admitted"] is not False or report["full_host_time_included"] is not False or
            len(report["steps"]) != 16):
        raise ValueError("complete partial-host measurement required, not an E2E claim")
    for step in report["steps"]:
        name = Path(step["stdout"]).name.removesuffix(".stdout.txt")
        if (step["exit_code"] or step["timed_out"] or
                json.loads(read("raw/" + name + ".resources.json")) != step):
            raise ValueError("failed or changed CPU command record")
        read("raw/" + name + ".stdout.txt")
        read("raw/" + name + ".stderr.txt")
    if read("raw/self_test.stdout.txt").strip() != b"HOST_SELF_TEST PASS":
        raise ValueError("CPU preparation self-test did not pass")
    for row in report["rows"]:
        label = f"{row['workload']}_repeat{row['repeat']}"
        if records(read("raw/" + label + ".stdout.txt").decode(), "HOST_PREPARATION ") != [row["result"]]:
            raise ValueError("raw CPU samples changed")
        if json.loads(read("raw/" + label + ".resources.json")) != row["resources"]:
            raise ValueError("CPU row command identity changed")
    comparisons = summarize(report["rows"], report["warm_rows"])
    if comparisons != report["comparisons"]:
        raise ValueError("partial-host arithmetic changed")
    return comparisons
