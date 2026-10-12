"""Reconstruct helper lifetimes without assigning exclusive stall causes."""

import re
from statistics import median

from ...adapter_axi.analysis import ROW_BASE, _records, parse_trace


def analyze(text):
    cases = parse_trace(text)
    starts = _records(text, "ROW_START", ("trial", "cycle", "source", "begin", "end"))
    finishes = _records(text, "ROW_DONE", ("trial", "cycle", "source"))
    packets = _records(text, "ROW_PACKET", ("trial", "cycle", "source"))
    if any(row["trial"] not in range(12) for row in starts + finishes + packets):
        raise ValueError("observer event has an unknown trial")
    report = []
    for case in cases:
        select = lambda rows: [row for row in rows if row["trial"] == case["trial"]]
        sources = [src for src in range(case["vertices"]) if case["placement"] == 0
                   or case["placement"] == 1 and src + 1 == case["vertices"]
                   or case["placement"] == 2 and src == 0
                   or case["placement"] == 3 and src % 7 == 0]
        began, ended, output = select(starts), select(finishes), select(packets)
        if ([row["source"] for row in began] != sources
                or [row["source"] for row in ended] != sources
                or [row["source"] for row in output] != [src for src in sources
                   for _ in range(case["length"] * 2)]):
            raise ValueError("occupied-row/source/packet conservation failed")
        if (len(output) != case["packets"] or output and (
                output[0]["cycle"] != case["first_packet"]
                or output[-1]["cycle"] != case["last_packet"])
                or any(right["cycle"] <= left["cycle"] for left, right in zip(output, output[1:]))):
            raise ValueError("observer packet timeline differs from AXI bench")
        rows = []
        for index, (start, done) in enumerate(zip(began, ended, strict=True)):
            if (not case["start"] <= start["cycle"] < done["cycle"] <= case["done"]
                    or index and start["cycle"] <= ended[index - 1]["cycle"]
                    or (start["begin"], start["end"]) != (
                        index * case["length"] * 16, (index + 1) * case["length"] * 16)):
                raise ValueError("occupied helper overlaps or row geometry differs")
            reads = [r for r in case["requests"] if r["address"] < ROW_BASE
                     and start["cycle"] <= r["cycle"] <= done["cycle"]]
            if len(reads) != case["length"] or any(r["beats"] != 1 or r["size"] != 64 for r in reads):
                raise ValueError("helper PMA request conservation failed")
            accepted = [r["cycle"] for r in output if r["source"] == start["source"]]
            rows.append({"source": start["source"], "start": start["cycle"], "done": done["cycle"],
                         "lifetime_cycles": done["cycle"] - start["cycle"],
                         "first_PMA_AR": reads[0]["cycle"], "last_PMA_AR": reads[-1]["cycle"],
                         "first_packet": accepted[0], "last_packet": accepted[-1]})
        if sum(case["length"] for _ in rows) != case["pma_requests"]:
            raise ValueError("PMA request exists outside observed helpers")
        lifetime = sum(row["lifetime_cycles"] for row in rows)
        report.append({key: case[key] for key in (
            "trial", "vertices", "placement", "length", "latency", "stall", "cycles",
            "row_requests", "pma_requests", "maximum_outstanding")} | {
                "rows": rows, "helper_lifetime_sum": lifetime,
                "outside_helper_lifetimes": case["cycles"] - lifetime,
                "helper_lifetime_fraction": lifetime / case["cycles"],
                "median_helper_lifetime": median(row["lifetime_cycles"] for row in rows) if rows else None,
                "successive_helper_start_gaps": [right["start"] - left["start"]
                    for left, right in zip(rows, rows[1:])],
                "scope": "overlapping_helper_memory_output_lifetimes_not_exclusive_stall_costs",
            })
    return cases, report


def helper_instance(text):
    names = re.findall(r"^pma_to_regraph_adapter_emit_row_segments (\w+)\s*\(", text, re.M)
    if len(names) != 1:
        raise ValueError("exactly one production occupied-row helper required")
    return names[0]


def require_replay(observed, frozen):
    if observed != frozen:
        raise ValueError("read-only observer changed the frozen complete RTL transcript")
