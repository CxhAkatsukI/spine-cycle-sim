"""Archive routed-source identity, frontend gates and unchanged legacy results."""

import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.refactor_equivalence import compare_runs, verify_source_snapshot
from .execution import identity
from .model_frontend import REPORTS, require_report


def package_model_frontend(data: Path, integration: Path, output: Path) -> dict:
    del integration
    root = Path(__file__).resolve().parents[3]
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / "raw_frontend.tar.gz"
    if archive_path.exists() or (output / "frontend.json").exists():
        raise FileExistsError("frontend evidence already frozen")
    binding = json.loads((data / "baseline_binding.json").read_text())
    baseline = Path(binding["retained_run"])
    if sha256_file(baseline / "identity.json") != binding["retained_identity_sha256"]:
        raise ValueError("retained frontend baseline changed")
    contract = json.loads((root / "configs/experiments/grasu_component_refactor_v1.json").read_text())
    comparison = compare_runs(contract, baseline, data / "legacy_final")
    if comparison["status"] != "PASS" or comparison["correctness_admitted_cases"] != 5 or comparison["ignored_result_fields"]:
        raise ValueError("all five legacy cases must match without ignored fields")
    if comparison != json.loads((data / "legacy_final/equivalence.json").read_text()):
        raise ValueError("saved legacy comparison differs from raw results")
    final = json.loads((data / "legacy_final/identity.json").read_text())
    verify_source_snapshot(root, final["source"])
    core = json.loads((data / "final_core_gate_identity.json").read_text())
    if core["source"] != final["source"]:
        raise ValueError("core and SST source identities differ")
    gate_dir = data / "frontend_artifact"
    gate = json.loads((gate_dir / "summary.json").read_text())
    manifest = json.loads((gate_dir / "manifest.json").read_text())
    if gate["status"] != "PASS" or gate["reports"] != REPORTS or not gate["source_unchanged"]:
        raise ValueError("complete frontend component gates required")
    if gate["hardware_artifact"] != manifest["hardware_artifact"] or gate["hardware_artifact"]["masters"] != [
            "M_AXI_GMEM1", "M_AXI_GMEM2", "M_AXI_GMEM3", "M_AXI_GMEM4"]:
        raise ValueError("measured SSSP source-master identity differs")
    pins = manifest["sources_and_executables"] + gate["hls_executables"] + core["executables"]
    if any(identity(Path(pin["path"])) != pin for pin in pins):
        raise ValueError("tested source or executable changed")
    for attempt in gate["attempts"]:
        if attempt["resources"]["exit_code"] or attempt["resources"]["timed_out"]:
            raise ValueError("frontend component process failed")
    for name in REPORTS:
        require_report(name, (gate_dir / f"{name}.stdout.txt").read_text())
    verification = {}
    for name in ("artifact_core_build", "final_core_ctest", "plugin_build", "legacy_regression"):
        resource = json.loads((data / f"{name}.resources.json").read_text())
        if resource["exit_code"] or resource["timed_out"]:
            raise ValueError("final core, plugin or regression failed")
        verification[name] = resource
    if "100% tests passed, 0 tests failed out of 20" not in (data / "final_core_ctest.stdout.txt").read_text():
        raise ValueError("complete 20-executable core gate missing")
    files = {}
    for name, directory in (("before", baseline), ("legacy_final", data / "legacy_final")):
        for path in directory.rglob("*"):
            if path.is_file():
                files[name + "/" + str(path.relative_to(directory))] = path
    for path in data.rglob("*"):
        relative = path.relative_to(data)
        if relative.parts[0] in {"core", "plugin", "legacy_final"}:
            continue
        if path.is_file() and path.suffix in {".json", ".txt", ".gz", ".cpp"}:
            files[str(relative)] = path
    for pin in final["source"]["files"]:
        files["source/simulator/" + pin["path"]] = root / pin["path"]
    for pin in manifest["sources_and_executables"]:
        path = Path(pin["path"])
        if path.suffix not in {".py", ".hpp", ".cpp", ".h", ".json", ".tsv", ".xo"}:
            continue
        name = "source/simulator/" + str(path.relative_to(root)) if path.is_relative_to(root) else "source/external/" + str(path).lstrip("/")
        files[name] = path
    index = [{"archive_path": name, **identity(path)} for name, path in sorted(files.items())]
    with tarfile.open(archive_path, "w:gz") as archive:
        for name, path in sorted(files.items()):
            archive.add(path, arcname=name, recursive=False)
    if any(identity(Path(pin["path"])) != {key: pin[key] for key in ("path", "sha256")} for pin in index):
        raise ValueError("frontend delivery inputs changed during packaging")
    atomic_write_json(output / "frontend_raw_index.json", {"archive": identity(archive_path), "files": index})
    result = {"schema_version": 1, "status": "LEGACY_EQUIVALENCE_AND_FRONTEND_FUNCTIONAL_PASS",
              "claim": "bounded_frontend_components_not_system_or_hardware_timing",
              "legacy": comparison, "frontend": gate, "verification": verification,
              "source_topology_correction": "measured_SSSP_XO_has_four_masters_worktree_has_two",
              "remaining": ["whole_lksg_ingress_gather_lifetime", "independent_four_worker_dispatch",
                            "shared_round_backend", "explicit_artifact_bound_candidate_profile",
                            "matched_hardware_timing", "matched_original_A4_comparison"]}
    atomic_write_json(output / "frontend.json", result)
    return result
