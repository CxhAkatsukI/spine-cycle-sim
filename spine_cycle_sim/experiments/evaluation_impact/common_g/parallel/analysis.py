"""Full-state and old-default regression gates, separate from timing claims."""

from ..preparation import COUNTS


def summarize(rows, previous):
    comparisons = []
    cases = sorted({(row["latency"], row["case"]) for row in rows})
    for latency, case in cases:
        pair = [row for row in rows if row["latency"] == latency and row["case"] == case]
        values = {row["arm"]: row["observation"] for row in pair}
        if set(values) != {"original", "current", "parallel"}:
            raise ValueError("incomplete three-arm case")
        if len({row["state_sha256"] for row in pair}) != 1:
            raise ValueError("three-arm PMA state differs")
        for field in ("cache_updates", "ddr_updates", "row_reads", "binary_probes"):
            if len({value[field] for value in values.values()}) != 1:
                raise ValueError("logical work differs: " + field)
        comparisons.append({"latency": latency, "case": case,
            "updates": pair[0]["updates"], "cycles": {arm: value["cycles"] for arm, value in values.items()},
            "parallel_over_original": values["parallel"]["cycles"] / values["original"]["cycles"],
            "parallel_over_current": values["parallel"]["cycles"] / values["current"]["cycles"]
                if values["current"]["cycles"] else None})
    for old in previous["rows"]:
        if old["updates"] not in COUNTS:
            raise ValueError("unexpected frozen diagnostic row")
        case = {0: "empty", 64: "small", 4096: "large"}[old["updates"]]
        matches = [row for row in rows if row["latency"] == old["latency"] and
                   row["case"] == case and row["arm"] == old["observation"]["arm"]]
        if len(matches) != 1 or matches[0]["observation"] != old["observation"] or \
                matches[0]["state_sha256"] != old["state_sha256"]:
            raise ValueError("unchanged original/current no longer equals frozen diagnostic")
    nonempty = [row for row in comparisons if row["updates"]]
    return {"comparisons": comparisons, "default_regression_rows": len(previous["rows"]),
        "prediction_no_more_than_ten_percent_slower": bool(nonempty) and
            all(row["parallel_over_original"] <= 1.1 for row in nonempty),
        "within_ten_percent_both_directions": bool(nonempty) and
            all(0.9 <= row["parallel_over_original"] <= 1.1 for row in nonempty)}
