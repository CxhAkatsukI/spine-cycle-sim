"""Seal the RTL empty-exit correction without admitting full-system calibration."""

import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.refactor_equivalence import compare_runs, verify_source_snapshot
from .execution import identity
from .row_exit_sweep import corrected_row
from .row_sweep_analysis import incremental_slopes


def compare_payloads(before: dict, after: dict) -> None:
    for result in (before, after):
        if not all(result[k] is True for k in ("success", "done", "ledger_closed", "replicas_equal")):
            raise ValueError("complete correctness and finite-ledger closure required")
        counters = result["counters"]
        if (counters["axi_requests"] != counters["axi_completions"]
                or counters["axi_beats"] != counters["axi_completed_beats"]):
            raise ValueError("AXI conservation failed")
        if (len(result["rounds"]) != result["expected_rounds"] or not result["rounds"]
                or result["rounds"][-1]["active_vertices"] != 0):
            raise ValueError("complete converged round history required")
    for key in ("vertices", "partitions", "pma_slots", "live_edges_per_round", "expected_rounds",
                "backend_reads", "backend_writes", "boundary", "evidence"):
        if before[key] != after[key]:
            raise ValueError(f"empty exit changed non-timing field {key}")
    counts = [{k: v for k, v in r["counters"].items() if k not in ("start_cycle", "end_cycle")}
              for r in (before, after)]
    if counts[0] != counts[1] or [r["active_vertices"] for r in before["rounds"]] != [
            r["active_vertices"] for r in after["rounds"]]:
        raise ValueError("non-timing counters or convergence changed")


def package_empty_exit(root: Path, data: Path, board_parent: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if (output / "raw_model.tar.gz").exists() or (output / "model.json").exists():
        raise FileExistsError("empty-exit model checkpoint is frozen")
    binding = json.loads((data / "baseline_binding.json").read_text())
    parent = Path(binding["parent"])
    contract = json.loads((root / "configs/experiments/grasu_component_refactor_v1.json").read_text())
    legacy = compare_runs(contract, parent / "legacy", data / "legacy")
    if legacy["status"] != "PASS" or legacy["correctness_admitted_cases"] != 5 or legacy["ignored_result_fields"]:
        raise ValueError("five exact legacy result regressions required")
    expected = legacy["candidate_identity"]
    verify_source_snapshot(root, expected["source"])
    if legacy["baseline_identity"]["plugin_sha256"] != binding["plugin"]["sha256"]:
        raise ValueError("pre-edit baseline plugin differs")
    verification = {}
    for step in ("configure", "build", "ctest", "plugin_build", "legacy_regression"):
        record = json.loads((data / f"{step}.resources.json").read_text())
        if record["exit_code"] or record["timed_out"]:
            raise ValueError(f"verification failed: {step}")
        verification[step] = record
    python = json.loads((data / "python_gates.resources.json").read_text())
    if python["exit_code"] or python["stop_reason"] != "process_exit":
        raise ValueError("focused Python gates failed")
    verification["python_gates"] = python
    if "100% tests passed, 0 tests failed out of 23" not in (data / "ctest.stdout.txt").read_text():
        raise ValueError("complete CTest gate missing")
    sweep = json.loads((data / "sweep/summary.json").read_text())
    old_sweep = json.loads((board_parent / "summary.json").read_text())
    if (sweep["status"] != "EMPTY_EXIT_SWEEP_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC"
            or len(sweep["replays"]) != 8 or len(sweep["rows"]) != 4
            or sweep["parent"] != identity(board_parent / "summary.json")):
        raise ValueError("complete fixed-payload paired sweep required")
    files = {}
    for prior, row in zip(old_sweep["rows"], sweep["rows"]):
        vertices = prior["vertices"]
        base = board_parent / str(vertices)
        corrected = data / "sweep/corrected_v4" / str(vertices)
        if corrected_row(prior, corrected) != row:
            raise ValueError("saved timing diagnostic changed")
        for arm in ("original", "candidate"):
            replay = data / "sweep/replay_v2" / str(vertices) / arm
            for name in ("result.json", "result.json.values.txt"):
                if (base / arm / name).read_bytes() != (replay / name).read_bytes():
                    raise ValueError("old control changed result fields or bytes")
            old = json.loads((base / arm / "result.json").read_text())
            new = json.loads((corrected / arm / "result.json").read_text())
            compare_payloads(old, new)
            if (corrected / arm / "result.json.values.txt").read_bytes() != (base / arm / "result.json.values.txt").read_bytes():
                raise ValueError("new control output differs")
            for directory in (replay, corrected / arm):
                manifest = json.loads((directory / "manifest.json").read_text())
                if (manifest["source"] != expected["source"]
                        or manifest["plugin"]["plugin_sha256"] != expected["plugin_sha256"]):
                    raise ValueError("all final tests must share source and plugin")
                if any(identity(Path(pin["path"])) != pin for pin in manifest["pins"] + manifest["headers"]):
                    raise ValueError("frozen input changed")
        files[f"inputs/{vertices}/input.graph"] = base / "input.graph"
        files[f"inputs/{vertices}/prepared.bin"] = base / "prepared.bin"
    if incremental_slopes(sweep["rows"]) != sweep["slopes"]:
        raise ValueError("saved slopes differ")
    for path in data.rglob("*"):
        rel = path.relative_to(data)
        if rel.parts[0] not in ("core", "plugin") and path.is_file() and path.name != "resident.bin":
            files["campaign/" + str(rel)] = path
    for pin in expected["source"]["files"]:
        files["source/simulator/" + pin["path"]] = root / pin["path"]
    for pattern in ("configs/architectures/*compute_v4.json", "configs/experiments/*timing_v4.json",
                    "cpp/tests/routed_regraph/adapter_tests.cpp", "tests/test_sharded_k4_row_exit*.py"):
        for path in root.glob(pattern):
            files["source/simulator/" + str(path.relative_to(root))] = path
    for pattern in ("CMakeCache.txt", "**/flags.make", "**/link.txt"):
        for path in (data / "core").glob(pattern):
            files["build/core/" + str(path.relative_to(data / "core"))] = path
    files["binaries/libspine_cycle.so"] = data / "plugin/libspine_cycle.so"
    if identity(files["binaries/libspine_cycle.so"])["sha256"] != expected["plugin_sha256"]:
        raise ValueError("tested plugin changed")
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    archive = output / "raw_model.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name, path in sorted(files.items()):
            stream.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"]))["sha256"] != pin["sha256"] for pin in index):
        raise ValueError("evidence changed during packaging")
    dependencies = [identity(output.parent / name) for name in
                    ("empty_row_rtl/rtl_raw_index.json", "empty_rows/empty_rows_raw_index.json",
                     "routed_streams/streams_raw_index.json")]
    atomic_write_json(output / "model_raw_index.json", {"archive": identity(archive), "files": index,
                                                       "dependencies": dependencies})
    report = {"status": "EMPTY_EXIT_CONTROL_PASS_FULL_MATRIX_PENDING", "legacy": legacy,
              "verification": verification, "sweep": sweep, "hardware_timing_admitted": False,
              "original_A4_match_admitted": False, "timing_fit_performed": False,
              "pending": ["six real-graph v3 exact replays and v4 predictions",
                          "occupied-row and optimized-path timing explanation", "matched original-A4 comparison"]}
    atomic_write_json(output / "model.json", report)
    return report
