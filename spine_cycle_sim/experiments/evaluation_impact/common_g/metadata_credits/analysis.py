"""Separate declared buffer changes, exact replay and performance retention."""

from ..cached_hot.study import metadata
from ..hot_lanes.analysis import LEDGERS
from ..search_diagnostics.analysis import key, validate_diagnostics
from ..search_diagnostics.preparation import matrix as previous_matrix
from .preparation import ARMS, CASES, CREDITS, NEW_ARMS, PREVIOUS_ARMS, matrix


def analyze(report, previous):
    for name, value in metadata().items():
        if name not in ("assumptions", "safety") and report.get(name) != value:
            raise ValueError("fixed metadata-control timing/resource geometry changed")
    if report.get("metadata_credits_per_master") != CREDITS or \
            report.get("metadata_masters_per_cu") != 1 or \
            report.get("new_arm_contexts_per_cu") != 64:
        raise ValueError("undeclared metadata buffers, masters or contexts")
    expected = set(matrix())
    if report["errors"] or len(report["rows"]) != len(expected) or set(map(key, report["rows"])) != expected or \
            len(report["matrix"]) != len(expected) or set(map(tuple, report["matrix"])) != expected:
        raise ValueError("complete unique metadata-credit matrix required")
    if previous["status"] != "G_READ_ONLY_DIAGNOSTICS_EXACT_REPLAY" or \
            len(previous["rows"]) != len(previous_matrix()) or set(map(key, previous["rows"])) != set(previous_matrix()):
        raise ValueError("complete frozen diagnostic checkpoint required")
    if report.get("baseline_admitted", False):
        raise ValueError("buffer prediction cannot admit the production baseline")
    old = {key(row): row for row in previous["rows"]}
    keyed = {key(row): row for row in report["rows"]}
    stages = []
    for row in report["rows"]:
        value = row["observation"]
        if value["arm"] != row["arm"] or value["timing_kind"] != "declared_prediction" or \
                any(type(value[f]) is not int or value[f] < 0 for f in ("read_bytes", "write_bytes") + LEDGERS) or \
                value["cache_updates"] + value["ddr_updates"] != row["updates"] or value["row_reads"] != row["updates"]:
            raise ValueError("invalid metadata-control identity or work ledger")
        if row["arm"] in PREVIOUS_ARMS:
            prior = old[key(row)]
            if any(row[f] != prior[f] for f in ("observation", "state_sha256", "diagnostics")):
                raise ValueError("default observations or diagnostics changed")
        else:
            control = keyed[(row["latency"], row["case"], row["updates"], "cached_hot64")]
            if row["state_sha256"] != control["state_sha256"] or any(
                    value[f] != control["observation"][f] for f in ("read_bytes", "write_bytes") + LEDGERS):
                raise ValueError("metadata buffers changed complete state, work or traffic")
            controls = {p["name"]: p for p in control["diagnostics"]["ports"]}
            for port in row["diagnostics"]["ports"]:
                prior = controls.get(port["name"])
                if prior is None or any(port[f] != prior[f] for f in
                        ("channel", "width", "requests", "responses", "beats_issued",
                         "beats_completed", "read_bytes", "write_bytes")):
                    raise ValueError("metadata buffers changed per-port topology or traffic")
        stages.append(validate_diagnostics(row))
        if row["arm"] != "original_forwarded":
            for port in row["diagnostics"]["ports"]:
                limit = CREDITS[row["arm"]] if port["name"].startswith("grasu-row") else 16
                if any(port[f] != limit for f in ("parent_limit", "burst_limit", "reorder_limit")):
                    raise ValueError("unexpected per-port credit change")
    comparisons = []
    for latency in (64, 128):
        for name, count, _ in CASES:
            rows = [keyed[(latency, name, count, arm)] for arm in ARMS]
            if len({row["state_sha256"] for row in rows}) != 1:
                raise ValueError("metadata-control final states differ")
            cycles = {row["arm"]: row["observation"]["cycles"] for row in rows}
            comparisons.append({"latency": latency, "case": name, "updates": count, "cycles": cycles,
                "ratios_over_forwarded_original": {arm: cycles[arm] / cycles["original_forwarded"] for arm in NEW_ARMS},
                "ratios_over_cached64": {arm: cycles[arm] / cycles["cached_hot64"] for arm in NEW_ARMS}})
    nonempty = [row for row in comparisons if row["updates"]]
    return {"exact_replayed_rows": len(old), "stage_observations": stages, "comparisons": comparisons,
        "no_more_than_ten_percent_slower": {arm: all(row["ratios_over_forwarded_original"][arm] <= 1.1 for row in nonempty) for arm in NEW_ARMS},
        "within_ten_percent_both_directions": {arm: all(.9 <= row["ratios_over_forwarded_original"][arm] <= 1.1 for row in nonempty) for arm in NEW_ARMS},
        "baseline_admitted": False, "hardware_timing_admitted": False}
