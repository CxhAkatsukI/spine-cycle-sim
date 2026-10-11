"""Freeze compute extraction and finite shared-port gates, not system timing."""

import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.refactor_equivalence import compare_runs, verify_source_snapshot
from .execution import identity


def package_model_compute(data: Path, integration: Path, output: Path) -> dict:
    del integration  # No HLS changes or new board claims in this checkpoint.
    root = Path(__file__).resolve().parents[3]
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / "raw_compute_ports.tar.gz"
    if archive_path.exists() or (output / "compute_ports.json").exists():
        raise FileExistsError("compute-port evidence already frozen")
    binding = json.loads((data / "baseline_binding.json").read_text())
    baseline = Path(binding["retained_run"])
    if sha256_file(baseline / "identity.json") != binding["retained_identity_sha256"]:
        raise ValueError("retained baseline identity changed")
    contract = json.loads((root / "configs/experiments/grasu_component_refactor_v1.json").read_text())
    comparisons = {}
    for name in ("extracted", "shared", "shared_final"):
        comparison = compare_runs(contract, baseline, data / name)
        if comparison["status"] != "PASS" or comparison["correctness_admitted_cases"] != 5:
            raise ValueError("both extraction and endpoint full-result equivalence required")
        if comparison != json.loads((data / name / "equivalence.json").read_text()):
            raise ValueError("saved equivalence differs from raw results")
        comparisons[name] = {key: comparison[key] for key in (
            "status", "claim", "cases", "ignored_result_fields", "correctness_admitted_cases", "known_rejections")}
    current = json.loads((data / "shared_final/identity.json").read_text())
    verify_source_snapshot(root, current["source"])
    gates = json.loads((data / "final_core_gate_identity.json").read_text())
    if gates["source"] != current["source"]:
        raise ValueError("core and final SST gates do not share the same source snapshot")
    for pin in gates["executables"] + gates["test_sources"]:
        if identity(Path(pin["path"])) != pin:
            raise ValueError("tested core executable or fixture source changed")
    verification = {}
    for name in ("core_build_fixed", "extraction_ctest", "extracted_plugin_build", "extraction_regression",
                 "shared_plugin_build", "final_core_build", "final_core_ctest", "shared_regression", "shared_final_regression",
                 "final_shared_axi_test", "final_connected_compute_test"):
        resource = json.loads((data / f"{name}.resources.json").read_text())
        if resource["exit_code"] != 0 or resource["timed_out"]:
            raise ValueError(f"required compute gate failed: {name}")
        verification[name] = resource
    reports = {
        "final_shared_axi_test": "PASS: 72 shared-master pressure/order/conservation cases",
        "final_connected_compute_test": "PASS: 25 connected Apply/writeback full-state and traffic cases",
    }
    for name, expected in reports.items():
        if (data / f"{name}.stdout.txt").read_text().strip() != expected:
            raise ValueError(f"component case set changed: {name}")
    if "100% tests passed, 0 tests failed out of 18" not in (data / "final_core_ctest.stdout.txt").read_text():
        raise ValueError("complete 18-executable CTest gate missing")
    source_index = json.loads((data / "extracted_source_index.json").read_text())
    if sha256_file(data / "extracted_source.tar.gz") != source_index["archive_sha256"]:
        raise ValueError("extraction source archive changed")
    files = {}
    for name, directory in (("before", baseline), ("extracted", data / "extracted"),
                            ("shared", data / "shared"), ("shared_final", data / "shared_final")):
        for path in directory.rglob("*"):
            if path.is_file():
                files[name + "/" + str(path.relative_to(directory))] = path
    for path in data.iterdir():
        if path.is_file() and path.suffix in (".json", ".txt", ".gz"):
            files[path.name] = path
    for pin in current["source"]["files"]:
        files["source/" + pin["path"]] = root / pin["path"]
    for path in (root / "cpp/tests/routed_regraph").glob("*.*"):
        if path.suffix in (".cpp", ".hpp"):
            files["source/" + str(path.relative_to(root))] = path
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, path in sorted(files.items()):
            archive.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"]))["sha256"] != pin["sha256"] for pin in index):
        raise ValueError("compute delivery source changed while packaging")
    atomic_write_json(output / "compute_raw_index.json", {"archive": identity(archive_path), "files": index})
    result = {
        "schema_version": 1, "status": "LEGACY_EQUIVALENCE_AND_SHARED_COMPUTE_PORT_PASS",
        "claim": "extracted_arithmetic_and_finite_shared_ports_not_complete_routed_system",
        "legacy": comparisons, "verification": verification,
        "component_cases": {"shared_axi": 72, "connected_compute": 25, "ctest_executables": 18},
        "remaining": ["production_candidate_scatter_and_pairwise_source_service",
                      "independent_adapter_gather_dispatch_and_ordered_mux",
                      "one_round_shared_apply_hbm_lifetime_and_status_write",
                      "distinct_candidate_profile_and_complete_system_gates",
                      "matched_hardware_component_and_system_timing",
                      "matched_original_A4_vs_actual_K4", "publication_speed_match"],
    }
    atomic_write_json(output / "compute_ports.json", result)
    return result
