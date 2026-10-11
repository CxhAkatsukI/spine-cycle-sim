"""Recheck frozen inputs, complete state files and raw results before packaging."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from spine_cycle_sim.experiments.original_regraph_inputs.analysis import analyze_topology
from spine_cycle_sim.experiments.original_regraph_inputs.preparation import inspect_graph
from ..sssp_real_round.delivery import members
from ..sssp_real_round.preparation import ACTIVE, overlay, read_words
from .analysis import MATRIX, admit, coverage, matrix
from .preparation import select
from .study import frozen_executor, sources
from .contract import execution_contract, watchdog_contract
from .layout_audit import audit, bind_traffic
from .history import archive_prior, watchdog_files
from .archive import seal_compact


def recheck(root: Path, run: Path) -> dict:
    report = json.loads((run / "results.json").read_text())
    if sources(root) != report["sources"]:
        raise ValueError("partition study source changed")
    basis, binary = frozen_executor(root, Path(report["basis"]["path"]))
    contract = json.loads((root / "configs/experiments/original_regraph_inputs_v1.json").read_text())
    execution_contract(root, run, report, basis, contract)
    if sha256_file(Path(report["basis"]["path"])) != report["basis"]["sha256"] or {
            "path": str(binary), "sha256": sha256_file(binary)} != report["executor"]:
        raise ValueError("numerical basis changed")
    if (sha256_file(root / "build/sst/libspine_cycle.so") != report["default_plugin_sha256_before"]
            or report["default_plugin_sha256_after"] != report["default_plugin_sha256_before"]):
        raise ValueError("default plugin changed")
    expected = ["author_layout", *(f"{mode}_lat{latency}_reverse{reverse}" for mode, latency, reverse in MATRIX)]
    if [row["label"] for row in report["runs"]] != expected:
        raise ValueError("raw execution matrix missing or reordered")
    for row in report["runs"]:
        if row["exit_code"] or row["timed_out"] or row["memory_limit_gib"] != 8 or row["reserve_gib"] != 16:
            raise ValueError("raw execution or memory gate failed")
        resource = Path(row["stdout"].removesuffix(".stdout.txt") + ".resources.json")
        if not same_typed(json.loads(resource.read_text()), {k: v for k, v in row.items() if k != "label"}):
            raise ValueError("raw execution resource record changed")
    watchdog = json.loads(run.with_name(run.name + "_watchdog.resources.json").read_text())
    watchdog_contract(root, run, report, watchdog)
    if (watchdog["exit_code"] or watchdog["stop_reason"] != "process_exit"
            or watchdog["tree_memory_gib"] != 8 or watchdog["reserve_gib"] != 16
            or watchdog["peak_tree_rss_kib"] > 8 * 1024**2
            or watchdog["minimum_available_bytes"] < 16 * 1024**3):
        raise ValueError("process-tree memory gate failed")
    layout = analyze_topology(Path(report["runs"][0]["stdout"]).read_text(), run / "author_capture",
                              basis["probe"], inspect_graph(run / "topology.txt"), contract)
    if not same_typed(layout, report["layout"]) or coverage(layout, run / "author_capture") != report["coverage"]:
        raise ValueError("author capture or partition coverage changed")
    layout_work = audit(run / "author_capture", report["selection"]["vertices"])
    if not same_typed(layout_work, report["layout_audit"]):
        raise ValueError("static PMA work changed")
    bind_traffic(layout_work, report["cases"])
    with tempfile.TemporaryDirectory(prefix="sssp-partition-recheck-") as temporary:
        directory = Path(temporary)
        graph, selected = select(Path(report["selection"]["source"]["path"]), directory / "topology.txt")
        original = report["selection"]
        if ({k: v for k, v in selected.items() if k != "topology"} != {
                k: v for k, v in original.items() if k != "topology"}
                or selected["topology"]["sha256"] != original["topology"]["sha256"]
                or sha256_file(run / "topology.txt") != original["topology"]["sha256"]):
            raise ValueError("induced input changed")
        if [item["mode"] for item in report["inputs"]] != ["cold", "warm_update"]:
            raise ValueError("initial-state scenario set changed")
        for item in report["inputs"]:
            regenerated = directory / item["mode"]
            geometry = overlay(graph, run / "author_capture", layout, regenerated, item["mode"])
            if not same_typed(geometry, {k: v for k, v in item.items() if k not in {"files", "path"}}):
                raise ValueError("SSSP initial-state geometry changed")
            if sorted(path.name for path in regenerated.iterdir()) != sorted(Path(file["path"]).name for file in item["files"]):
                raise ValueError("SSSP overlay file set changed")
            for file in item["files"]:
                if (sha256_file(Path(file["path"])) != file["sha256"]
                        or sha256_file(regenerated / Path(file["path"]).name) != file["sha256"]):
                    raise ValueError("SSSP overlay changed")
    for case, raw in zip(report["cases"], report["runs"][1:], strict=True):
        geometry = next(item for item in report["inputs"] if item["mode"] == case["mode"])
        observed = admit(Path(raw["stdout"]).read_text(), run / "states" / raw["label"], geometry)
        if (Path(raw["stderr"]).read_bytes() or not same_typed(observed, {
                k: v for k, v in case.items() if k not in {"mode", "latency", "reverse"}})):
            raise ValueError("raw complete state or counters changed")
        words = read_words(Path(case["outputs"][0]["path"]))
        if sum(bool(word & ACTIVE) for word in words) != case["paths"][0]["active_vertices"]:
            raise ValueError("saved-state active count differs")
    admission = matrix(report["cases"])
    if report["status"] != admission["status"] or not same_typed(admission, report["admission"]):
        raise ValueError("matrix admission changed")
    return report


def deliver(root: Path, run: Path, destination: Path, attempts: list[Path]) -> dict:
    if destination.exists():
        raise ValueError("use a fresh delivery directory")
    report = recheck(root, run)
    files = members(run, "run")
    files.extend(watchdog_files(run, "watchdog"))
    files.extend((root / item["path"], "sources/" + item["path"]) for item in report["sources"])
    destination.mkdir(parents=True)
    archive = destination / "raw_sssp_partition_round.tar.xz"
    index = seal_compact(files, archive)
    shutil.copyfile(run / "results.json", destination / "results.json")
    record = {"status": report["status"], "files": index, "archive_bytes": archive.stat().st_size,
              "archive_sha256": sha256_file(archive), "results_sha256": sha256_file(destination / "results.json"),
              "complete_raw_inputs_states_and_counters_rechecked": True, "scope": report["admission"],
              "external_references": [report["basis"], report["executor"], report["selection"]["source"]]}
    if attempts:
        record["prior_attempts"] = archive_prior(attempts, report, destination)
    atomic_write_json(destination / "verification.json", record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--prior-attempt", type=Path, action="append", default=[])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    result = deliver(root, args.run.resolve(), args.destination.resolve(), [path.resolve() for path in args.prior_attempt])
    print(json.dumps({"status": result["status"], "archive_bytes": result["archive_bytes"]}, sort_keys=True))


if __name__ == "__main__":
    main()
