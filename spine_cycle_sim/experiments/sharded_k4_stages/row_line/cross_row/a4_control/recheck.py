"""Re-admit all raw results without depending on their original filesystem paths."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.layout_audit import audit
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ...evidence import bounded
from .analysis import admit, matrix
from .contract import BASIS_SHA, BOUNDARY, LIMITS, STATUS, VERSION, label, profile, run_specs
from .execution import case_command, commands
from .preparation import changes


def read(path):
    return json.loads(path.read_text())


def recheck(run):
    manifest, report = read(run / "manifest.json"), read(run / "results.json")
    if (report["manifest_sha256"] != sha256_file(run / "manifest.json") or report["status"] != STATUS
            or manifest["version"] != VERSION or manifest["boundary"] != BOUNDARY
            or not same_typed(manifest["limits"], LIMITS)
            or manifest["hardware_timing_admitted"] is not False
            or manifest["strict_resource_match_admitted"] is not False):
        raise ValueError("cross-row scope or manifest differs")
    basis = read(run / "bases/results.json")
    old = read(run / "bases/manifest.json")
    if (sha256_file(run / "bases/results.json") != BASIS_SHA
            or sha256_file(run / "bases/manifest.json") != basis["manifest_sha256"]
            or manifest["basis_report_sha256"] != BASIS_SHA
            or manifest["basis_manifest_sha256"] != basis["manifest_sha256"]
            or any(not same_typed(manifest[key], old[key]) for key in ("inputs", "layout_audit", "memory"))
            or manifest["historical_model"] != old["model"]):
        raise ValueError("historical basis or workload differs")
    names = [item["path"] for item in manifest["sources"]]
    if (len(names) != len(set(names)) or any(Path(name).is_absolute() or ".." in Path(name).parts for name in names)
            or {str(p.relative_to(run / "sources")) for p in (run / "sources").rglob("*") if p.is_file()} != set(names)):
        raise ValueError("frozen source set differs")
    for item in manifest["sources"]:
        path = run / "sources" / item["path"]
        if path.is_symlink() or sha256_file(path) != item["sha256"]:
            raise ValueError("executed source differs")
    if (changes(run / "sources", run / "pre_edit_source.tar.gz", read(run / "pre_edit_source_index.json"))
            != manifest["declared_source_changes"]
            or not same_typed(profile(run / "sources"), manifest["profile"])):
        raise ValueError("numerical version declaration differs")
    for geometry in manifest["inputs"]:
        directory = run / "inputs" / geometry["mode"]
        if {p.name for p in directory.iterdir()} != {Path(item["path"]).name for item in geometry["files"]}:
            raise ValueError("input file set differs")
        for item in geometry["files"]:
            if sha256_file(directory / Path(item["path"]).name) != item["sha256"]:
                raise ValueError("complete input differs")
        original = next(c for c in basis["cases"] if c["mode"] == geometry["mode"] and c["arm"] == "original")
        if sha256_file(run / "expected" / (geometry["mode"] + ".u32le")) != original["outputs"][0]["sha256"]:
            raise ValueError("complete oracle differs")
    if audit(run / "inputs/cold", manifest["inputs"][0]["vertices"]) != manifest["layout_audit"]:
        raise ValueError("independent PMA layout differs")
    origin, root = Path(manifest["output"]), Path(manifest["root"])
    specs = commands(root, origin) + [(label(*spec), case_command(origin, *spec), LIMITS["run_tree_gib"],
                                      LIMITS["run_timeout_seconds"]) for spec in run_specs()]
    if len(report["runs"]) != len(specs):
        raise ValueError("raw execution matrix incomplete")
    for row, (name, command, budget, timeout) in zip(report["runs"], specs, strict=True):
        record = bounded(run / "raw" / (name + ".resources.json"), command, str(root), timeout, budget)
        if not same_typed(row, {"label": name, **record}):
            raise ValueError("stored execution differs from raw record")
    if (run / "raw/compiler.stdout.txt").read_bytes() != (run / "bases/compiler.txt").read_bytes():
        raise ValueError("compiler identity differs")
    for item in report["build_files"]:
        if sha256_file(run / item["relative"]) != item["sha256"]:
            raise ValueError("binary or build configuration differs")
    cases = []
    for spec in run_specs():
        mode, latency, reverse, arm = spec
        name = label(*spec)
        if (run / "raw" / (name + ".stderr.txt")).read_bytes():
            raise ValueError("control emitted stderr")
        geometry = next(item for item in manifest["inputs"] if item["mode"] == mode)
        result = admit((run / "raw" / (name + ".stdout.txt")).read_text(), run / "states" / name,
                       geometry, basis, spec)
        result["outputs"] = [{**item, "path": str(origin / "states" / name / Path(item["path"]).name)}
                             for item in result["outputs"]]
        cases.append({"mode": mode, "latency": latency, "reverse": reverse, "arm": arm, **result})
    if (not same_typed(cases, report["cases"]) or not same_typed(matrix(cases), report["admission"])
            or report["default_plugin_sha256_after"] != manifest["default_plugin_sha256_before"]):
        raise ValueError("raw conclusion or default plugin preservation differs")
    return report
