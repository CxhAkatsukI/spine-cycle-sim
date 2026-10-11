"""Revalidate and freeze the explicit SST candidate, including timing mismatches."""

import json
from pathlib import Path
from statistics import median
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.refactor_equivalence import compare_runs, verify_source_snapshot
from .analysis import analyze_log
from .execution import identity
from .sst_candidate import load_profile, require_export_headers
from .sst_timing import timing_diagnostic


def tail_diagnostic(model: dict, board: dict, inventory: list[dict]) -> dict:
    models = {(e["stage"], e["round"] - 1, e["partition"]): e for e in model["invocations"]}
    measured = {(e["stage"], e["round"], e["shard"]): e for e in board["events"]}
    rows = []
    for round_index in range(len(model["rounds"])):
        for item in inventory:
            p, count = item["partition"], item["trailing_empty_rows"]
            if count <= 0:
                continue
            ma, mg = (models[stage, round_index, p] for stage in ("adapter", "gather"))
            ha, hg = (measured[stage, round_index, p] for stage in ("adapter", "gather"))
            model_tail = max(0, ma["end"] - mg["end"]) * 1000 / 150
            board_tail = max(0, ha["end_ns"] - hg["end_ns"])
            rows.append({"round": round_index + 1, "partition": p, "trailing_empty_rows": count,
                         "model_adapter_after_gather_ms": model_tail / 1e6,
                         "board_adapter_after_gather_ms": board_tail / 1e6,
                         "model_nominal_tail_ns_per_row": model_tail / count,
                         "board_nominal_tail_ns_per_row": board_tail / count})
    return {"rows": rows,
            "model_median_nominal_ns_per_row": median(r["model_nominal_tail_ns_per_row"] for r in rows),
            "board_median_nominal_ns_per_row": median(r["board_nominal_tail_ns_per_row"] for r in rows),
            "claim": "observable_tail_normalized_by_known_empty_rows_not_exclusive_AXI_latency_or_calibration"}


