"""Check banked handoff separately from single-window performance retention."""

import json

from ..common_g.finite_search.preparation import matrix
from ..common_g.finite_search.study import settings
from ..common_g.search_diagnostics.analysis import key
from .analysis import FIXTURES, MEASUREMENTS

STATUS = "FINITE_BANKED_HANDOFF_CORRECTNESS_PASS_NOT_BASELINE_ADMISSION"


def analyze(stdout):
    arms = {"HANDOFF_RESULT": {}, "BANKED_HANDOFF_RESULT": {}}
    for line in stdout.splitlines():
        tag, _, body = line.partition(" ")
        if tag not in arms:
            continue
        row = json.loads(body)
        identity = (row["vertices"], row["cache_segments"], row["empty"], row["reverse"])
        if identity in arms[tag] or type(row["empty"]) is not bool or type(row["reverse"]) is not bool:
            raise ValueError("duplicate or invalid banked handoff identity")
        if row["physical_handoff_pass"] is not True or row["performance_admitted"] is not False:
            raise ValueError("banked correctness cannot admit performance")
        if any(type(row[name]) is not int or row[name] < 0 for name in MEASUREMENTS) or \
                min(row[name] for name in MEASUREMENTS if name != "g_cycles") <= 0 or \
                (not row["empty"] and row["g_cycles"] == 0):
            raise ValueError("banked handoff omitted work")
        arms[tag][identity] = row
    expected = {(v, c, e, reverse) for v, c, e in FIXTURES for reverse in (False, True)}
    old, new = arms.values()
    if set(old) != {identity for identity in expected if not identity[-1]} or set(new) != expected:
        raise ValueError("incomplete banked handoff matrix")
    for identity, row in new.items():
        reference = old[identity[:-1] + (False,)]
        if any(row[name] != reference[name] for name in MEASUREMENTS if name != "g_cycles"):
            raise ValueError("finite G changed R time/work/traffic")
        other = new[identity[:-1] + (not identity[-1],)]
        if any(row[name] != other[name] for name in MEASUREMENTS):
            raise ValueError("banked registration order changed observations")
    return {"status": STATUS, "finite_rows": list(new.values()), "direct_rows": list(old.values()),
            "r_time_work_traffic_exact": True, "registration_order_exact": True,
            "finite_search_sharded_correctness": True, "full_cached_sharded_candidate": False,
            "baseline_admitted": False, "hardware_timing_admitted": False,
            "publication_match_admitted": False, "host_window_measured": False}


def replay(report, previous):
    expected = set(matrix())
    if previous["status"] != "G_FINITE_SEARCH_PREDICTIONS_CHECKED" or report["errors"] or \
            len(report["rows"]) != len(expected) or len(previous["rows"]) != len(expected) or \
            set(map(key, report["rows"])) != expected or set(map(key, previous["rows"])) != expected:
        raise ValueError("complete 228-row before/after matrix required")
    for name, value in settings().items():
        if report.get(name) != value or previous.get(name) != value:
            raise ValueError("bank routing replay changed declared configuration: " + name)
    old = {key(row): row for row in previous["rows"]}
    for row in report["rows"]:
        if any(row[name] != old[key(row)][name] for name in ("observation", "state_sha256", "diagnostics")):
            raise ValueError("bank routing changed previous G numerical results")
    return {"exact_replayed_rows": len(expected), "baseline_admitted": False,
            "hardware_timing_admitted": False}
