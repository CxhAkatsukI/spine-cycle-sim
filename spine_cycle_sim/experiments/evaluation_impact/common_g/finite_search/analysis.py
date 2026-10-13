"""Require exact old results and conserved new work before reporting ratios."""

from ..cached_hot.study import metadata
from ..hot_lanes.analysis import LEDGERS
from ..metadata_credits.preparation import CREDITS, matrix as previous_matrix
from ..search_diagnostics.analysis import key, validate_diagnostics
from .preparation import ARM, CASES, GEOMETRY, PREVIOUS_ARMS, matrix


def analyze(report, previous):
    for name, value in metadata().items():
        if name not in ("assumptions", "safety") and report.get(name) != value:
            raise ValueError("finite search changed fixed G timing/resources")
    expected = set(matrix())
    if report["errors"] or len(report["rows"]) != len(expected) or \
            set(map(key, report["rows"])) != expected or len(report["matrix"]) != len(expected) or \
            set(map(tuple, report["matrix"])) != expected:
        raise ValueError("complete unique finite-search matrix required")
    if previous["status"] != "G_METADATA_CREDIT_PREDICTIONS_VALIDATED" or \
            len(previous["rows"]) != len(previous_matrix()) or \
            set(map(key, previous["rows"])) != set(previous_matrix()):
        raise ValueError("complete frozen 190-row metadata checkpoint required")
    if report.get("finite_search_geometry") != GEOMETRY:
        raise ValueError("finite search topology or schedule assumptions changed")
    if report.get("metadata_credits_per_master") != {**CREDITS, ARM: 32} or \
            report.get("metadata_masters_per_cu") != 1 or report.get("new_arm_contexts_per_cu") != 64:
        raise ValueError("undeclared finite-search AXI resources")
    for name in ("baseline_admitted", "hardware_timing_admitted", "production_baseline_admitted",
                 "publication_match_admitted", "reference_cache_timing_admitted"):
        if report.get(name, False):
            raise ValueError("finite-stage prediction cannot promote hardware/publication admission")
    old = {key(row): row for row in previous["rows"]}
    keyed = {key(row): row for row in report["rows"]}
    summaries = []
    for row in report["rows"]:
        value = row["observation"]
        if value["arm"] != row["arm"] or value["timing_kind"] != "declared_prediction" or \
                any(type(value[f]) is not int or value[f] < 0 for f in ("read_bytes", "write_bytes") + LEDGERS) or \
                value["cache_updates"] + value["ddr_updates"] != row["updates"] or value["row_reads"] != row["updates"]:
            raise ValueError("finite search work/identity mismatch")
        if row["arm"] in PREVIOUS_ARMS:
            if any(row[field] != old[key(row)][field] for field in
                   ("observation", "state_sha256", "diagnostics")):
                raise ValueError("legacy state/time/work/traffic/diagnostics changed")
        else:
            control = keyed[(row["latency"], row["case"], row["updates"], "cached_hot64_m32")]
            if row["state_sha256"] != control["state_sha256"] or any(
                    value[field] != control["observation"][field] for field in
                    ("read_bytes", "write_bytes") + LEDGERS):
                raise ValueError("finite stages changed full PMA state/work/traffic")
            controls = {p["name"]: p for p in control["diagnostics"]["ports"]}
            for port in row["diagnostics"]["ports"]:
                prior = controls.get(port["name"])
                if prior is None or any(port[field] != prior[field] for field in
                        ("channel", "width", "requests", "responses", "beats_issued", "beats_completed",
                         "read_bytes", "write_bytes", "parent_limit", "burst_limit", "reorder_limit")):
                    raise ValueError("finite stages changed per-port resources or traffic")
        summaries.append(validate_diagnostics(row))
    comparisons = []
    for latency in (64, 128):
        for name, count, _ in CASES:
            selected = {arm: keyed[(latency, name, count, arm)] for arm in
                        ("original_forwarded", "cached_hot64_m32", ARM)}
            if len({row["state_sha256"] for row in selected.values()}) != 1:
                raise ValueError("finite search original/candidate full-state disagreement")
            cycles = {arm: row["observation"]["cycles"] for arm, row in selected.items()}
            comparisons.append({"latency": latency, "case": name, "updates": count,
                "cycles": cycles, "ratio_over_forwarded_original": cycles[ARM] / cycles["original_forwarded"],
                "ratio_over_flat_m32": cycles[ARM] / cycles["cached_hot64_m32"]})
    nonempty = [row for row in comparisons if row["updates"]]
    return {"exact_replayed_rows": len(old), "stage_observations": summaries, "comparisons": comparisons,
        "no_more_than_ten_percent_slower": all(row["ratio_over_forwarded_original"] <= 1.1 for row in nonempty),
        "within_ten_percent_both_directions": all(.9 <= row["ratio_over_forwarded_original"] <= 1.1 for row in nonempty),
        "baseline_admitted": False, "hardware_timing_admitted": False}