def package_sst_checkpoint(root: Path, integration: Path, data: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / "raw_sst.tar.gz"
    if archive_path.exists() or (output / "sst.json").exists():
        raise FileExistsError("SST checkpoint is already frozen")
    binding = json.loads((data / "baseline_binding.json").read_text())
    before = Path(binding["baseline"])
    contract = json.loads((root / "configs/experiments/grasu_component_refactor_v1.json").read_text())
    equivalent = compare_runs(contract, before, data / "legacy_final")
    legacy = json.loads((data / "legacy_final/identity.json").read_text())
    if equivalent["status"] != "PASS" or equivalent["correctness_admitted_cases"] != 5 or equivalent["ignored_result_fields"]:
        raise ValueError("all five complete legacy SST results must remain identical")
    verify_source_snapshot(root, legacy["source"])
    profile_path = root / "configs/architectures/grasu_regraph_routed_sssp_compute_v1.json"
    profile = load_profile(root, profile_path)
    require_export_headers(integration, profile)
    matrix_dir = data / "matrix_final"
    matrix = json.loads((matrix_dir / "matrix.json").read_text())
    complete = json.loads((matrix_dir / "summary.json").read_text())
    expected = {f"{case}_{arm}" for case in ("au", "su", "wk") for arm in ("candidate", "original")}
    if (complete["status"] != "FUNCTIONAL_MATRIX_PASS_TIMING_UNADMITTED" or complete["hardware_timing_admitted"]
            or set(matrix["expected"]) != expected or len(matrix["expected"]) != 6
            or sorted(row["id"] for row in complete["rows"]) != sorted(matrix["expected"])
            or identity(Path(matrix["contract"]["path"])) != matrix["contract"]):
        raise ValueError("complete predeclared paired SST matrix is required")
    audits = json.loads((data / "input_audits_final.json").read_text())
    if audits["status"] != "PASS" or identity(Path(audits["source"]["path"])) != audits["source"]:
        raise ValueError("independent resident old-state audit is required")
    verification = {}
    for name in ("plugin_build_final", "exporter_build_attempt1", "core_build", "core_ctest", "legacy_regression", "input_audit_final"):
        resource = json.loads((data / f"{name}.resources.json").read_text())
        if resource["exit_code"] or resource["timed_out"]:
            raise ValueError(f"required gate failed: {name}")
        verification[name] = resource
    if "100% tests passed, 0 tests failed out of 22" not in (data / "core_ctest.stdout.txt").read_text():
        raise ValueError("complete 22-executable core gate missing")
    files, rows = {}, []
    for name in matrix["expected"]:
        directory = matrix_dir / name
        manifest = json.loads((directory / "manifest.json").read_text())
        result = json.loads((directory / "result.json").read_text())
        saved = json.loads((directory / "summary.json").read_text())
        if manifest["source"] != legacy["source"] or manifest["plugin"]["plugin_sha256"] != legacy["plugin_sha256"]:
            raise ValueError("candidate and legacy gates must bind identical numerical source and plugin")
        for pin in manifest["pins"] + manifest["headers"] + [saved["fixture"]]:
            if identity(Path(pin["path"])) != pin:
                raise ValueError("candidate input, exporter or hardware evidence changed")
        board_pin = next(pin for pin in manifest["pins"] if Path(pin["path"]).name == "run.log")
        board_path = Path(board_pin["path"]).parent
        board = analyze_log((board_path / "run.log").read_text(), require_trace=True)
        if (identity(directory / "result.json.values.txt")["sha256"] != identity(board_path / "result.txt")["sha256"]
                or timing_diagnostic(result, board) != saved["timing"]):
            raise ValueError("complete result or timing diagnostic changed")
        rows.append({"id": name, "timing": saved["timing"], "result": result, "attempts": saved["attempts"]})
        for path in board_path.iterdir():
            if path.is_file(): files["board/" + name + "/" + path.name] = path
    if identity(data / "plugin_final/libspine_cycle.so")["sha256"] != legacy["plugin_sha256"]:
        raise ValueError("tested plugin changed")
    tail_rows = {}
    for case in matrix["matrix"]["cases"]:
        name = case["id"]
        original = next(row for row in rows if row["id"] == name + "_original")
        audit = next(row for row in audits["rows"] if row["id"] == name)
        if identity(Path(audit["fixture"]["path"])) != audit["fixture"] or identity(Path(audit["graph"]["path"])) != audit["graph"]:
            raise ValueError("resident audit input changed")
        board = analyze_log((Path(case["board_pair"]) / "r0_original/run.log").read_text(), require_trace=True)
        tail_rows[name] = tail_diagnostic(original["result"], board, audit["audit"]["tails"])
        candidate_fixture = matrix_dir / f"{name}_candidate/resident.bin"
        if identity(candidate_fixture)["sha256"] != identity(matrix_dir / f"{name}_original/resident.bin")["sha256"]:
            raise ValueError("old/new PMA input fixtures differ")
        files[f"fixtures/{name}.bin"] = candidate_fixture
        files[f"graphs/{name}.graph"] = Path(case["graph"])
    for path in data.rglob("*"):
        relative = path.relative_to(data)
        if relative.parts[0] in {"core", "plugin", "plugin_final"} or path.name == "resident.bin": continue
        if path.is_file() and path.suffix in {".json", ".txt"}: files["campaign/" + str(relative)] = path
    for path in before.rglob("*"):
        if path.is_file(): files["baseline/" + str(path.relative_to(before))] = path
    for pin in legacy["source"]["files"]:
        files["source/simulator/" + pin["path"]] = root / pin["path"]
    for pattern in ("cpp/tools/routed_regraph/*", "cpp/tests/routed_regraph/*", "tests/test_sharded_k4*.py",
                    "scripts/run_routed_k4*.py", "scripts/package_routed_k4_sst.py",
                    "spine_cycle_sim/experiments/sharded_k4_stages/sst*.py"):
        for path in root.glob(pattern):
            if path.is_file(): files["source/simulator/" + str(path.relative_to(root))] = path
    for name in profile["input_export"]: files["source/HLS/include/" + name] = integration / "include" / name
    files["source/simulator/" + str(profile_path.relative_to(root))] = profile_path
    files["source/simulator/configs/experiments/sharded_k4_routed_sssp_timing_v1.json"] = Path(matrix["contract"]["path"])
    files["binaries/libspine_cycle.so"] = data / "plugin_final/libspine_cycle.so"
    files["binaries/export_hls_fixture"] = data / "export_hls_fixture"
    for name in ("CMakeCache.txt", "cpp/CMakeFiles/spine_cycle_core.dir/flags.make",
                 "cpp/CMakeFiles/routed_regraph_fixture_tests.dir/link.txt",
                 "cpp/routed_regraph_fixture_tests", "cpp/routed_regraph_system_tests"):
        files["core_configuration/" + name] = data / "core" / name
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, path in sorted(files.items()): archive.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"])) != {key: pin[key] for key in ("path", "sha256")} for pin in index):
        raise ValueError("delivery input changed during packaging")
    atomic_write_json(output / "sst_raw_index.json", {"archive": identity(archive_path), "files": index,
                                                     "duplicate_arm_fixtures": "one identical fixture per graph archived"})
    summary = {"schema_version": 1, "status": "SSSP_SST_FUNCTIONAL_PASS_TIMING_MISMATCH_RETAINED",
               "hardware_timing_admitted": False, "original_A4_match_admitted": False,
               "legacy": equivalent, "rows": rows, "input_audits": audits,
               "old_adapter_tail_diagnostic": tail_rows, "verification": verification,
               "remaining": ["identify_and_validate_physical_memory_and_schedule_timing_gap",
                             "matched_window_hardware_timing_acceptance", "matched_original_A4_comparison",
                             "other_algorithms_routed_topology_admission"]}
    atomic_write_json(output / "sst.json", summary)
    return summary
