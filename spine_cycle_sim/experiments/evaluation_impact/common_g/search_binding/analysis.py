"""Validate all binding modes and their finite-channel search ledgers."""

import json
import re

from .preparation import KEYS, MATRIX

PASS = re.compile(r"SEARCH_PIPELINE_PASS updates=(\d+) probes=(\d+) stalled=([01]) "
                  r"channels=339 output_blocked=\d+ host_vendor_keep_bits=16")


def analyze(stdout: str):
    controls, rows, pending = [], [], None
    for line in stdout.splitlines():
        if line.startswith("SEARCH_PIPELINE_PASS"):
            match = PASS.fullmatch(line)
            if match is None or pending is not None:
                raise ValueError("malformed or unpaired finite-channel control")
            pending = tuple(map(int, match.groups()))
        elif line.startswith("SEARCH_BINDING_ROW "):
            row = json.loads(line.removeprefix("SEARCH_BINDING_ROW "))
            if set(row) != {*KEYS, "probes"} or any(type(value) is not int for value in row.values()):
                raise ValueError("unexpected binding row schema")
            if pending != (row["updates"], row["probes"], row["stalled"]):
                raise ValueError("binding row lacks matching finite-channel control")
            controls.append(pending)
            rows.append(row)
            pending = None
    if pending is not None or [tuple(row[key] for key in KEYS) for row in rows] != list(MATRIX):
        raise ValueError("missing, duplicate, reordered, or undeclared binding execution")
    work = {}
    for row in rows:
        key = (row["generation"], row["updates"], row["same_key"])
        probes = row["probes"]
        if probes < 0 or (row["updates"] == 0 and probes != 0):
            raise ValueError("invalid probe count")
        if work.setdefault(key, probes) != probes:
            raise ValueError("alias or backpressure changed search work")
    return {"calls": len(rows), "metadata_generations": 2, "alias_modes": 3,
            "finite_channels": 339, "rows": rows,
            "hardware_timing_admitted": False, "production_baseline_admitted": False,
            "publication_match_admitted": False,
            "claim": "eleven_argument_compact_search_source_binding_not_RTL_or_complete_G"}
