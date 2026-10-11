"""Recompute residency evidence from raw logs, commands, results and XRT traces."""

import json
from pathlib import Path

from .analysis import analyze_log
from .dispatch_sweep import dispatch_metrics
from .execution import identity
from .input_residency import residency_record, summarize
from .residency_matrix import summarize_matrix
from .runtime_trace import parse_vtf, trace_transfers


def load(path: Path):
    return json.loads(path.read_text())


def check_attempt(directory: Path, attempt: dict, manifest: dict, expected: dict,
                  *, enabled: bool | None, profiled: bool) -> dict[str, Path]:
    resources = load(directory / "process.resources.json")
    if (resources != attempt["resources"] or resources["exit_code"] or resources["timed_out"]
            or resources["memory_limit_gib"] != 8 or resources["reserve_gib"] != 16
            or resources["command"][:3] != ["taskset", "--cpu-list", ",".join(map(str, manifest["cpus"]))]
            or resources["cwd"] != str(directory)
            or ("GRASU_SHARDED_PREMIGRATE_INPUTS=1" in resources["command"]) != (enabled is True)
            or any(v.startswith("XRT_INI_PATH=") for v in resources["command"]) != profiled):
        raise ValueError("bounded execution, affinity or intervention differs from assigned arm")
    if enabled is False and "GRASU_SHARDED_PREMIGRATE_INPUTS=0" not in resources["command"]:
        raise ValueError("disabled arm does not explicitly disable residency")
    log = (directory / "board/run.log").read_text()
    board = analyze_log(log, require_trace=True)
    result = identity(directory / "board/result.txt")
    if (board != attempt["analysis"] or result != attempt["result"]
            or board["result"] != expected["analysis"]["result"]
            or result["sha256"] != expected["result"]["sha256"]):
        raise ValueError("raw complete result, round geometry or kernel events changed")
    if "dispatch" in attempt and dispatch_metrics(board) != attempt["dispatch"]:
        raise ValueError("changed dispatch analysis")
    initial = residency_record(log, enabled=enabled is True,
                               partitions=int(board["result"]["destination_partitions"]))
    if "residency" in attempt and initial != attempt["residency"]:
        raise ValueError("changed initial-residency record")
    traces = [identity(p) for p in sorted(directory.glob("*.csv"))]
    if "traces" in attempt and traces != attempt["traces"]:
        raise ValueError("runtime trace identities changed")
    if profiled and not (directory / "opencl_trace.csv").is_file():
        raise ValueError("missing OpenCL runtime trace")
    files = {str(p.relative_to(directory)): p for p in directory.glob("*") if p.is_file()}
    files.update({"board/" + leaf: directory / "board" / leaf
                  for leaf in ("run.log", "run.env", "summary.tsv")})
    return files


