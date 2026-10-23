"""Require common full states before reporting any predicted speedup."""

import json
from pathlib import Path
from spine_cycle_sim.experiments.campaign_runtime import sha256_file


def record(resources, output, workload, latency, arm, reverse):
    if resources["exit_code"] or resources["timed_out"]:
        raise ValueError("execution failed; raw evidence retained: " + resources["stdout"])
    lines = Path(resources["stdout"]).read_text().splitlines()
    def one(prefix):
        matches = [json.loads(line[len(prefix):]) for line in lines if line.startswith(prefix)]
        if len(matches) != 1:
            raise ValueError("one complete " + prefix + " record required")
        return matches[0]
    identity, result = one("WARM_INPUT "), one("WARM_RESULT ")
    if result["arm"] != arm or not result["correctness"] or not result["ledger_closed"]:
        raise ValueError("correctness and drained ledgers required")
    hashes = {name: sha256_file(output / (name + ".u32le"))
              for name in ("old_state", "expected", "final")}
    if hashes["expected"] != hashes["final"] or result["cycles"] <= 0:
        raise ValueError("complete final state must match independent Dijkstra")
    return dict(workload=workload, latency=latency, arm=arm, reverse=reverse,
                input=identity, result=result, state_hashes=hashes, resources=resources)


def summarize(rows):
    comparisons = []
    for workload in ("smoke", "amazon"):
        for latency in (64, 128):
            group = [r for r in rows if (r["workload"], r["latency"]) == (workload, latency)]
            expected = {(0, "gr"), (1, "gr"), (0, "spine")}
            if {(r["reverse"], r["arm"]) for r in group} != expected or len(group) != 3:
                raise ValueError("complete predeclared three-arm group required")
            first = group[0]
            if any(r["input"] != first["input"] or r["state_hashes"] != first["state_hashes"] for r in group):
                raise ValueError("warm state, batch and final state must be identical")
            g = [r for r in group if r["arm"] == "gr"]
            if g[0]["result"] != g[1]["result"]:
                raise ValueError("G+R depends on component registration order")
            s = next(r for r in group if r["arm"] == "spine")
            comparisons.append(dict(workload=workload, latency=latency,
                g_cycles=g[0]["result"]["g_cycles"], r_cycles=g[0]["result"]["r_cycles"],
                gr_cycles=g[0]["result"]["cycles"], spine_cycles=s["result"]["cycles"],
                speedup_gr_over_spine=g[0]["result"]["cycles"] / s["result"]["cycles"]))
    return comparisons
