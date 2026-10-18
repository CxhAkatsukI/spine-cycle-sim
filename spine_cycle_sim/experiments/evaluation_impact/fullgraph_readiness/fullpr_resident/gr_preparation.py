"""FullPR CPU preparation using the shared bounded host-study executor."""

import math
from pathlib import Path

from .. import analysis, preparation, recheck, study
from ..board_analysis import single
from . import inputs

PASS = "GR_FULLPR_HOST_PREPARATION_PASS_NOT_BOARD_OR_PERFORMANCE"
PREFIX = "FULL_PR_PMA_NATIVE_SHARDED"


def freeze(source, cohort, output):
    frozen, pins = inputs.load(cohort)
    host = preparation.freeze_sources(source, output, extra_tools=("resident_full_pagerank.hpp",))
    return {**host, "rows": frozen["rows"], "pins": [*pins, *host["pins"]]}


def command(binary, row, result):
    return [str(binary), "--prepare-only", row["graph"], str(result), "--resident-fullpr"]


def geometry(row, initial):
    expected = {"vertices": row["vertices"], "static_edges": row["initial_edges"],
                "logical_updates": row["updates"], "physical_updates": row["updates"],
                "final_edges": row["initial_edges"] + row["updates"],
                "destination_partitions": (row["vertices"] + 65535) // 65536,
                "rounds": 256, "warm_residual_checked": 1}
    if any(int(initial[key]) != value for key, value in expected.items()) or \
            initial.get("convergence") != "global_l1" or float(initial["epsilon"]) != 1e-6 or \
            float(initial["damping"]) != .85 or int(initial["pma_slots_total"]) <= 0 or \
            int(initial["hbm_graph_allocated_bytes"]) <= 0:
        raise ValueError("FullPR dimensions, old-rank check or convergence policy differ")


def analyze(row, stdout, stderr):
    lines = stdout.splitlines()
    if stderr.strip() or not lines or not lines[0].startswith(PREFIX + "_INPUT ") or \
            not lines[-1].startswith(PREFIX + "_PREP "):
        raise ValueError("diagnostic-free FullPR preparation required")
    initial = single(lines, PREFIX + "_INPUT")
    prepared = single(lines, PREFIX + "_PREP")
    geometry(row, initial)
    if any(prepared.get(key) != value for key, value in {
            "status": "PASS", "pma_destination_abi": "local_dst19", "k4_frontends": "4",
            "shared_regraph_downstream": "1", "conversion_cost": "absent"}.items()) or \
            any(int(prepared[key]) != int(initial[key]) for key in
                ("vertices", "destination_partitions", "pma_slots_total")) or \
            not 0 < int(prepared["pma_slots_max_shard"]) <= int(prepared["pma_slots_total"]) or \
            not math.isfinite(float(prepared["rank_sum"])) or float(prepared["rank_sum"]) <= 0:
        raise ValueError("FullPR PMA preparation contract differs")
    seen, updates = set(), 0
    for line in lines[1:-1]:
        if not line.startswith("GRASU_SHARDED_UPDATE_LAYOUT "):
            raise ValueError("unexpected output; preparation cannot execute hardware")
        layout = analysis.fields(line)
        shard = int(layout["shard"])
        count, hot, cold = (int(layout[key]) for key in ("updates", "cache_updates", "ddr_updates"))
        if shard in seen or not 0 <= shard < int(initial["destination_partitions"]) or \
                int(layout["destination_base"]) != shard * 65536 or count <= 0 or \
                min(hot, cold) < 0 or hot + cold != count:
            raise ValueError("FullPR shard/update conservation differs")
        seen.add(shard)
        updates += count
    if updates != row["updates"]:
        raise ValueError("FullPR physical update count differs")
    return {"dataset": row["dataset"], "algorithm": inputs.ALGORITHM, "status": "PASS",
            "input": initial, "prepared": prepared, "layout_shards": len(seen),
            "claim": "FullPR_CPU_reference_and_PMA_capacity_only_not_FPGA"}


def decision(cases):
    return PASS if [case["dataset"] for case in cases] == list(inputs.DATASETS) and \
        all(case["status"] == "PASS" and case["algorithm"] == inputs.ALGORITHM for case in cases) else "FAILED_RETAINED"


def protocol(cohort):
    return study.Protocol("FullPR AU/SU/WK CPU reference and PMA capacity; no hardware or performance claim",
        (inputs.ALGORITHM,), freeze, lambda _: [inputs.load(cohort)[0]["smoke"]], command, analyze, decision)


def replay(report, output):
    if report.get("status") != PASS or report.get("errors") or \
            any(report.get(key) is not False for key in recheck.CLAIMS):
        raise ValueError("complete CPU-only FullPR preparation required")
    cohort, _ = inputs.load(Path(report["preparation_input"]))
    if report["matrix"] != cohort["rows"] or [case["dataset"] for case in report["smokes"]] != ["SMOKE"] or \
            report["smokes"][0]["status"] != "PASS" or decision(report["cases"]) != PASS:
        raise ValueError("exact FullPR smoke and AU/SU/WK cohort required")
    events = dict(line.split() for line in report["memory_events_after"].splitlines())
    if any(int(events[key]) for key in ("max", "oom", "oom_kill", "oom_group_kill")):
        raise ValueError("FullPR memory-limit or OOM events prevent admission")
    labels = recheck.replay_steps(report, lambda name: (output / name).read_text(),
        algorithms=(inputs.ALGORITHM,), rows=[cohort["smoke"], *cohort["rows"]],
        prepare_command=command, analyze=analyze, successful=True)
    if len(report["steps"]) != len(labels):
        raise ValueError("all FullPR compilation and preparation steps required")
    preparation.unchanged(report["pins"], full=True)
    return cohort
