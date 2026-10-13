"""Full-scope admission and exact replay, never a chosen near-matching batch."""

from .preparation import ARMS, CASES

LEDGERS = ("cache_updates", "ddr_updates", "row_reads", "binary_probes")


def analyze(report, previous):
    expected = {(latency, name, count, arm) for latency in (64, 128)
                for name, count, _ in CASES for arm in ARMS}
    actual = [(r["latency"], r["case"], r["updates"], r["arm"]) for r in report["rows"]]
    if len(actual) != len(expected) or set(actual) != expected or \
            len(report["matrix"]) != len(expected) or set(map(tuple, report["matrix"])) != expected:
        raise ValueError("incomplete, duplicate, or undeclared hot-owner matrix")
    if report["errors"]:
        raise ValueError("matrix contains failed executions")
    for field in ("hardware_timing_admitted", "publication_match_admitted", "production_baseline_admitted"):
        if report.get(field) is not False:
            raise ValueError("prediction was promoted without evidence: " + field)
    for row in report["rows"]:
        value = row["observation"]
        if value["arm"] != row["arm"] or value["state_pass"] is not True or \
                value["timing_kind"] != "declared_prediction":
            raise ValueError("wrong observation identity or evidence kind")
        for field in ("cycles", "read_bytes", "write_bytes") + LEDGERS:
            if type(value[field]) is not int or value[field] < 0:
                raise ValueError("invalid nonnegative ledger: " + field)
        if value["cache_updates"] + value["ddr_updates"] != row["updates"] or \
                value["row_reads"] != row["updates"] or len(row["state_sha256"]) != 64:
            raise ValueError("work/state ledger does not close")
        if row["updates"] and value["cycles"] == 0:
            raise ValueError("nonempty work has no time")
    keyed = {(r["latency"], r["case"], r["arm"]): r for r in report["rows"]}
    if len(previous["rows"]) != 84:
        raise ValueError("requires complete frozen 84-row search checkpoint")
    for old in previous["rows"]:
        new = keyed[(old["latency"], old["case"], old["arm"])]
        if new["observation"] != old["observation"] or new["state_sha256"] != old["state_sha256"]:
            raise ValueError("old default/search predictions changed")
    comparisons = []
    for latency in (64, 128):
        for name, count, _ in CASES:
            rows = [keyed[(latency, name, arm)] for arm in ARMS]
            if len({r["state_sha256"] for r in rows}) != 1 or any(
                    len({r["observation"][field] for r in rows}) != 1 for field in LEDGERS):
                raise ValueError("four-arm logical state/work differ")
            values = {r["arm"]: r["observation"] for r in rows}
            for arm in ("current", "parallel"):
                for field in ("read_bytes", "write_bytes"):
                    if values[arm][field] != values["parallel_hot"][field]:
                        raise ValueError("hot concurrency changed physical traffic")
            cycles = {arm: value["cycles"] for arm, value in values.items()}
            comparisons.append({"latency": latency, "case": name, "updates": count, "cycles": cycles,
                "hot_over_original": cycles["parallel_hot"] / cycles["original"],
                "hot_over_search": cycles["parallel_hot"] / cycles["parallel"] if cycles["parallel"] else None})
    nonempty = [r for r in comparisons if r["updates"]]
    return {"comparisons": comparisons, "old_checkpoint_exact_rows": len(previous["rows"]),
            "prediction_no_more_than_ten_percent_slower": all(r["hot_over_original"] <= 1.1 for r in nonempty),
            "within_ten_percent_both_directions": all(0.9 <= r["hot_over_original"] <= 1.1 for r in nonempty)}
