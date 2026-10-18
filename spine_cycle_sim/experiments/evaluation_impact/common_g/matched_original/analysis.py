"""Validate deterministic translation facts, not board or performance claims."""

import json

STATUS = "MATCHED_G_HOST_PREFLIGHT_PASS_NOT_BOARD_OR_PERFORMANCE"
CLAIMS = ("board_programmed", "hardware_timing_measured", "original_g_performance_match",
          "publication_performance_match", "final_figures_admitted")


def expected(row):
    facts = row["facts"]
    segments = max(1, facts["segments"])
    even, odd = (segments + 1) // 2, segments // 2
    words = 2 * 131072 * 16 + 16 * sum(count if count > 131072 else 1 for count in (even, odd))
    return {"status": "PASS_NOT_BOARD", **{key: facts[key] for key in
            ("vertices", "segments", "updates", "route_updates")}, "checked_words": words,
            "identity_mapping": True, "unit_weight": True, "same_logical_slots": True, "same_update_order": True}


def inspect(stdout, stderr, row):
    lines = stdout.splitlines()
    if stderr or len(lines) != 1 or not lines[0].startswith("MATCHED_G_MODEL "):
        raise ValueError("matched-G model diagnostics")
    observed = json.loads(lines[0].removeprefix("MATCHED_G_MODEL "))
    # JSON equality alone admits true == 1; require the complete typed structure.
    if json.dumps(observed, sort_keys=True) != json.dumps(expected(row), sort_keys=True):
        raise ValueError("matched-G same-input/state facts differ")
    return observed
