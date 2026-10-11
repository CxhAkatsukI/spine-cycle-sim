"""Freeze routed admission and paired-board evidence without replacing older gates."""

import json
from pathlib import Path
import statistics
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .analysis import analyze_log
from .execution import identity


def inspect_pair(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    result = json.loads((directory / "summary.json").read_text())
    if result["status"] != "PAIRED_BOARD_PASS" or not all(result["checks"].values()):
        raise ValueError("paired board checks failed")
    if any(identity(Path(pin["path"])) != pin for pin in manifest["pins"]):
        raise ValueError("board input or source changed")
    attempts = result["attempts"]
    expected = [(repeat, arm) for repeat in range(manifest["repeats"])
                for arm in (("candidate", "original") if repeat % 2 else ("original", "candidate"))]
    if manifest["repeats"] < 3 or [(a["repeat"], a["arm"]) for a in attempts] != expected:
        raise ValueError("paired repetitions or order differ")
    hashes, correctness = set(), []
    for attempt in attempts:
        run = directory / f"r{attempt['repeat']}_{attempt['arm']}"
        if attempt["resources"]["exit_code"] != 0 or attempt["resources"]["timed_out"]:
            raise ValueError("board process did not complete")
        analyzed = analyze_log((run / "run.log").read_text(), require_trace=True)
        if analyzed != attempt["analysis"] or identity(run / "result.txt") != attempt["result"]:
            raise ValueError("board raw log or result differs from summary")
        hashes.add(attempt["result"]["sha256"])
        correctness.append(analyzed["result"])
    if len(hashes) != 1 or any(row != correctness[0] for row in correctness):
        raise ValueError("board result bytes or convergence differ")
    for arm in ("original", "candidate"):
        rows = [a["analysis"] for a in attempts if a["arm"] == arm]
        for key, value in result["medians"][arm].items():
            values = [r["timing_ms"][key] if key == "setup_inclusive_ms" else r[key] for r in rows]
            if statistics.median(values) != value:
                raise ValueError("board median differs from raw repetitions")
    return {"case": manifest["case"], "repeats": manifest["repeats"],
            "device_index": manifest["device_index"], "checks": result["checks"],
            "geometry": correctness[0], "medians": result["medians"],
            "old_over_new": {key: result["medians"]["original"][key] / result["medians"]["candidate"][key]
                             for key in ("setup_inclusive_ms", "compute_span_ms")}}


def package_board(data: Path, integration: Path, output: Path, board_case: list[str]) -> dict:
    del integration  # Kept compatible with the shared gate-packaging CLI.
    if not board_case or len(set(board_case)) != len(board_case):
        raise ValueError("unique explicit board case directories required")
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / "raw_board.tar.gz"
    if archive_path.exists() or (output / "board.json").exists():
        raise FileExistsError("board evidence already frozen")
    route = data / "route_combined_sssp"
    admission = data / "route_combined_sssp_admission"
    gate = json.loads((admission / "summary.json").read_text())
    if gate["status"] != "ROUTED_METADATA_TIMING_PASS_AWAITING_BOARD":
        raise ValueError("routed admission required")
    pins = gate["pins"] + [gate["original"], gate["candidate"], gate["timing"]["report"]]
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("routed admission evidence changed")
    files = {}

    def add(path):
        files[str(path.relative_to(data))] = path

    cases = []
    for name in board_case:
        if Path(name).name != name:
            raise ValueError("board case must be a direct child of the run root")
        directory = data / name
        case = inspect_pair(directory)
        pair_manifest = json.loads((directory / "manifest.json").read_text())
        if identity(admission / "summary.json") not in pair_manifest["pins"]:
            raise ValueError("paired case uses a different admission")
        cases.append(case)
        for path in directory.rglob("*"):
            if path.is_file():
                add(path)
    for path in admission.rglob("*"):
        if path.is_file():
            add(path)
    for name in ("manifest.json", "summary.json", "route.progress.json", "route.stdout.txt",
                 "route.stderr.txt", "link.cfg", "logs/link/link.steps.log"):
        add(route / name)
    if (route / "route.resources.json").exists():
        add(route / "route.resources.json")
    add(Path(gate["timing"]["report"]["path"]))
    for path in Path(__file__).parent.glob("*.py"):
        files["source/simulator/" + path.name] = path
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, path in sorted(files.items()):
            archive.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"]))["sha256"] != pin["sha256"] for pin in index):
        raise ValueError("board delivery input changed while packaging")
    atomic_write_json(output / "board_raw_index.json", {"archive": identity(archive_path), "files": index})
    result = {"status": "ROUTED_AND_PAIRED_SSSP_BOARD_PASS", "admission": gate, "cases": cases,
              "claim": "old_vs_combined_K4_SSSP_same_host_resident_update_to_convergence",
              "not_complete": ["individual_prefetch_vs_stop_ablation_on_FPGA", "optimized_CC_and_PR_hardware",
                               "optimized_production_simulator", "matched_original_A4_vs_actual_K4", "publication_speed_match"]}
    atomic_write_json(output / "board.json", result)
    return result
