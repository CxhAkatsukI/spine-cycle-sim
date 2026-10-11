"""Audit and freeze the independent-channel correction without replacing v1 evidence."""

import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.refactor_equivalence import compare_runs, verify_source_snapshot
from .analysis import analyze_log
from .execution import identity
from .sst_candidate import INDEPENDENT_PROFILE_ID, load_profile
from .sst_delivery import tail_diagnostic
from .sst_timing import timing_diagnostic


def compare_channel_results(parent: dict, replay: dict, corrected: dict) -> dict:
    if parent != replay:
        changed = sorted(key for key in parent.keys() | replay.keys()
                         if parent.get(key) != replay.get(key))
        raise ValueError(f"version-1 full-result regression differs: {changed}")
    if corrected.get("profile_id") != INDEPENDENT_PROFILE_ID:
        raise ValueError("corrected result must explicitly select version 2")
    if not all(corrected.get(field) is True for field in ("success", "done", "ledger_closed", "replicas_equal")):
        raise ValueError("corrected result must complete correctness and conservation")
    for field in ("vertices", "partitions", "pma_slots", "live_edges_per_round", "expected_rounds"):
        if corrected[field] != parent[field]:
            raise ValueError(f"corrected geometry or convergence differs: {field}")
    for result in (parent, corrected):
        counters = result["counters"]
        if (counters["axi_requests"] != counters["axi_completions"]
                or counters["axi_beats"] != counters["axi_completed_beats"]):
            raise ValueError("AXI traffic does not conserve")
    old = parent["counters"]["end_cycle"] - parent["counters"]["start_cycle"]
    new = corrected["counters"]["end_cycle"] - corrected["counters"]["start_cycle"]
    return {"version_1_every_result_field_equal": True, "ignored_result_fields": [],
            "version_1_cycles": old, "version_2_cycles": new,
            "version_2_over_version_1_cycles": new / old,
            "version_1_requests": parent["counters"]["axi_requests"],
            "version_2_requests": corrected["counters"]["axi_requests"]}


