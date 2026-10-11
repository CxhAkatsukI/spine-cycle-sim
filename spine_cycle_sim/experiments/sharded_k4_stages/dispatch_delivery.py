"""Revalidate and seal the unchanged-board CPU-affinity control."""

import json
from pathlib import Path
import statistics
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from .analysis import analyze_log
from .dispatch_sweep import dispatch_metrics, validate_affinities
from .execution import identity


def validate_sweep(data: Path) -> tuple[dict, dict[str, Path]]:
    manifest = json.loads((data / "manifest.json").read_text())
    saved = json.loads((data / "summary.json").read_text())
    attempts = json.loads((data / "attempts.json").read_text())
    affinities = manifest["affinities"]
    validate_affinities(affinities, set().union(*map(set, affinities)))
    if (manifest["repeats"] != 3 or manifest["device_index"] != 1
            or manifest["case"]["case"] != "wk_weighted_sssp_resident"
            or saved["status"] != "DISPATCH_AFFINITY_CONTROL_FUNCTIONAL_PASS"
            or saved["attempts"] != attempts):
        raise ValueError("unexpected dispatch campaign identity or saved attempts")
    for pin in manifest["pins"]:
        if identity(Path(pin["path"])) != pin:
            raise ValueError("dispatch campaign source/input/binary changed")
    reference = json.loads(Path(manifest["pins"][-2]["path"]).read_text())
    if reference["status"] != "PAIRED_BOARD_PASS" or not all(reference["checks"].values()):
        raise ValueError("paired reference is not admitted")
    expected = reference["attempts"][0]
    order = [(repeat, (repeat + offset) % 3) for repeat in range(3) for offset in range(3)]
    if [(a["repeat"], a["arm"]) for a in attempts] != order:
        raise ValueError("dispatch control is missing or reorders an arm")
    files = {name: data / name for name in ("manifest.json", "summary.json", "attempts.json")}
    result_pins = []
    for attempt in attempts:
        name = f"r{attempt['repeat']}_arm{attempt['arm']}"
        process = f"{name}_process"
        resources = json.loads((data / f"{process}.resources.json").read_text())
        if (resources != attempt["resources"] or resources["exit_code"]
                or resources["timed_out"] or resources["memory_limit_gib"] != 8
                or resources["reserve_gib"] != 16):
            raise ValueError("failed or changed bounded dispatch execution")
        prefix = ["taskset", "--cpu-list", ",".join(map(str, affinities[attempt["arm"]]))]
        if resources["command"][:3] != prefix:
            raise ValueError("affinity differs from its assigned arm")
        board = analyze_log((data / name / "run.log").read_text(), require_trace=True)
        result = identity(data / name / "result.txt")
        if (board != attempt["analysis"] or dispatch_metrics(board) != attempt["dispatch"]
                or board["result"] != expected["analysis"]["result"]
                or result != attempt["result"] or result["sha256"] != expected["result"]["sha256"]):
            raise ValueError("dispatch full result, round geometry or trace changed")
        result_pins.append(result)
        for extension in ("resources.json", "stdout.txt", "stderr.txt"):
            files[f"{process}.{extension}"] = data / f"{process}.{extension}"
        for leaf in ("run.log", "run.env", "summary.tsv"):
            files[f"{name}/{leaf}"] = data / name / leaf
    medians = [{"arm": arm, "cpus": cpus,
                "compute_span_ms": statistics.median(a["analysis"]["compute_span_ms"] for a in attempts if a["arm"] == arm)}
               for arm, cpus in enumerate(affinities)]
    if medians != saved["medians_ms"] or any(saved[key] for key in
            ("root_cause_proven", "hardware_timing_admitted", "timing_fit_performed")):
        raise ValueError("changed numerical summary or unsupported timing claim")
    report = {"status": saved["status"], "medians_ms": medians,
              "compute_span_range_ms": [min(a["analysis"]["compute_span_ms"] for a in attempts),
                                        max(a["analysis"]["compute_span_ms"] for a in attempts)],
              "full_result_pins": result_pins, "attempt_count": len(attempts),
              "peak_process_rss_kib": max(a["resources"]["peak_rss_kib"] for a in attempts),
              "total_process_wall_seconds": sum(a["resources"]["wall_seconds"] for a in attempts),
              "all_successors_queued_before_previous_end": all(
                  gap["queued_before_previous_end"] for a in attempts
                  for group in a["dispatch"]["groups"] for gap in group["gaps"]),
              "root_cause_proven": False, "hardware_timing_admitted": False,
              "original_A4_match_admitted": False, "timing_fit_performed": False,
              "limits": ["three repetitions per affinity, not a causal or statistical certificate",
                         "kernel lifetimes include stream waits; gather denotes whole lksg",
                         "same-worker gap sums are not additive end-to-end penalties",
                         "CPU count alone does not explain the remaining WK timing gap",
                         "identical full result files are externally hash-indexed, not duplicated in archive"]}
    return report, files


def package_sweep(root: Path, data: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "raw_dispatch.tar.gz"
    if archive.exists() or (output / "dispatch.json").exists():
        raise FileExistsError("dispatch evidence is frozen")
    report, files = validate_sweep(data)
    manifest = json.loads((data / "manifest.json").read_text())
    for pin in manifest["pins"]:
        path = Path(pin["path"])
        if path.suffix in (".py", ".sh", ".json", ".tsv"):
            files["reference/" + str(path).lstrip("/")] = path
    owner = root / "spine_cycle_sim/experiments/sharded_k4_stages"
    for name in ("dispatch_sweep.py", "dispatch_delivery.py"):
        files["source/" + name] = owner / name
    files["tests/test_sharded_k4_dispatch_sweep.py"] = root / "tests/test_sharded_k4_dispatch_sweep.py"
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    with tarfile.open(archive, "w:gz") as stream:
        for name, path in sorted(files.items()):
            stream.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"]))["sha256"] != pin["sha256"] for pin in index):
        raise ValueError("dispatch evidence changed during packaging")
    dependencies = [identity(output.parent / "empty_exit_matrix" / "matrix_raw_index.json")]
    atomic_write_json(output / "dispatch_raw_index.json", {
        "archive": identity(archive), "files": index, "dependencies": dependencies,
        "external_full_results": report["full_result_pins"]})
    atomic_write_json(output / "dispatch.json", report)
    return report
