"""Conserve cache traffic and replay all controls before reporting ratios."""

from ..hot_lanes.analysis import LEDGERS
from .preparation import ARMS, CASES, HOT_TRANSFER_BYTES, PREVIOUS_ARMS, matrix


def analyze(report, previous):
    expected = set(matrix())
    actual = [(r["latency"], r["case"], r["updates"], r["arm"]) for r in report["rows"]]
    if len(actual) != len(expected) or set(actual) != expected or \
            len(report["matrix"]) != len(expected) or set(map(tuple, report["matrix"])) != expected:
        raise ValueError("incomplete, duplicate, or undeclared cached-G matrix")
    if report["errors"]:
        raise ValueError("cached-G matrix contains failed executions")
    for field in ("hardware_timing_admitted", "publication_match_admitted",
                  "production_baseline_admitted", "reference_cache_timing_admitted"):
        if report.get(field) is not False:
            raise ValueError("unsupported timing/baseline promotion: " + field)
    keyed = {(r["latency"], r["case"], r["arm"]): r for r in report["rows"]}
    previous_expected = {(latency, name, count, arm) for latency in (64, 128)
                         for name, count, _ in CASES for arm in PREVIOUS_ARMS}
    old_ids = [(r["latency"], r["case"], r["updates"], r["arm"]) for r in previous["rows"]]
    if len(old_ids) != len(previous_expected) or set(old_ids) != previous_expected:
        raise ValueError("complete frozen 152-row hot-owner checkpoint required")
    for old in previous["rows"]:
        new = keyed[(old["latency"], old["case"], old["arm"])]
        if new["observation"] != old["observation"] or new["state_sha256"] != old["state_sha256"]:
            raise ValueError("old prediction/state/traffic changed")
    for row in report["rows"]:
        value = row["observation"]
        if value["arm"] != row["arm"] or value["state_pass"] is not True or \
                value["timing_kind"] != "declared_prediction":
            raise ValueError("observation identity or evidence kind changed")
        for field in ("cycles", "read_bytes", "write_bytes") + LEDGERS:
            if type(value[field]) is not int or value[field] < 0:
                raise ValueError("invalid nonnegative ledger: " + field)
        if value["cache_updates"] + value["ddr_updates"] != row["updates"] or \
                value["row_reads"] != row["updates"] or len(row["state_sha256"]) != 64 or \
                any(c not in "0123456789abcdef" for c in row["state_sha256"]):
            raise ValueError("work/state ledger does not close")
        if value["cycles"] == 0 and (row["updates"] or row["arm"] in ("original", "cached_hot")):
            raise ValueError("cache preload/writeback cannot have zero time")
    comparisons = []
    for latency in (64, 128):
        for name, count, _ in CASES:
            rows = [keyed[(latency, name, arm)] for arm in ARMS]
            if len({r["state_sha256"] for r in rows}) != 1 or any(
                    len({r["observation"][field] for r in rows}) != 1 for field in LEDGERS):
                raise ValueError("logical state/work differ across cached-G arms")
            values = {r["arm"]: r["observation"] for r in rows}
            cached, direct = values["cached_hot"], values["parallel_hot"]
            expected_reads = direct["read_bytes"] - direct["cache_updates"] * 64 + HOT_TRANSFER_BYTES
            expected_writes = direct["write_bytes"] - direct["cache_updates"] * 64 + HOT_TRANSFER_BYTES
            if cached["read_bytes"] != expected_reads or cached["write_bytes"] != expected_writes:
                raise ValueError("full-cache transfer or unchanged cold traffic was omitted")
            if any(cached[field] != values["original"][field] for field in ("read_bytes", "write_bytes")):
                raise ValueError("cached and original physical traffic differ")
            cycles = {arm: value["cycles"] for arm, value in values.items()}
            comparisons.append({"latency": latency, "case": name, "updates": count,
                "cycles": cycles, "cached_over_legacy_original": cycles["cached_hot"] / cycles["original"],
                "cached_over_direct_owners": cycles["cached_hot"] / cycles["parallel_hot"]
                    if cycles["parallel_hot"] else None})
    nonempty = [r for r in comparisons if r["updates"]]
    return {"comparisons": comparisons, "old_checkpoint_exact_rows": len(previous["rows"]),
        "legacy_reference_no_more_than_ten_percent_slower":
            all(r["cached_over_legacy_original"] <= 1.1 for r in nonempty),
        "legacy_reference_within_ten_percent_both_directions":
            all(0.9 <= r["cached_over_legacy_original"] <= 1.1 for r in nonempty)}