def package_channel_checkpoint(root: Path, data: Path, parent_data: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() for name in ("channels.json", "raw_channels.tar.gz")):
        raise FileExistsError("independent-channel checkpoint is already frozen")
    binding = json.loads((data / "baseline_binding.json").read_text())
    parent_pin = binding["parent_evidence"]
    if identity(Path(parent_pin["path"])) != parent_pin:
        raise ValueError("frozen parent evidence changed")
    legacy_contract = json.loads((root / "configs/experiments/grasu_component_refactor_v1.json").read_text())
    legacy = compare_runs(legacy_contract, Path(binding["baseline"]), data / "legacy_final")
    if legacy["status"] != "PASS" or legacy["correctness_admitted_cases"] != 5 or legacy["ignored_result_fields"]:
        raise ValueError("all five legacy results must remain exactly equivalent")
    expected = legacy["candidate_identity"]
    verify_source_snapshot(root, expected["source"])
    capped = json.loads((data / "capped_equivalence/summary.json").read_text())
    if (capped["status"] != "PASS" or capped["plugin"]["plugin_sha256"] != expected["plugin_sha256"]
            or {row["id"] for row in capped["rows"]} != {"au_original", "su_original"}
            or any(not row["every_result_field_equal"] or row["ignored_fields"] for row in capped["rows"])):
        raise ValueError("partial blocked-read runtime-equivalence checks are missing")
    profile = load_profile(root, root / "configs/architectures/grasu_regraph_routed_sssp_compute_v2.json")
    predecessor = binding["runtime_predecessor"]
    for name in ("source", "intentional_stop"):
        if identity(Path(predecessor[name]["path"])) != predecessor[name]:
            raise ValueError("runtime predecessor evidence changed")
    rtl = json.loads((data / "rtl_identity.json").read_text())
    if identity(Path(rtl["xo"]["path"])) != rtl["xo"] or any(
            identity(Path(pin["path"]))["sha256"] != pin["sha256"] for pin in rtl["members"]):
        raise ValueError("extracted measured RTL changed")
    if (profile["target"]["wrapper_xo_sha256"] != rtl["xo"]["sha256"]
            or profile["target"]["wrapper_top_rtl_sha256"] not in {pin["sha256"] for pin in rtl["members"]}):
        raise ValueError("measured top RTL is not bound to version 2")
    verification = {}
    for name in ("fresh_core_config", "fresh_core_build", "fresh_core_ctest", "plugin_build_final",
                 "legacy_regression", "python_gates_final"):
        record = json.loads((data / f"{name}.resources.json").read_text())
        if record["exit_code"] or record.get("timed_out", False):
            raise ValueError(f"required channel gate failed: {name}")
        verification[name] = record
    if "100% tests passed, 0 tests failed out of 23" not in (data / "fresh_core_ctest.stdout.txt").read_text():
        raise ValueError("complete 23-executable core gate missing")
    files, rows, fixtures, runtime_equivalence = {}, [], {}, []
    prior = Path(predecessor["path"])
    audits = json.loads((parent_data / "input_audits_final.json").read_text())
    for case in ("au", "su", "wk"):
        for arm in ("candidate", "original"):
            name = f"{case}_{arm}"
            directories = [parent_data / "matrix_final" / name, data / "legacy_v1_replay" / name,
                           data / "matrix_final" / name]
            results = [json.loads((directory / "result.json").read_text()) for directory in directories]
            row = {"id": name, **compare_channel_results(*results)}
            if arm == "candidate":
                prior_run = prior / "matrix_final" / name
                if (json.loads((prior_run / "result.json").read_text()) != results[-1]
                        or identity(prior_run / "result.json.values.txt")["sha256"] !=
                        identity(directories[-1] / "result.json.values.txt")["sha256"]):
                    raise ValueError("runtime-only optimization changed a complete v2 result")
                runtime_equivalence.append({"id": name, "every_result_field_equal": True,
                                            "complete_result_bytes_equal": True, "ignored_fields": []})
            values = [identity(directory / "result.json.values.txt")["sha256"] for directory in directories]
            if len(set(values)) != 1:
                raise ValueError("complete result bytes changed across versions")
            for directory in directories[1:]:
                manifest = json.loads((directory / "manifest.json").read_text())
                if manifest["source"] != expected["source"] or manifest["plugin"]["plugin_sha256"] != expected["plugin_sha256"]:
                    raise ValueError("all channel and legacy gates must bind identical source/plugin")
                for pin in manifest["pins"] + manifest["headers"]:
                    if identity(Path(pin["path"])) != pin:
                        raise ValueError("channel experiment input changed")
            summary = json.loads((directories[-1] / "summary.json").read_text())
            manifest = json.loads((directories[-1] / "manifest.json").read_text())
            board_path = Path(next(pin["path"] for pin in manifest["pins"] if Path(pin["path"]).name == "run.log"))
            board = analyze_log(board_path.read_text(), require_trace=True)
            row["timing"] = timing_diagnostic(results[-1], board)
            if row["timing"] != summary["timing"]:
                raise ValueError("saved timing analysis differs")
            if arm == "original":
                audit = next(item for item in audits["rows"] if item["id"] == case)
                row["tail_diagnostic"] = tail_diagnostic(results[-1], board, audit["audit"]["tails"])
            rows.append(row)
            fixture = directories[-1] / "resident.bin"
            if identity(fixture)["sha256"] != identity(directories[0] / "resident.bin")["sha256"]:
                raise ValueError("post-update resident PMA fixture changed")
            if case in fixtures and identity(fixture)["sha256"] != identity(fixtures[case])["sha256"]:
                raise ValueError("old/new arms use different resident fixtures")
            fixtures[case] = fixture
            for path in directories[0].glob("result.json*"):
                files[f"parent_results/{name}/{path.name}"] = path
    for directory in ("legacy_v1_replay", "matrix_final"):
        summary = json.loads((data / directory / "summary.json").read_text())
        if summary["status"] != "FUNCTIONAL_MATRIX_PASS_TIMING_UNADMITTED" or summary["hardware_timing_admitted"]:
            raise ValueError("complete predeclared matrix is required without timing admission")
    for case, fixture in fixtures.items():
        files[f"fixtures/{case}.bin"] = fixture
    for path in prior.rglob("*"):
        relative = path.relative_to(prior)
        if relative.parts[0] in {"core", "plugin_final"} or path.name == "resident.bin":
            continue
        if path.is_file() and path.suffix in {".json", ".txt", ".v"}:
            files["runtime_predecessor/" + str(relative)] = path
    files["runtime_predecessor/source_before_runtime_fix.tar.gz"] = Path(predecessor["source"]["path"])
    files["runtime_predecessor/libspine_cycle.so"] = prior / "plugin_final/libspine_cycle.so"
    for path in data.rglob("*"):
        relative = path.relative_to(data)
        if relative.parts[0] in {"core", "plugin_final"} or path.name == "resident.bin":
            continue
        if path.is_file() and (path.suffix in {".json", ".txt", ".v"}
                              or relative.parts[0] == "runtime_intermediate"):
            files["campaign/" + str(relative)] = path
    for pin in expected["source"]["files"]:
        files["source/simulator/" + pin["path"]] = root / pin["path"]
    for pattern in ("cpp/tests/axi/*.cpp", "cpp/tests/routed_regraph/*.cpp", "tests/test_sharded_k4_channels.py", "configs/architectures/*compute_v2.json",
                    "configs/experiments/sharded_k4_routed_sssp_timing_v*.json"):
        for path in root.glob(pattern):
            files["source/simulator/" + str(path.relative_to(root))] = path
    files["binaries/libspine_cycle.so"] = data / "plugin_final/libspine_cycle.so"
    for name in ("CMakeCache.txt", "cpp/CMakeFiles/spine_cycle_core.dir/flags.make",
                 "cpp/axi_independent_channels_tests", "cpp/routed_regraph_system_tests"):
        files["core_configuration/" + name] = data / "core" / name
    if identity(files["binaries/libspine_cycle.so"])["sha256"] != expected["plugin_sha256"]:
        raise ValueError("tested plugin changed")
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    archive_path = output / "raw_channels.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, path in sorted(files.items()):
            archive.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"]))["sha256"] != pin["sha256"] for pin in index):
        raise ValueError("channel evidence changed during packaging")
    atomic_write_json(output / "channels_raw_index.json", {"archive": identity(archive_path), "files": index,
                      "parent_raw_dependency": parent_pin})
    report = {"schema_version": 1, "status": "INDEPENDENT_CHANNELS_FUNCTIONAL_PASS_TIMING_DIAGNOSTIC",
              "hardware_timing_admitted": False, "original_A4_match_admitted": False,
              "legacy": legacy, "rows": rows, "verification": verification, "rtl": rtl,
              "runtime_only_optimization_equivalence": runtime_equivalence,
              "partial_observation_equivalence": capped,
              "parent_evidence": parent_pin,
              "limits": ["source_AXI_channel_correction_not_a_fitted_timing_multiplier",
                         "nominal_board_windows_include_host_gaps_absent_from_model",
                         "parent_raw_archive_supplies_graphs_exporter_and_prior_evidence",
                         "independent_channels_do_not_admit_original_A4_or_other_algorithms"]}
    atomic_write_json(output / "channels.json", report)
    return report
