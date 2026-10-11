"""Version-3 stream-depth evidence; preserve exact v2 replay and unmatched timing."""

import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.refactor_equivalence import compare_runs, verify_source_snapshot
from .analysis import analyze_log
from .execution import identity
from .sst_candidate import INDEPENDENT_PROFILE_ID, STREAM_PROFILE_ID, load_profile
from .sst_timing import timing_diagnostic
from .stream_contract import audit_design


def compare_stream_results(parent: dict, replay: dict, corrected: dict) -> dict:
    if parent != replay or parent.get("profile_id") != INDEPENDENT_PROFILE_ID:
        raise ValueError("version-2 replay must preserve every result field")
    if corrected.get("profile_id") != STREAM_PROFILE_ID:
        raise ValueError("stream correction must explicitly select version 3")
    for result in (parent, corrected):
        if not all(result.get(field) is True for field in ("success", "done", "ledger_closed", "replicas_equal")):
            raise ValueError("complete correctness and conservation are required")
        c = result["counters"]
        if c["axi_requests"] != c["axi_completions"] or c["axi_beats"] != c["axi_completed_beats"]:
            raise ValueError("AXI requests or beats do not conserve")
        if (len(result["rounds"]) != result["expected_rounds"]
                or not result["rounds"] or result["rounds"][-1]["active_vertices"] != 0
                or c["end_cycle"] <= c["start_cycle"]):
            raise ValueError("positive complete converged timing is required")
    for field in ("vertices", "partitions", "pma_slots", "live_edges_per_round", "expected_rounds"):
        if corrected[field] != parent[field]:
            raise ValueError(f"version-3 workload or convergence changed: {field}")
    counts = [{k: v for k, v in result["counters"].items() if k not in ("start_cycle", "end_cycle")}
              for result in (parent, corrected)]
    if counts[0] != counts[1]:
        raise ValueError("stream capacity correction changed non-timing counters")
    for field in ("backend_reads", "backend_writes", "boundary", "evidence"):
        if parent[field] != corrected[field]:
            raise ValueError(f"stream correction changed {field}")
    if [r["active_vertices"] for r in parent["rounds"]] != [r["active_vertices"] for r in corrected["rounds"]]:
        raise ValueError("per-round active results changed")
    old, new = [r["counters"]["end_cycle"] - r["counters"]["start_cycle"] for r in (parent, corrected)]
    return {"v2_every_result_field_equal": True, "ignored_result_fields": [],
            "v2_cycles": old, "v3_cycles": new, "v3_over_v2_cycles": new / old,
            "non_timing_counters_equal": True}


