"""Reject incomplete or ambiguous candidate matrices before delivery."""

from .preparation import CASES


def validate_matrix(report):
    expected = {(latency, name, count, arm) for latency in (64, 128)
                for name, count, _ in CASES for arm in ("original", "current", "parallel")}
    actual = [(row["latency"], row["case"], row["updates"], row["arm"]) for row in report["rows"]]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("missing, duplicate or undeclared candidate matrix row")
    declared = [tuple(item) for item in report["matrix"]]
    if len(declared) != len(expected) or set(declared) != expected:
        raise ValueError("declared candidate matrix differs from required scope")
    if report.get("errors"):
        raise ValueError("candidate matrix contains failed executions")
    for row in report["rows"]:
        observation = row["observation"]
        if observation["arm"] != row["arm"] or observation["state_pass"] is not True or \
                observation["timing_kind"] != "declared_prediction":
            raise ValueError("candidate identity, correctness or evidence kind mismatch")
        for field in ("cycles", "read_bytes", "write_bytes", "cache_updates", "ddr_updates",
                      "row_reads", "binary_probes"):
            if type(observation[field]) is not int or observation[field] < 0:
                raise ValueError("invalid nonnegative integer ledger: " + field)
        if observation["cache_updates"] + observation["ddr_updates"] != row["updates"] or \
                observation["row_reads"] != row["updates"]:
            raise ValueError("candidate update work does not close")
        if row["updates"] and not observation["cycles"]:
            raise ValueError("nonempty candidate has no execution time")
        if len(row["state_sha256"]) != 64:
            raise ValueError("missing complete-state identity")
    for field in ("hardware_timing_admitted", "publication_match_admitted", "production_baseline_admitted"):
        if report.get(field) is not False:
            raise ValueError("unsupported candidate promotion: " + field)
