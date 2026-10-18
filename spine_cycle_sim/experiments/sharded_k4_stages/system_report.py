"""Strict extended routed-system matrices; frozen 13-row reports stay separate."""

import re

BASE_REPORT = ("PASS: 21 whole routed SSSP cases; full state, source replicas, padding, "
               "scheduling and traffic; 12 admission rejections PASS")
LINE_REPORT = "PASS: 9 whole-line/reference executions; complete oracle, replicas and traffic checks"
PAIR_BEGIN = "BEGIN: two-pair source topology"
PAIR_REPORT = "PASS: 12 pairwise/reference executions and invalid-topology rejection"
KEYS = ("vertices", "reverse", "stop", "pressure", "fixed", "limit", "independent",
        "stream_depth", "row_line_reads", "source_topology", "rounds", "failed")
RECORD = re.compile(
    r"case " + " ".join(name + r"=(?P<" + name + r">\d+)" for name in (
        "vertices", "reverse", "stop", "pressure", "fixed", "limit", "independent",
        "stream_depth", "rounds", "failed", "cycles", "parents", "beats")) +
    r"(?: row_line_reads=(?P<row_line_reads>1))?"
    r"(?: source_topology=(?P<source_topology>two_pairwise))?")


def shape(vertices, *, reverse=0, stop=1, pressure=0, fixed=0, limit=128,
          independent=0, stream_depth=16, row_line_reads=0, source_topology="four_dedicated",
          rounds=4, failed=0):
    return (vertices, reverse, stop, pressure, fixed, limit, independent, stream_depth,
            row_line_reads, source_topology, rounds, failed)


def base_matrix():
    expected = set()
    for vertices, pressure, rounds in ((129, 0, 4), (65569, 0, 4), (262273, 0, 5), (129, 1, 4)):
        for reverse in (0, 1):
            expected.add(shape(vertices, reverse=reverse, pressure=pressure, rounds=rounds))
    expected.update(shape(129, reverse=reverse, stop=0) for reverse in (0, 1))
    expected.update((shape(129, rounds=1), shape(129, fixed=2, rounds=2),
                     shape(129, limit=1, rounds=1, failed=1)))
    for vertices, pressure, rounds in ((129, 1, 4), (262273, 0, 5)):
        expected.update(shape(vertices, pressure=pressure, rounds=rounds, independent=1,
                              reverse=reverse) for reverse in (0, 1))
    for depth in (1, 32):
        expected.update(shape(65569, pressure=1, independent=1, stream_depth=depth,
                              reverse=reverse) for reverse in (0, 1))
    return expected


def line_matrix():
    expected = set()
    for vertices, pressure, rounds in ((129, 1, 4), (65569, 0, 4), (262273, 0, 5)):
        for reverse, row_lines in ((0, 0), (0, 1), (1, 1)):
            expected.add(shape(vertices, pressure=pressure, rounds=rounds, independent=1,
                               stream_depth=32, reverse=reverse, row_line_reads=row_lines))
    return expected


def pair_matrix():
    expected = set()
    for vertices, pressure, depth, row_lines, rounds in ((129, 0, 16, 0, 4),
            (65569, 1, 1, 1, 4), (262273, 0, 32, 1, 5)):
        for reverse, topology in ((0, "four_dedicated"), (0, "two_pairwise"), (1, "two_pairwise")):
            expected.add(shape(vertices, pressure=pressure, rounds=rounds, independent=1,
                               stream_depth=depth, reverse=reverse, row_line_reads=row_lines,
                               source_topology=topology))
    extra = dict(independent=1, source_topology="two_pairwise", rounds=1)
    expected.update((shape(129, pressure=1, stream_depth=1, row_line_reads=1, **extra),
                     shape(129, fixed=2, **{**extra, "rounds": 2}),
                     shape(129, limit=1, failed=1, **extra)))
    return expected


def parse_group(lines, expected):
    rows = []
    for line in lines:
        match = RECORD.fullmatch(line)
        if match is None:
            raise ValueError("invalid extended whole-system execution record")
        raw = match.groupdict()
        row = {key: int(value or 0) for key, value in raw.items() if key != "source_topology"}
        row["source_topology"] = raw["source_topology"] or "four_dedicated"
        rows.append(row)
    observed = {tuple(row[key] for key in KEYS) for row in rows}
    if observed != expected or len(observed) != len(rows):
        raise ValueError("extended system gate changed or duplicated its predeclared matrix")
    for row in rows:
        if row["cycles"] <= 0 or row["parents"] <= 0 or row["beats"] < row["parents"]:
            raise ValueError("empty or inconsistent whole-system transaction record")
        if row["reverse"] and {**row, "reverse": 0} not in rows:
            raise ValueError("registration-order execution records differ")
    return rows


def sections(text):
    lines = text.strip().splitlines()
    if len(lines) not in (32, 46) or lines[21] != BASE_REPORT or lines[31] != LINE_REPORT:
        raise ValueError("complete extended system gate and rejection summaries required")
    groups = [(lines[:21], base_matrix()), (lines[22:31], line_matrix())]
    if len(lines) == 46:
        if lines[32] != PAIR_BEGIN or lines[-1] != PAIR_REPORT:
            raise ValueError("complete pairwise topology and invalid-topology gate required")
        groups.append((lines[33:45], pair_matrix()))
    return groups


def require_extended_report(text):
    return [row for lines, expected in sections(text) for row in parse_group(lines, expected)]


def extended_scope(text):
    rows = require_extended_report(text)
    paired = len(rows) == 42
    return {"report_version": "source_pairs_v1" if paired else "whole_lines_v1",
            "converged_executions": sum(not row["fixed"] and not row["failed"] for row in rows),
            "fixed_round_executions": sum(bool(row["fixed"]) for row in rows),
            "expected_limit_failures": sum(row["failed"] for row in rows),
            "admission_rejections": 13 if paired else 12}
