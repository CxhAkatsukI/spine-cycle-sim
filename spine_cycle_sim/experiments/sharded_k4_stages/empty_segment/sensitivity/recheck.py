"""Reconstruct sensitivity admission from pinned inputs, commands and full states."""

import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_partition_round.delivery import recheck as recheck_basis
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from ..production_validation import recheck as recheck_production, require_execution
from .analysis import ARMS, admit, matrix
from .study import DOC, HARNESS, command


def check_commands(root: Path, run: Path, report: dict, basis: dict) -> None:
    binary = run / "build/routed_regraph_empty_segment_round"
    expected = [
        ("configure", ["cmake", "-S", str(root / HARNESS), "-B", str(run / "build"),
                       "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_TESTING=OFF"], 6, 300),
        ("build", ["cmake", "--build", str(run / "build"), "--target",
                   "routed_regraph_empty_segment_round", "-j2"], 6, 600),
        ("compiler", ["c++", "--version"], 1, 30)]
    for frozen in basis["cases"]:
        mode, latency, reverse = (frozen[k] for k in ("mode", "latency", "reverse"))
        geometry = next(item for item in basis["inputs"] if item["mode"] == mode)
        for arm in ARMS:
            label = f"{mode}_lat{latency}_reverse{reverse}_empty{arm}"
            expected.append((label, [str(binary), geometry["path"], str(run / "states" / label),
                                    str(latency), str(reverse), "100000000", str(arm)], 3, 180))
    if len(report["runs"]) != len(expected):
        raise ValueError("raw sensitivity command matrix differs")
    for record, (label, argv, budget, timeout) in zip(report["runs"], expected, strict=True):
        resource = json.loads((run / "raw" / (label + ".resources.json")).read_text())
        if (record["label"] != label or resource["command"] != argv or resource["cwd"] != str(root)
                or not same_typed(resource, {k: v for k, v in record.items() if k != "label"})
                or not same_typed(resource["host_affinity"], report["cpu_affinity"])):
            raise ValueError("raw command or resource record differs: " + label)
        require_execution(resource, budget=budget, timeout=timeout)
    if (report["executor"] != {"path": str(binary), "sha256": sha256_file(binary)}
            or sha256_file(run / "build/CMakeCache.txt") != report["cmake_cache_sha256"]):
        raise ValueError("standalone executable or compiler configuration differs")
    watchdog = json.loads(run.with_name(run.name + "_watchdog.resources.json").read_text())
    require_execution(watchdog, budget=8, timeout=1800)
    expected_outer = command(report["python_executable"], run, Path(report["basis"]["path"]).parent,
                             Path(report["production"]["path"]).parent)
    if (watchdog["command"] != expected_outer or watchdog["cwd"] != str(root)
            or not same_typed(watchdog["host_affinity"], report["cpu_affinity"])):
        raise ValueError("outer watchdog command or affinity differs")


def recheck(root: Path, run: Path) -> dict:
    report = json.loads((run / "results.json").read_text())
    basis_path = Path(report["basis"]["path"])
    committed = root / DOC / "matched_a4/sssp_partition_round/evidence/results.json"
    if (report["schema_version"] != 2 or sha256_file(basis_path) != report["basis"]["sha256"]
            or sha256_file(committed) != report["basis"]["sha256"]
            or report["scope"] != "single_parameter_sensitivity_not_routed_timing_or_production_calibration"):
        raise ValueError("sensitivity basis or scope differs")
    basis = recheck_basis(root, basis_path.parent)
    for key in ("model", "memory", "boundary", "inputs"):
        if not same_typed(report[key], basis[key]):
            raise ValueError("frozen numerical contract differs: " + key)
    production = Path(report["production"]["path"])
    gate = recheck_production(production.parent)
    if (sha256_file(production) != report["production"]["sha256"]
            or not same_typed(report["production"]["xo"], gate["report"]["xo"])):
        raise ValueError("production prerequisite differs")
    pins = report["sources"]
    if len({item["path"] for item in pins}) != len(pins):
        raise ValueError("duplicate source snapshot")
    for pin in pins:
        relative = Path(pin["path"])
        snapshot = run / "sources" / relative
        if (relative.is_absolute() or ".." in relative.parts or snapshot.is_symlink()
                or sha256_file(snapshot) != pin["sha256"]
                or sha256_file(root / relative) != pin["sha256"]):
            raise ValueError("source snapshot or current replay source differs: " + str(relative))
    plugin_hash = sha256_file(root / "build/sst/libspine_cycle.so")
    if (plugin_hash != report["default_plugin_sha256_before"]
            or plugin_hash != report["default_plugin_sha256_after"]
            or plugin_hash != basis["default_plugin_sha256_after"]):
        raise ValueError("default plugin changed")
    check_commands(root, run, report, basis)
    if len(report["cases"]) != 12:
        raise ValueError("sensitivity case matrix differs")
    observed = []
    for frozen in basis["cases"]:
        mode, latency, reverse = (frozen[k] for k in ("mode", "latency", "reverse"))
        geometry = next(item for item in basis["inputs"] if item["mode"] == mode)
        for arm in ARMS:
            label = f"{mode}_lat{latency}_reverse{reverse}_empty{arm}"
            prefix = run / "raw" / label
            if prefix.with_suffix(".stderr.txt").read_bytes():
                raise ValueError("raw case emitted stderr")
            observed.append({"mode": mode, "latency": latency, "reverse": reverse, "empty_exit": arm,
                **admit(prefix.with_suffix(".stdout.txt").read_text(), run / "states" / label,
                        geometry, frozen, arm)})
    admitted = matrix(observed)
    if (not same_typed(observed, report["cases"]) or not same_typed(admitted, report["admission"])
            or report["status"] != admitted["status"]):
        raise ValueError("rederived sensitivity admission differs")
    return report