def package_stream_checkpoint(root: Path, data: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if (output / "streams.json").exists() or (output / "raw_streams.tar.gz").exists():
        raise FileExistsError("stream-depth checkpoint is already frozen")
    binding = json.loads((data / "baseline_binding.json").read_text())
    parent = Path(binding["parent"])
    legacy = compare_runs(json.loads((root / "configs/experiments/grasu_component_refactor_v1.json").read_text()),
                          parent / "legacy_final", data / "legacy")
    if legacy["status"] != "PASS" or legacy["correctness_admitted_cases"] != 5 or legacy["ignored_result_fields"]:
        raise ValueError("five exact legacy result regressions are required")
    expected = legacy["candidate_identity"]
    if legacy["baseline_identity"]["plugin_sha256"] != binding["plugin_sha256"]:
        raise ValueError("parent plugin differs from the pre-edit binding")
    verify_source_snapshot(root, expected["source"])
    load_profile(root, root / "configs/architectures/grasu_regraph_routed_sssp_compute_v3.json")
    designs = [audit_design(data / "route" / f"{arm}.bd", arm) for arm in ("original", "candidate")]
    verification = {}
    for name in ("configure", "build", "ctest", "plugin_build", "legacy_regression", "python_gates"):
        record = json.loads((data / f"{name}.resources.json").read_text())
        if record["exit_code"] or record["timed_out"]:
            raise ValueError(f"stream-depth verification failed: {name}")
        verification[name] = record
    if "100% tests passed, 0 tests failed out of 23" not in (data / "ctest.stdout.txt").read_text():
        raise ValueError("complete CTest gate missing")
    rows, files = [], {}
    for version in ("replay_v2", "matrix_v3"):
        matrix = json.loads((data / version / "summary.json").read_text())
        if matrix["status"] != "FUNCTIONAL_MATRIX_PASS_TIMING_UNADMITTED" or matrix["hardware_timing_admitted"]:
            raise ValueError("full matrix required without timing admission")
    for case in ("au", "su", "wk"):
        for arm in ("original", "candidate"):
            name = f"{case}_{arm}"
            directories = [parent / "matrix_final" / name, data / "replay_v2" / name, data / "matrix_v3" / name]
            results = [json.loads((d / "result.json").read_text()) for d in directories]
            row = {"id": name, **compare_stream_results(*results)}
            if len({identity(d / "result.json.values.txt")["sha256"] for d in directories}) != 1:
                raise ValueError("complete result bytes changed")
            if len({identity(d / "resident.bin")["sha256"] for d in directories}) != 1:
                raise ValueError("resident input changed")
            for directory in directories[1:]:
                manifest = json.loads((directory / "manifest.json").read_text())
                if manifest["source"] != expected["source"] or manifest["plugin"]["plugin_sha256"] != expected["plugin_sha256"]:
                    raise ValueError("common source/plugin required for every final gate")
                if any(identity(Path(pin["path"])) != pin for pin in manifest["pins"] + manifest["headers"]):
                    raise ValueError("a frozen input changed")
            board_path = Path(next(p["path"] for p in manifest["pins"] if Path(p["path"]).name == "run.log"))
            board = analyze_log(board_path.read_text(), require_trace=True)
            row["timing"] = timing_diagnostic(results[-1], board)
            if row["timing"] != json.loads((directories[-1] / "summary.json").read_text())["timing"]:
                raise ValueError("saved timing diagnostic differs")
            if identity(board_path.parent / "result.txt")["sha256"] != identity(directories[-1] / "result.json.values.txt")["sha256"]:
                raise ValueError("full FPGA output differs")
            files[f"board/{name}/run.log"] = board_path
            files[f"parent/{name}/result.json"] = directories[0] / "result.json"
            files[f"fixtures/{case}.bin"] = directories[-1] / "resident.bin"
            rows.append(row)
    for path in data.rglob("*"):
        rel = path.relative_to(data)
        if rel.parts[0] not in ("core", "plugin") and path.is_file() and path.name != "resident.bin":
            files["campaign/" + str(rel)] = path
    for pin in expected["source"]["files"]:
        files["source/simulator/" + pin["path"]] = root / pin["path"]
    for pattern in ("configs/architectures/*compute_v3.json", "configs/experiments/*timing_v3.json",
                    "cpp/tests/routed_regraph/system_tests.cpp", "tests/test_sharded_k4_stream*.py"):
        for path in root.glob(pattern):
            files["source/simulator/" + str(path.relative_to(root))] = path
    for pattern in ("CMakeCache.txt", "**/flags.make", "**/link.txt"):
        for path in (data / "core").glob(pattern):
            files["build/core/" + str(path.relative_to(data / "core"))] = path
    files["binaries/libspine_cycle.so"] = data / "plugin/libspine_cycle.so"
    if identity(files["binaries/libspine_cycle.so"])["sha256"] != expected["plugin_sha256"]:
        raise ValueError("tested plugin changed")
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    archive = output / "raw_streams.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name, path in sorted(files.items()):
            stream.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"]))["sha256"] != pin["sha256"] for pin in index):
        raise ValueError("evidence changed during packaging")
    dependencies = [identity(output.parent / "independent_channels/channels_raw_index.json"),
                    identity(output.parent / "sst_raw_index.json")]
    atomic_write_json(output / "streams_raw_index.json", {"archive": identity(archive), "files": index,
                                                          "dependencies": dependencies})
    report = {"schema_version": 1, "status": "ROUTED_STREAM_DEPTHS_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC",
              "hardware_timing_admitted": False, "original_A4_match_admitted": False, "timing_fit_performed": False,
              "rows": rows, "routed_designs": designs, "legacy": legacy, "verification": verification}
    atomic_write_json(output / "streams.json", report)
    return report
