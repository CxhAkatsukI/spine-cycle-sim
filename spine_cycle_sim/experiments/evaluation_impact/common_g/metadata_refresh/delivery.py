"""Recheck frozen raw host evidence without promoting it to device execution."""

import json

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from ..search_pipeline.synthesis import unchanged
from . import analysis, preparation
from .study import POLICY


def validate(attempt):
    report = json.loads((attempt / "results.json").read_text())
    if report["status"] != analysis.PASS or report["errors"] or any(
            report.get(key) is not False for key in preparation.CLAIMS) or report["policy"] != POLICY or \
            report["contract"] != json.loads((attempt / "contract.json").read_text()) or \
            report["contract"]["case"] != preparation.CASE:
        raise ValueError("metadata host evidence incomplete or claim changed")
    unchanged(report["pins"])
    if report["binary_sha256"] != sha256_file(attempt / "probe"):
        raise ValueError("metadata host binary changed")
    if [step["label"] for step in report["steps"]] != ["compile", "model", "stale"]:
        raise ValueError("metadata preflight execution order changed")
    for step in report["steps"]:
        label = step["label"]
        if {key: value for key, value in step.items() if key != "label"} != json.loads(
                (attempt / "raw" / (label + ".resources.json")).read_text()) or \
                step["exit_code"] != (1 if label == "stale" else 0) or step["stop_reason"] != "process_exit" or \
                step["cleanup_snapshot_error"] or step["tree_memory_gib"] != 2 or step["reserve_gib"] != 24:
            raise ValueError("metadata preflight bounded resource record changed")
    def raw(label, stream):
        return (attempt / "raw" / (label + "." + stream + ".txt")).read_text()
    if any(raw("compile", stream).strip() for stream in ("stdout", "stderr")) or \
            report["model"] != analysis.analyze(raw("model", "stdout"), raw("model", "stderr")) or \
            report["negative"] != analysis.stale_rejection(raw("stale", "stdout"), raw("stale", "stderr")):
        raise ValueError("metadata raw numerical evidence changed")
    events = dict(line.split() for line in report["memory_events_after"].splitlines())
    if any(events.get(key) != "0" for key in ("oom", "oom_kill", "oom_group_kill")) or \
            report["admission"].get("admitted") is not True or report["admission"].get("policy") != \
            "full_finite_budgets_plus_reserve_atomic_lease":
        raise ValueError("metadata preflight lacks safe atomic admission")
    return report
