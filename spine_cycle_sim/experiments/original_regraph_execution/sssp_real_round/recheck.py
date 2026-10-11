"""Re-admit frozen raw results without executing or changing the numerical model."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import sha256_file
from spine_cycle_sim.experiments.original_regraph_inputs.analysis import analyze_topology
from spine_cycle_sim.experiments.original_regraph_inputs.preparation import inspect_graph
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.shared_workloads import load_slice
from .analysis import LATENCIES, MODES, admit_matrix, admit_round
from .evidence import apply_schedule
from .preparation import ACTIVE, overlay, read_words
from .study import SSSP_TARGETS, TARGETS, admitted_probe


def identity(item: dict, root: Path = Path("/")) -> None:
    path = root / item["path"]
    if path.is_symlink() or sha256_file(path) != item["sha256"]:
        raise ValueError("frozen file changed: " + str(path))


def steps(report: dict) -> dict[str, dict]:
    names = ["configure", "compiler", "build", *SSSP_TARGETS,
             *("legacy_" + name for name in ("gather_tests", "frontend_tests", "state_tests", "iteration_tests")),
             "old_source_comparison", "legacy_source_comparison", "old_state_comparison", "legacy_state_comparison",
             "whole_skewed_sources", "whole_boundary_ring", "whole_amazon", "author_layout", "pr_arithmetic_rejection",
             *(f"{mode}_lat{latency}_reverse{reverse}" for mode in MODES for latency in LATENCIES for reverse in (0, 1))]
    rows = report["runs"]
    observed = [Path(row["stdout"]).name.removesuffix(".stdout.txt") for row in rows]
    if observed != names:
        raise ValueError("raw execution matrix missing, duplicated or reordered")
    for name, row in zip(names, rows, strict=True):
        if (row["timed_out"] is not False or type(row["exit_code"]) is not int
                or row["exit_code"] != int(name == "pr_arithmetic_rejection")
                or row["memory_limit_gib"] != 8 or row["reserve_gib"] != 16
                or row["available_before_bytes"] < 24 * 1024**3):
            raise ValueError("unexpected failure or memory boundary: " + name)
        resource = Path(str(row["stdout"]).removesuffix(".stdout.txt") + ".resources.json")
        if not same_typed(json.loads(resource.read_text()), row):
            raise ValueError("raw resource record changed: " + name)
    return dict(zip(names, rows, strict=True))


def legacy(report: dict, raw: dict, components: Path, whole: Path) -> list[dict]:
    references = []
    expected = ["gather_tests", "frontend_tests", "state_tests", "iteration_tests", "source_comparison", "state_comparison"]
    if ([item["target"] for item in report["legacy_components"]["results"]] != expected
            or report["legacy_components"]["default_component_and_full_source_comparison_outputs_identical"] is not True):
        raise ValueError("legacy component/source comparison matrix changed")
    for directory, admitted in ((components, report["legacy_components"]), (whole, report["legacy_whole"])):
        identity({"path": str(directory / "baseline.json"), "sha256": admitted["baseline_sha256"]})
    baseline = json.loads((components / "baseline.json").read_text())
    for item in report["legacy_components"]["results"]:
        new = raw["legacy_" + item["target"]]
        old = next((row for row in baseline["runs"] if row["target"] == item["target"]),
                   raw.get("old_" + item["target"]))
        if item["identical"] is not True or sha256_file(Path(new["stdout"])) != item["stdout_sha256"]:
            raise ValueError("legacy component output changed")
        for stream in ("stdout", "stderr"):
            if Path(old[stream]).read_bytes() != Path(new[stream]).read_bytes():
                raise ValueError("old/new component outputs differ")
        for capture in item.get("original_captures", []):
            identity(capture)
            references.append(capture)
    frozen = json.loads((whole / "baseline.json").read_text())
    if [row["case"] for row in report["legacy_whole"]["cases"]] != ["skewed_sources", "boundary_ring", "amazon"]:
        raise ValueError("whole-path legacy matrix changed")
    for old, new in zip(frozen["runs"], report["legacy_whole"]["cases"], strict=True):
        row = raw["whole_" + new["case"]]
        if old["exit_code"] or old["timed_out"] or not new["full_outputs_cycles_counters_identical"]:
            raise ValueError("legacy whole-path gate failed")
        for stream in ("stdout", "stderr"):
            if Path(old[stream]).read_bytes() != Path(row[stream]).read_bytes():
                raise ValueError("whole-path cycles/counters changed")
        old_directory = Path(old["command"][2])
        if sorted(path.name for path in old_directory.iterdir()) != sorted(Path(item["path"]).name for item in new["outputs"]):
            raise ValueError("whole-path state replica set changed")
        for item in new["outputs"]:
            identity(item)
            identity({"path": str(old_directory / Path(item["path"]).name), "sha256": item["sha256"]})
        for path in sorted(Path(old["command"][1]).iterdir()):
            if path.is_file():
                references.append({"path": str(path), "sha256": sha256_file(path),
                                   "scope": "legacy_input_rechecked_at_packaging_not_prebaseline_hash"})
    return references


def recheck(root: Path, run: Path, components: Path, whole: Path) -> tuple[dict, list[dict]]:
    report = json.loads((run / "results.json").read_text())
    admission = admit_matrix(report["cases"])
    if report["status"] != admission["status"] or not same_typed(admission, report["admission"]):
        raise ValueError("resident-round admission changed")
    if [Path(item["path"]).name for item in report["binaries"]] != list(TARGETS):
        raise ValueError("tested executable set changed")
    for item in report["sources"]:
        identity(item, root)
    for item in [*report["binaries"], report["graph"], report["hls_udf"]]:
        identity(item)
    profile = root / report["model"]["k4_profile_reference"]
    identity({"path": str(profile), "sha256": report["model"]["k4_profile_sha256"]})
    plugin = root / "build/sst/libspine_cycle.so"
    if sha256_file(plugin) != report["default_plugin_sha256_before"] or report["default_plugin_sha256_after"] != report["default_plugin_sha256_before"]:
        raise ValueError("frozen default plugin changed")
    probe = report["probe"]
    if not same_typed(admitted_probe(root, Path(probe["report"]), Path(probe["binary"])), probe):
        raise ValueError("author-layout probe changed")
    solution = Path(report["sssp_apply_schedule"]["files"][0]["path"]).parents[2]
    if not same_typed(apply_schedule(solution), report["sssp_apply_schedule"]):
        raise ValueError("SSSP Apply schedule evidence changed")
    raw = steps(report)
    references = legacy(report, raw, components, whole)
    graph = load_slice(Path(report["graph"]["path"]))
    contract = json.loads((root / "configs/experiments/original_regraph_inputs_v1.json").read_text())
    layout = analyze_topology(Path(raw["author_layout"]["stdout"]).read_text(), run / "author_capture",
                              probe, inspect_graph(run / "topology.txt"), contract)
    if not same_typed(layout, report["layout"]) or [i["mode"] for i in report["inputs"]] != list(MODES):
        raise ValueError("author layout or SSSP input matrix changed")
    with tempfile.TemporaryDirectory(prefix="sssp-round-recheck-") as temporary:
        for item in report["inputs"]:
            regenerated = Path(temporary) / item["mode"]
            geometry = overlay(graph, run / "author_capture", layout, regenerated, item["mode"])
            if not same_typed(geometry, {k: v for k, v in item.items() if k not in {"path", "files"}}):
                raise ValueError("SSSP input geometry changed")
            if sorted(p.name for p in regenerated.iterdir()) != sorted(Path(f["path"]).name for f in item["files"]):
                raise ValueError("SSSP input files changed")
            for file in item["files"]:
                identity(file)
                if sha256_file(regenerated / Path(file["path"]).name) != file["sha256"]:
                    raise ValueError("SSSP state/weights/task overlay changed")
    for case in report["cases"]:
        name = f"{case['mode']}_lat{case['latency']}_reverse{case['reverse']}"
        row = raw[name]
        geometry = next(i for i in report["inputs"] if i["mode"] == case["mode"])
        observed = admit_round(Path(row["stdout"]).read_text(), run / "states" / name, geometry)
        if Path(row["stderr"]).read_bytes() or not same_typed(observed, {k: v for k, v in case.items() if k not in {"mode", "latency", "reverse"}}):
            raise ValueError("complete state or raw counters changed")
        words = read_words(Path(case["outputs"][0]["path"]))
        if sum(bool(word & ACTIVE) for word in words) != case["paths"][0]["active_vertices"] or any(words[geometry["vertices"]:]):
            raise ValueError("saved-state active population or padding differs")
    negative = report["pr_arithmetic_negative_control"]
    if (negative["original_pr_rejected_unchanged_capture"] is not True or negative["sssp_has_separate_oracle"] is not True
            or negative["diagnostic"] not in Path(raw["pr_arithmetic_rejection"]["stderr"]).read_text()
            or list((run / "pr_rejection").iterdir())):
        raise ValueError("original PR negative control changed")
    return report, references
