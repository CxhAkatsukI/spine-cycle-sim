"""Package adapter functionality and exact legacy regression, not timing admission."""

import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.refactor_equivalence import compare_runs
from .execution import identity
from .model_adapter import require_case_report


def package_model_adapter(data: Path, integration: Path, output: Path) -> dict:
    del integration  # HLS identities are pinned by the shared-fixture manifest.
    root = Path(__file__).resolve().parents[3]
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / "raw_model_adapter.tar.gz"
    if archive_path.exists() or (output / "model_adapter.json").exists():
        raise FileExistsError("model-adapter evidence already frozen")
    contract = json.loads((root / "configs/experiments/grasu_component_refactor_v1.json").read_text())
    comparisons = {}
    for name in ("extracted", "candidate", "candidate_final"):
        comparison = compare_runs(contract, data / "before", data / name)
        if comparison["status"] != "PASS" or comparison["correctness_admitted_cases"] != 5:
            raise ValueError("both extraction and final full-result equivalence required")
        if comparison != json.loads((data / name / "equivalence.json").read_text()):
            raise ValueError("saved equivalence differs from raw results")
        comparisons[name] = {key: comparison[key] for key in
            ("status", "claim", "cases", "ignored_result_fields", "correctness_admitted_cases", "known_rejections")}
    shared = data / "shared_fixture_completion"
    manifest = json.loads((shared / "manifest.json").read_text())
    checks = json.loads((shared / "summary.json").read_text())
    if checks["status"] != "PASS" or checks["hls_fixture_calls"] != 324 or checks["hls_variants"] != 12:
        raise ValueError("all twelve HLS variants required")
    pins = manifest["sources_and_executable"]
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("adapter source or tested executable changed")
    for attempt in checks["attempts"]:
        resources = attempt["resources"]
        if resources["exit_code"] != 0 or resources["timed_out"]:
            raise ValueError("adapter validation process failed")
        name = attempt["name"]
        if name == "cycle_model" or name.endswith("_run"):
            require_case_report((shared / f"{name}.stdout.txt").read_text(), hls=name != "cycle_model")
    verification = {}
    for name in ("baseline_build", "extracted_build", "candidate_build", "candidate_final_build", "core_final_ctest"):
        resource = json.loads((data / f"{name}.resources.json").read_text())
        if resource["exit_code"] != 0 or resource["timed_out"]:
            raise ValueError("build or core test failed")
        verification[name] = resource
    files = {}

    def add(path: Path) -> None:
        files[str(path.relative_to(data))] = path

    for name in ("before", "extracted", "candidate", "candidate_final"):
        for path in (data / name).rglob("*"):
            if path.is_file():
                add(path)
    for name in ("shared_fixture_hls", "shared_fixture_hls_single_tu", "shared_fixture_final", "shared_fixture_completion"):
        for path in (data / name).iterdir():
            if path.suffix in (".json", ".txt"):
                add(path)
    for path in data.glob("*"):
        if path.is_file() and path.suffix in (".json", ".txt"):
            add(path)
    source_paths = [Path(pin["path"]) for pin in pins if Path(pin["path"]).suffix in (".py", ".hpp", ".cpp")]
    source_paths += [root / "cpp/src/grasu_regraph.cpp", root / "cpp/src/grasu_regraph_legacy_reader.cpp",
                     root / "cpp/src/detail/grasu_regraph_streams.hpp", root / "cpp/CMakeLists.txt",
                     root / "cpp/sst/Makefile", Path(__file__)]
    for path in source_paths:
        if path.is_relative_to(root):
            name = "source/simulator/" + str(path.relative_to(root))
        else:
            name = "source/integration/" + path.name
        files[name] = path
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, path in sorted(files.items()):
            archive.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"]))["sha256"] != pin["sha256"] for pin in index):
        raise ValueError("model delivery input changed while packaging")
    atomic_write_json(output / "model_raw_index.json", {"archive": identity(archive_path), "files": index})
    result = {"schema_version": 1, "status": "LEGACY_EQUIVALENCE_AND_ADAPTER_FUNCTIONAL_PASS",
              "claim": "new_component_packet_and_finite_resource_checks_not_system_timing",
              "legacy": comparisons, "adapter": checks, "verification": verification,
              "remaining": ["production_candidate_scatter_and_completion_wiring",
                            "independent_frontend_dispatch_and_shared_round_backend",
                            "matched_hardware_component_and_system_timing",
                            "matched_original_A4_vs_actual_K4", "publication_speed_match"]}
    atomic_write_json(output / "model_adapter.json", result)
    return result
