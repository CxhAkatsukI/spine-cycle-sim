"""Admit only explained R-cycle changes after the finite read-credit repair."""


EXPECTED = {(w, latency, arm, reverse) for w in ("smoke", "amazon")
            for latency in (64, 128) for arm, reverse in (("gr", 0), ("gr", 1), ("spine", 0))}


def indexed(report):
    if report.get("pins_unchanged") is not True or report.get("failures") != []:
        raise ValueError("successful unchanged SSSP replay required")
    rows = report["rows"]
    result = {(r["workload"], r["latency"], r["arm"], r["reverse"]): r for r in rows}
    if len(rows) != 12 or set(result) != EXPECTED:
        raise ValueError("twelve unique registered SSSP trajectories required")
    for row in rows:
        if (row["result"].get("correctness") is not True or
                row["result"].get("ledger_closed") is not True or
                row["state_hashes"]["expected"] != row["state_hashes"]["final"]):
            raise ValueError("independent SSSP state and ledger gates required")
    return result


def compare(before, after):
    old, new = indexed(before), indexed(after)
    deltas = []
    for workload in ("smoke", "amazon"):
        for latency in (64, 128):
            if new[workload, latency, "gr", 0]["result"] != new[workload, latency, "gr", 1]["result"]:
                raise ValueError("registration order changed G+R result or timing")
    for key in sorted(EXPECTED):
        a, b = old[key], new[key]
        if any(a[k] != b[k] for k in ("input", "state_hashes")):
            raise ValueError("SSSP input or complete state changed")
        previous, current = a["result"], b["result"]
        if key[2] == "spine":
            if current != previous:
                raise ValueError("Spine state, cycles or traffic changed")
        else:
            allowed = {"cycles", "r_cycles"}
            if ({k: v for k, v in current.items() if k not in allowed} !=
                    {k: v for k, v in previous.items() if k not in allowed} or
                    current["cycles"] - previous["cycles"] !=
                    current["r_cycles"] - previous["r_cycles"]):
                raise ValueError("only explicitly reported R-cycle deltas may change")
        deltas.append(dict(workload=key[0], latency=key[1], arm=key[2], reverse=key[3],
            before_cycles=previous["cycles"], after_cycles=current["cycles"],
            delta_cycles=current["cycles"] - previous["cycles"]))
    return dict(status="SSSP_READ_CREDIT_CORRECTION", trajectories=12,
                states_and_bytes_exact=True, spine_cycles_exact=True, cycle_deltas=deltas)
