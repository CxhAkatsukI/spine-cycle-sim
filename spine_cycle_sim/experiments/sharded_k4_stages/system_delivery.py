"""Freeze complete candidate SSSP gates and exact unchanged legacy SST evidence."""

import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.refactor_equivalence import compare_runs, verify_source_snapshot
from .execution import identity
from .model_system import require_system_report


def package_model_system(data: Path, integration: Path, output: Path) -> dict:
    del integration
    root = Path(__file__).resolve().parents[3]
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / "raw_system.tar.gz"
    if archive_path.exists() or (output / "system.json").exists():
        raise FileExistsError("system evidence already frozen")
    binding = json.loads((data / "baseline_binding.json").read_text())
    baseline = Path(binding["baseline"])
    contract = json.loads((root / "configs/experiments/grasu_component_refactor_v1.json").read_text())
    comparison = compare_runs(contract, baseline, data / "legacy_final")
    if comparison["status"] != "PASS" or comparison["correctness_admitted_cases"] != 5 or comparison["ignored_result_fields"]:
        raise ValueError("all five exact legacy SST results are required")
    if comparison != json.loads((data / "legacy_final/equivalence.json").read_text()):
        raise ValueError("saved legacy comparison differs from raw results")
    final = json.loads((data / "legacy_final/identity.json").read_text())
    gate_dir = data / "system_final"
    gate = json.loads((gate_dir / "summary.json").read_text())
    if gate["status"] != "PASS" or not gate["source_unchanged"] or gate["source"] != final["source"]:
        raise ValueError("candidate and legacy gates must bind identical unchanged source")
    verify_source_snapshot(root, final["source"])
    if gate["rows"] != require_system_report((gate_dir / "system.stdout.txt").read_text()):
        raise ValueError("whole-system saved matrix differs from its raw report")
    for pin in gate["artifacts"] + gate["gate_sources"]:
        if identity(Path(pin["path"])) != pin:
            raise ValueError("tested candidate binary, library or compile configuration changed")
    for attempt in gate["attempts"]:
        resource = attempt["resources"]
        if resource["exit_code"] or resource["timed_out"]:
            raise ValueError("candidate system gate failed")
    verification = {}
    for name in ("admitted_core_build", "admitted_core_ctest", "admitted_plugin_build", "legacy_regression"):
        resource = json.loads((data / f"{name}.resources.json").read_text())
        if resource["exit_code"] or resource["timed_out"]:
            raise ValueError("complete core, plugin and legacy gates are required")
        verification[name] = resource
    if "100% tests passed, 0 tests failed out of 21" not in (data / "admitted_core_ctest.stdout.txt").read_text():
        raise ValueError("complete 21-executable core test gate missing")
    files = {}
    for name, directory in (("before", baseline), ("legacy_final", data / "legacy_final")):
        for path in directory.rglob("*"):
            if path.is_file(): files[name + "/" + str(path.relative_to(directory))] = path
    for path in data.rglob("*"):
        relative = path.relative_to(data)
        if relative.parts[0] in {"core", "plugin", "plugin_final", "legacy_final"}: continue
        if path.is_file() and path.suffix in {".json", ".txt", ".gz"}: files[str(relative)] = path
    for pin in final["source"]["files"]:
        files["source/simulator/" + pin["path"]] = root / pin["path"]
    for pin in gate["artifacts"]:
        path = Path(pin["path"])
        if path.name in {"CMakeCache.txt", "flags.make", "link.txt"}:
            files["build_configuration/" + path.name] = path
    # Source discovery deliberately excludes tests; include every compiled
    # candidate fixture and its independent per-round software oracle.
    for path in (root / "cpp/tests/routed_regraph").glob("*.cpp"):
        files["source/simulator/" + str(path.relative_to(root))] = path
    files["source/simulator/scripts/validate_sharded_k4_system_model.py"] = root / "scripts/validate_sharded_k4_system_model.py"
    files["source/simulator/scripts/package_sharded_k4_adapter_gates.py"] = root / "scripts/package_sharded_k4_adapter_gates.py"
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, path in sorted(files.items()): archive.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"])) != {key: pin[key] for key in ("path", "sha256")} for pin in index):
        raise ValueError("system delivery inputs changed during packaging")
    atomic_write_json(output / "system_raw_index.json", {"archive": identity(archive_path), "files": index})
    result = {"schema_version": 1, "status": "SSSP_SYSTEM_FUNCTIONAL_AND_LEGACY_EQUIVALENCE_PASS",
              "claim": "candidate_compute_system_not_hardware_calibration_or_original_A4_match",
              "legacy": comparison, "system": gate, "verification": verification,
              "remaining": ["explicit_artifact_bound_SST_candidate_profile", "matched_FPGA_timing",
                            "matched_original_A4_comparison", "other_algorithms_routed_topology_admission"]}
    atomic_write_json(output / "system.json", result)
    return result
