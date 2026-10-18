"""Keep setup, hold and pulse results separate from any hardware admission."""

import math

from spine_cycle_sim.experiments.sharded_k4_stages.bitstream import parse_routed_timing
from spine_cycle_sim.experiments.sharded_k4_stages.execution import identity

PASSES = ("baseline", "clock_opt", "fanout", "replication")


def timing(path):
    lines = path.read_text().splitlines()
    headers = [index for index, line in enumerate(lines) if line.strip().startswith("WNS(ns)")]
    if len(headers) != 1 or headers[0] + 2 >= len(lines):
        raise ValueError("one complete design timing summary required")
    values = lines[headers[0] + 2].split()
    if len(values) != 12:
        raise ValueError("twelve design timing fields required")
    metrics = {}
    for offset, name in ((0, "setup"), (4, "hold"), (8, "pulse")):
        slack, total = float(values[offset]), float(values[offset + 1])
        failing, endpoints = int(values[offset + 2]), int(values[offset + 3])
        if not all(math.isfinite(value) for value in (slack, total)) or total > 0 or \
                not 0 <= failing <= endpoints:
            raise ValueError("invalid timing values or endpoint counts")
        metrics[name] = {"worst_ns": slack, "total_ns": total, "failing": failing, "endpoints": endpoints}
    try:
        parse_routed_timing(path)
        passed, reason = True, None
    except ValueError as error:
        passed, reason = False, str(error)
    return {"report": identity(path), "metrics": metrics, "summary_constraints_pass": passed,
            "strict_parser_reason": reason}


def inspect(output):
    rows = [{"pass": name, **timing(output / (name + ".rpt"))} for name in PASSES]
    return {"passes": rows, "any_summary_constraints_pass": any(row["summary_constraints_pass"] for row in rows),
            "final_summary_constraints_pass": rows[-1]["summary_constraints_pass"],
            "final_checkpoint": identity(output / "refined.dcp"),
            "reports": [identity(output / name) for name in (
                "clocks.rpt", "final_route_status.rpt", "final_drc.rpt")]}
