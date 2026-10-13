"""Require exact old replay, conserved controls and explicit replication costs."""

from copy import deepcopy

from ..chronological_contract import case_names
from ..preparation import ARMS as BASE_ARMS, LATENCIES
from ..real_analysis import analyze as analyze_real
from .preparation import ARMS, CONTROLS, REPLICA_CHANNELS, baseline_value


def identity(row):
    return row["case"], row["latency"], row["arm"]


def project(rows, contract, runtime_arm):
    selected = deepcopy([row for row in rows if row["arm"] in (*BASE_ARMS[:2], runtime_arm)])
    for row in selected:
        if row["arm"] == runtime_arm:
            row["arm"] = row["observation"]["arm"] = BASE_ARMS[2]
    declared = {**contract, "matrix": [{key: row[key] for key in ("case", "latency", "arm")} for row in selected]}
    return analyze_real(selected, declared, names=case_names())


def check_diagnostics(observation):
    diagnostic = observation["diagnostics"]
    cycles = observation["cycles"]
    if diagnostic is None or diagnostic["sampling"] != "after every committed cycle; overlapping markers are not additive":
        raise ValueError("missing read-only runtime diagnostics")
    for key, count in (("search_done", 4), ("cache_loaded", 2), ("write_started", 2),
                       ("first_hot_update", 2), ("last_hot_update", 2)):
        if len(diagnostic[key]) != count or any(not 0 < value <= cycles + 1 for value in diagnostic[key]):
            raise ValueError("invalid observed completion marker")
    if sum(diagnostic["hot_completed"]) != observation["physical_updates"]:
        raise ValueError("observed update progress differs")
    for key in ("metadata_port_cycles", "metadata_full_cycles", "metadata_peak_parents"):
        if len(diagnostic[key]) != 4:
            raise ValueError("incomplete metadata pressure observations")
    # AxiMaster::pending_requests includes one staged input beyond its 32
    # active parent slots. This is observation geometry, not a larger budget.
    if any(not 0 <= full <= total or not 0 <= peak <= 33 for total, full, peak in zip(
            diagnostic["metadata_port_cycles"], diagnostic["metadata_full_cycles"], diagnostic["metadata_peak_parents"])):
        raise ValueError("invalid metadata pressure counters")
    ports = diagnostic["ports"]
    if not ports or len({p["name"] for p in ports}) != len(ports):
        raise ValueError("missing or duplicate observed port")
    for port in ports:
        if (port["requests"] != port["responses"] or port["beats_issued"] != port["beats_completed"] or
                not 0 <= port["channel"] < 32 or port["peak_bursts"] > port["burst_limit"]):
            raise ValueError("observed port not drained or exceeds finite limits")
    if any(sum(port[key] for port in ports) != observation[key] for key in ("read_bytes", "write_bytes")):
        raise ValueError("observed ports do not conserve complete traffic")


def check_resources(observation, runtime):
    arm, resource = observation["arm"], observation["resources"]
    original = runtime["resources"]
    if resource is None:
        raise ValueError("missing observed resource budget")
    row_copy = arm in (CONTROLS[0], CONTROLS[2])
    binary_copy = arm in (CONTROLS[1], CONTROLS[2])
    extra = 4 * (row_copy * original["row_allocated_bytes"] + binary_copy * original["binary_allocated_bytes"])
    if (original["extra_metadata_bytes"] != 0 or resource["extra_metadata_bytes"] != extra or
            resource["allocated_bytes"] != original["allocated_bytes"] + extra or
            not resource["allocated_bytes"] <= resource["channel_span_bytes"] <= 23 * 512 * 1024**2 or
            not original["used_channels"] <= resource["used_channels"] <= 23):
        raise ValueError("metadata replication resource cost omitted or invalid")
    for key, copied in (("row_channels", row_copy), ("binary_channels", binary_copy)):
        expected = REPLICA_CHANNELS if copied else original[key]
        if resource[key] != expected or any(not 0 <= channel < 23 for channel in resource[key]):
            raise ValueError("metadata channel placement differs")
    for key in ("row_allocated_bytes", "binary_allocated_bytes"):
        if resource[key] != original[key] or resource[key] <= 0:
            raise ValueError("metadata geometry differs")


def analyze(rows, contract):
    expected = {(case, latency, arm) for case in case_names() for latency in LATENCIES for arm in ARMS}
    if (len(rows) != len(expected) or {identity(row) for row in rows} != expected or
            len(contract["matrix"]) != len(expected) or {identity(r) for r in contract["matrix"]} != expected):
        raise ValueError("incomplete, duplicate or undeclared metadata matrix")
    previous = {identity(row): row for row in contract["baseline_rows"]}
    baseline = {identity(row): baseline_value(row) for row in rows if row["arm"] in BASE_ARMS}
    if len(contract["baseline_rows"]) != 36 or len(previous) != 36 or previous != baseline:
        raise ValueError("diagnostic instrumentation changed old cycles, work, traffic or state")
    summary = project(rows, contract, BASE_ARMS[2])
    controls = {arm: project(rows, contract, arm) for arm in CONTROLS}
    observations = {identity(row): row["observation"] for row in rows}
    decisions = []
    for row in rows:
        if row["arm"] in BASE_ARMS[:2]:
            if row["observation"]["diagnostics"] is not None or row["observation"]["resources"] is not None:
                raise ValueError("unexpected original/four-bank instrumentation")
            continue
        runtime = observations[row["case"], row["latency"], BASE_ARMS[2]]
        check_diagnostics(row["observation"])
        check_resources(row["observation"], runtime)
    for case in contract["cases"]:
        for latency in LATENCIES:
            group = {arm: observations[case, latency, arm] for arm in ARMS}
            decisions.append({"case": case, "latency": latency,
                "cycles": {arm: value["cycles"] for arm, value in group.items()},
                "controls": {arm: {"over_original": group[arm]["cycles"] / group[BASE_ARMS[0]]["cycles"],
                    "over_runtime": group[arm]["cycles"] / group[BASE_ARMS[2]]["cycles"],
                    "resources": group[arm]["resources"]} for arm in CONTROLS}})
    return {**summary, "prediction_rows": len(rows), "baseline_exact_replay_rows": 36,
        "metadata_comparisons": decisions,
        "control_ten_percent_diagnostic_met": {arm: value["runtime_ten_percent_diagnostic_met"]
                                              for arm, value in controls.items()},
        "replication_controls_only": True, "production_layout_changed": False}
