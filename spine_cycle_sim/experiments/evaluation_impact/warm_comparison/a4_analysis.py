"""Admit the complete same-batch A4 matrix, never infer parity from total time."""

from pathlib import Path
from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ...original_regraph_inputs.analysis import records
from .analysis import record, summarize as summarize_warm


def reference_rows(report, directory):
    if report["status"] != "COMPLETE_EXPLORATORY_DEVICE_PREDICTION":
        raise ValueError("complete warm comparison required")
    rows = []
    for saved in report["rows"]:
        output = directory / (f"{saved['workload']}_lat{saved['latency']}_"
                              f"{saved['arm']}_order{saved['reverse']}")
        current = record(saved["resources"], output, saved["workload"], saved["latency"],
                         saved["arm"], saved["reverse"])
        if current != saved:
            raise ValueError("warm reference raw output or full state changed")
        rows.append(current)
    if summarize_warm(rows) != report["comparisons"]:
        raise ValueError("warm reference comparison changed")
    return rows


def a4_record(step, directory, workload, latency, reverse):
    if step["exit_code"] or step["timed_out"]:
        raise ValueError("A4 execution failed; evidence retained")
    text = Path(step["stdout"]).read_text()
    identity, results = records(text, "WARM_INPUT "), records(text, "DEMO_RESULT ")
    if len(identity) != 1 or len(results) != 1:
        raise ValueError("one complete input/result required")
    result = results[0]
    rounds = records(text, "DEMO_ROUND ")
    if (result["arm"] != "a4_io16" or result["passed"] is not True or
            result["cycles"] <= 0 or result["rounds"] != identity[0]["oracle_rounds"] or
            len(rounds) != result["rounds"] or
            [r["round"] for r in rounds] != list(range(len(rounds))) or
            any(r["arm"] != "a4_io16" or r["cycles"] <= 0 for r in rounds) or
            sum(r["cycles"] for r in rounds) != result["cycles"] or rounds[-1]["active"] != 0):
        raise ValueError("A4 complete correctness/convergence records required")
    hashes = {name: sha256_file(directory / (name + ".u32le"))
              for name in ("old_state", "expected", "final")}
    replicas = [sha256_file(directory / f"replica{i}.u32le") for i in range(4)]
    if hashes["expected"] != hashes["final"] or len(set(replicas)) != 1:
        raise ValueError("A4 full final state or replicas differ")
    return dict(workload=workload, latency=latency, reverse=reverse, input=identity[0],
                result=result, rounds=rounds, state_hashes=hashes, replica_hashes=replicas,
                resources=step)


def summarize(rows, warm_rows):
    warm = summarize_warm(warm_rows)
    if len(rows) != 8:
        raise ValueError("all eight same-batch A4 executions required")
    comparisons = []
    for saved in warm:
        key = saved["workload"], saved["latency"]
        group = [r for r in rows if (r["workload"], r["latency"]) == key]
        if len(group) != 2 or {r["reverse"] for r in group} != {0, 1}:
            raise ValueError("normal and reverse A4 runs required")
        first = group[0]
        for row in group:
            if any(row[name] != first[name] for name in
                   ("result", "rounds", "input", "state_hashes", "replica_hashes")):
                raise ValueError("A4 registration-order dependence")
        common = [r for r in warm_rows if (r["workload"], r["latency"]) == key]
        if any(r["input"] != first["input"] or r["state_hashes"] != first["state_hashes"] for r in common):
            raise ValueError("different common graph, warm state, batch or result")
        ratio = saved["r_cycles"] / first["result"]["cycles"]
        comparisons.append(dict(**saved, a4_cycles=first["result"]["cycles"],
            r_over_a4=ratio, r_delta_pct=(ratio - 1) * 100, within_15pct=abs(ratio - 1) <= 0.15,
            a4_read_bytes=first["result"]["read_bytes"], a4_write_bytes=first["result"]["write_bytes"]))
    return comparisons
