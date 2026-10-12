"""Re-admit frozen raw results without loading a different numerical version."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.layout_audit import audit
from .analysis import admit, matrix
from .contract import BASES, BOUNDARY, EXTRACTION_SHA, HARNESS_CHANGE, LIMITS, NUMERICAL_CHANGES, STATUS, label, run_specs
from .execution import commands, case_command


def read(path):
    return json.loads(path.read_text())


def recheck(run: Path) -> dict:
    report = read(run / "results.json")
    manifest = read(run / "manifest.json")
    if (report["manifest_sha256"] != sha256_file(run / "manifest.json")
            or manifest["boundary"] != BOUNDARY or not same_typed(manifest["limits"], LIMITS)
            or manifest["hardware_timing_admitted"] is not False
            or manifest["strict_resource_match_admitted"] is not False
            or report["status"] != STATUS or sha256_file(run / "pre_extraction.tar.gz") != EXTRACTION_SHA):
        raise ValueError("frozen scope or source snapshot differs")
    for item in manifest["sources"]:
        if sha256_file(run / "sources" / item["path"]) != item["sha256"]:
            raise ValueError("archived executed source differs")
    reports = {}
    for name, (_, expected) in BASES.items():
        if sha256_file(run / "bases" / (name + ".json")) != expected:
            raise ValueError("frozen historical basis differs")
        reports[name] = read(run / "bases" / (name + ".json"))
    changes = []
    for name in ("numerical", "partition", "sensitivity"):
        observed = []
        for item in reports[name]["sources"]:
            current = sha256_file(run / "sources" / item["path"])
            if current != item["sha256"]:
                observed.append(item["path"])
                changes.append({"basis": name, "path": item["path"], "before_sha256": item["sha256"],
                                "after_sha256": current})
        expected = NUMERICAL_CHANGES if name == "numerical" else (
            NUMERICAL_CHANGES | {HARNESS_CHANGE} if name == "sensitivity" else set())
        if set(observed) != expected:
            raise ValueError("archived undeclared numerical version change")
    if (changes != manifest["declared_source_changes"] or manifest["inputs"] != reports["partition"]["inputs"]
            or manifest["model"] != reports["partition"]["model"]
            or manifest["memory"] != reports["partition"]["memory"]):
        raise ValueError("frozen inputs or numerical version declaration differs")
    for geometry in manifest["inputs"]:
        mode = geometry["mode"]
        if geometry != next(row for row in reports["partition"]["inputs"] if row["mode"] == mode):
            raise ValueError("frozen geometry differs")
        if {path.name for path in (run / "inputs" / mode).iterdir()} != {Path(item["path"]).name for item in geometry["files"]}:
            raise ValueError("input file set differs")
        for item in geometry["files"]:
            if sha256_file(run / "inputs" / mode / Path(item["path"]).name) != item["sha256"]:
                raise ValueError("complete input differs")
        expected = next(case for case in reports["partition"]["cases"] if case["mode"] == mode)["outputs"][0]
        if sha256_file(run / "expected" / (mode + ".u32le")) != expected["sha256"]:
            raise ValueError("frozen complete oracle differs")
    layout = audit(run / "inputs/cold", manifest["inputs"][0]["vertices"])
    if not same_typed(layout, manifest["layout_audit"]) or layout != reports["partition"]["layout_audit"]:
        raise ValueError("independent PMA work differs")
    origin = Path(manifest["output"])
    root = Path(manifest["root"])
    expected_runs = commands(root, origin) + [
        (label(*spec), case_command(origin, *spec), LIMITS["run_tree_gib"], LIMITS["run_timeout_seconds"])
        for spec in run_specs()]
    if len(report["runs"]) != len(expected_runs):
        raise ValueError("raw command matrix incomplete")
    for row, (name, command, budget, timeout) in zip(report["runs"], expected_runs, strict=True):
        prefix = run / "raw" / name
        observed = read(prefix.with_suffix(".resources.json"))
        if (row["label"] != name or not same_typed(observed, {k: v for k, v in row.items() if k != "label"})
                or observed["command"] != command or observed["cwd"] != str(root)
                or observed["tree_memory_gib"] != budget or observed["reserve_gib"] != 16
                or observed["timeout_seconds"] != timeout or observed["exit_code"] != 0
                or observed["stop_reason"] != "process_exit" or observed["cleanup_snapshot_error"] is not None
                or observed["peak_tree_rss_kib"] > budget * 1024**2
                or observed["minimum_available_bytes"] < 16 * 1024**3):
            raise ValueError("command or process-tree contract differs")
    if (run / "raw/compiler.stdout.txt").read_text() != reports["numerical"]["compiler_version"]:
        raise ValueError("compiler differs from numerical basis")
    for item in report["build_files"]:
        if sha256_file(run / item["relative"]) != item["sha256"]:
            raise ValueError("compiled executable or build flags differ")
    cases = []
    for mode, latency, reverse, arm in run_specs():
        name = label(mode, latency, reverse, arm)
        geometry = next(item for item in manifest["inputs"] if item["mode"] == mode)
        frozen = next(item for item in reports["partition"]["cases"]
                      if (item["mode"], item["latency"], item["reverse"]) == (mode, latency, reverse))
        skip = next(item for item in reports["sensitivity"]["cases"]
                    if (item["mode"], item["latency"], item["reverse"], item["empty_exit"]) == (mode, latency, reverse, 0))
        if (run / "raw" / (name + ".stderr.txt")).read_bytes():
            raise ValueError("model control emitted stderr")
        result = admit((run / "raw" / (name + ".stdout.txt")).read_text(), run / "states" / name,
                       geometry, frozen, skip, arm, layout)
        # Raw command records retain their original paths when a package is relocated.
        result["outputs"] = [{**item, "path": str(origin / "states" / name / Path(item["path"]).name)}
                             for item in result["outputs"]]
        cases.append({"mode": mode, "latency": latency, "reverse": reverse, "arm": arm, **result})
    if not same_typed(cases, report["cases"]) or not same_typed(matrix(cases), report["admission"]):
        raise ValueError("raw complete result or admission differs")
    if report["default_plugin_sha256_after"] != manifest["default_plugin_sha256_before"]:
        raise ValueError("default plugin preservation differs")
    return report