def validate_campaigns(campaign: Path, traced: Path) -> tuple[dict, dict[str, Path]]:
    control, matrix = campaign / "control", campaign / "matrix"
    manifests = {"control": load(control / "manifest.json"), "matrix": load(matrix / "manifest.json"),
                 "trace": load(traced / "manifest.json")}
    pins = {p["path"]: p for m in manifests.values() for p in m["pins"]}
    if any(p != pins[p["path"]] for m in manifests.values() for p in m["pins"]):
        raise ValueError("conflicting campaign pins")
    if any(identity(Path(p["path"])) != p for p in pins.values()):
        raise ValueError("pinned input, source, runtime or binary changed")
    for m in manifests.values():
        if (m["device_index"] != 1 or m["cpus"] != [122, 123] or m["memory_limit_gib"] != 8
                or m["reserve_gib"] != 16 or m["timeout_seconds"] != 600):
            raise ValueError("unexpected runtime or safety contract")
    frozen = next(Path(p) for p in pins if p.endswith("/empty_exit_matrix/matrix.json"))
    predictions = {r["id"]: r["timing"]["predicted_no_host_ms"] for r in load(frozen)["rows"]}
    if predictions != manifests["matrix"]["predictions_ms"]:
        raise ValueError("model predictions differ from the frozen pre-intervention matrix")
    reference = load(Path(manifests["control"]["reference"]) / "summary.json")["attempts"][0]
    files, all_attempts = {}, []
    for label, directory in (("control", control), ("matrix", matrix), ("trace", traced)):
        attempts, saved = load(directory / "attempts.json"), load(directory / "summary.json")
        if attempts != saved["attempts"]:
            raise ValueError("saved attempts differ from campaign summary")
        if label == "control" and summarize(attempts) != saved:
            raise ValueError("changed residency control summary")
        if label == "matrix" and summarize_matrix(attempts, manifests[label]["predictions_ms"]) != saved:
            raise ValueError("changed fixed-model matrix summary")
        if label == "trace" and (saved["status"] != "RUNTIME_TRACE_FUNCTIONAL_PASS"
                or [a["arm"] for a in attempts] != ["unprofiled", "profiled"]):
            raise ValueError("incomplete runtime trace control")
        for flag in ("hardware_timing_admitted", "timing_fit_performed"):
            if saved[flag]:
                raise ValueError("unsupported timing admission or model fitting")
        for name in ("manifest.json", "attempts.json", "summary.json"):
            files[f"{label}/{name}"] = directory / name
        for a in attempts:
            if label == "matrix":
                name = f"r{a['repeat']}_{a['graph']}_{a['arm']}"
                expected = next(v for v in manifests[label]["cases"][a["graph"]]["baseline"]["attempts"]
                                if v["arm"] == a["arm"])
                enabled, profiled = True, False
            elif label == "control":
                name = "profiled_on" if a["profiled"] else f"r{a['repeat']}_{a['arm']}"
                expected, enabled, profiled = reference, a["arm"] == "on", a["profiled"]
            else:
                name, expected, enabled, profiled = a["arm"], reference, None, a["arm"] == "profiled"
            files.update({f"{label}/{name}/{n}": p for n, p in check_attempt(
                directory / name, a, manifests[label], expected, enabled=enabled, profiled=profiled).items()})
            all_attempts.append(a)
    before = trace_transfers(parse_vtf((traced / "profiled/opencl_trace.csv").read_text()),
                             load(traced / "attempts.json")[1]["analysis"])
    after = trace_transfers(parse_vtf((control / "profiled_on/opencl_trace.csv").read_text()),
                            load(control / "attempts.json")[-1]["analysis"])
    if (before["compute_write_count"] != 16 or before["compute_write_bytes"] != 145939200
            or not before["all_compute_writes_row_sized"]
            or not before["all_compute_writes_precede_dependent_adapter"]
            or not all(w["earlier_same_bo_write_ids"] for w in before["writes"])
            or after["compute_write_count"] or before["aligned_kernels"] != 56 or after["aligned_kernels"] != 56):
        raise ValueError("runtime intervention no longer reproduces the transfer finding")
    build = load(campaign / "build.resources.json")
    if build["exit_code"] or build["timed_out"] or build["memory_limit_gib"] != 8 or build["reserve_gib"] != 16:
        raise ValueError("residency host build failed or lacked safety bounds")
    for leaf in ("build_sources.json", "build.resources.json", "build.stdout.txt", "build.stderr.txt",
                 "host/manifest.txt", "host/weighted_pma_native_host.sha256", "host/sharded_k4_sssp_native_host"):
        files["build/" + leaf] = campaign / leaf
    result_pins = [a["result"] for a in all_attempts]
    for p in result_pins:
        files[f"complete_results/{p['sha256']}.txt"] = Path(p["path"])
    report = {"status": "INITIAL_RESIDENCY_INTERVENTION_VALIDATED", "attempt_count": len(all_attempts),
              "control_medians": load(control / "summary.json")["medians"],
              "resident_matrix": load(matrix / "summary.json")["rows"],
              "runtime_before": before, "runtime_after": after, "external_full_results": result_pins,
              "peak_process_rss_kib": max(a["resources"]["peak_rss_kib"] for a in all_attempts),
              "total_process_wall_seconds": sum(a["resources"]["wall_seconds"] for a in all_attempts),
              "timing_fit_performed": False, "hardware_timing_admitted": False,
              "original_A4_match_admitted": False, "exclusive_stage_calibration_admitted": False,
              "limits": ["initial migration is separately charged, not an architectural speedup",
                         "runtime profiles are diagnostics; medians use unprofiled runs only",
                         "fixed model omits dispatch/relaunch gaps and has uncalibrated physical mapping",
                         "all six warm-SSSP model rows checked, not other algorithms or original A4",
                         "kernel lifetimes include stream waits; transfer times must not be summed"]}
    return report, files
