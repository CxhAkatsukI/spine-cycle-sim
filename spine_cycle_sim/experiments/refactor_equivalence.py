"""Freeze source identities and require exact execution-result equivalence."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Mapping

from .campaign_runtime import sha256_file


SEMANTIC_IDENTITIES = (
    "profile_sha256", "workload_sha256", "update_workload_sha256", "update_sha256",
    "capability_catalog_sha256", "algorithm_capability", "resident_state",
    "measurement_window", "supersteps", "residual_contract", "downstream_sharing",
    "sst_memory_binding", "physical_hbm_address_regions", "core_mhz",
)


def source_snapshot(root: Path, contract_path: Path, contract: Mapping[str, Any]) -> dict:
    paths = {contract_path.resolve()}
    for directory in ("cpp/include", "cpp/src", "cpp/sst", "sst"):
        paths.update(path for path in (root / directory).rglob("*")
                     if path.suffix in {".cpp", ".hpp", ".py"})
    paths.update(root / name for name in (
        "CMakeLists.txt", "cpp/CMakeLists.txt", "cpp/sst/Makefile",
        "configs/contracts/grasu_regraph_sharded_k4_hls_capabilities_v8.json",
        "configs/memory/HBM2_1ch_x128.ini",
        "scripts/run_grasu_refactor_regression.py",
        "spine_cycle_sim/experiments/refactor_equivalence.py",
    ))
    for case in contract["cases"]:
        paths.update(root / case[field] for field in ("runner", "profile", "workload", "updates"))
    return {
        "revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "relevant_dirty_diff": subprocess.check_output(
            ["git", "diff", "HEAD", "--", "cpp/include", "cpp/src", "cpp/sst", "cpp/CMakeLists.txt"],
            cwd=root, text=True,
        ),
        "compiler": subprocess.check_output([contract["build"]["compiler"], "--version"], text=True).splitlines()[0],
        "declared_build": contract["build"],
        "dramsim3_library_sha256": sha256_file(Path(contract["build"]["dramsim3_root"]) / "libdramsim3.so"),
        "files": [{"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)}
                  for path in sorted(paths)],
    }


def verify_source_snapshot(root: Path, snapshot: Mapping[str, Any]) -> None:
    changed = [row["path"] for row in snapshot["files"]
               if not (root / row["path"]).is_file()
               or sha256_file(root / row["path"]) != row["sha256"]]
    if changed:
        raise ValueError(f"source or inputs changed during the campaign: {changed}")


def case_command(root: Path, case: Mapping[str, Any], lib_dir: Path, case_dir: Path,
                 *, timeout_seconds: int = 240) -> list[str]:
    import sys

    if timeout_seconds <= 0:
        raise ValueError("case timeout must be positive")
    return [
        "timeout", "--signal=TERM", "--kill-after=10s", f"{timeout_seconds}s", sys.executable,
        str(root / case["runner"]), "--no-build", "--profile", str(root / case["profile"]),
        "--capability-catalog", str(root / "configs/contracts/grasu_regraph_sharded_k4_hls_capabilities_v8.json"),
        "--workload", str(root / case["workload"]), "--update-workload", str(root / case["updates"]),
        "--lib-dir", str(lib_dir), "--out-dir", str(case_dir),
        *case["arguments"],
    ]


def compare_result_payloads(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict:
    if before.get("success") is not True or after.get("success") is not True:
        raise ValueError("refactor inputs must both pass correctness")
    changed = sorted(key for key in set(before) | set(after)
                     if key not in before or key not in after or before[key] != after[key])
    return {"equivalent": not changed, "changed_fields": changed}


def compare_runs(contract: Mapping[str, Any], baseline_dir: Path, candidate_dir: Path) -> dict:
    identities = [json.loads((directory / "identity.json").read_text())
                  for directory in (baseline_dir, candidate_dir)]
    if identities[0]["contract_sha256"] != identities[1]["contract_sha256"]:
        raise ValueError("refactor comparison changed the predeclared case matrix")
    if identities[0]["source"]["compiler"] != identities[1]["source"]["compiler"]:
        raise ValueError("refactor comparison changed the compiler")
    for field in ("declared_build", "dramsim3_library_sha256"):
        if identities[0]["source"][field] != identities[1]["source"][field]:
            raise ValueError(f"refactor comparison changed {field}")
    rows = []
    for case in contract["cases"]:
        directories = [directory / "cases" / case["id"] for directory in (baseline_dir, candidate_dir)]
        results = [json.loads((directory / "result.json").read_text()) for directory in directories]
        manifests = [json.loads((directory / case["manifest"]).read_text()) for directory in directories]
        for manifest, identity in zip(manifests, identities):
            if manifest.get("status") != "PASS" or manifest.get("sst_plugin_sha256") != identity["plugin_sha256"]:
                raise ValueError(f"{case['id']}: unaccepted result or wrong plugin binding")
        changed_identities = [field for field in SEMANTIC_IDENTITIES
                              if manifests[0].get(field) != manifests[1].get(field)]
        comparison = compare_result_payloads(*results)
        rows.append({
            "case": case["id"], **comparison,
            "changed_manifest_identities": changed_identities,
            "cycles": results[0]["cycles"], "backend_requests": results[0]["backend_requests"],
            "result_hashes": [sha256_file(directory / "result.json") for directory in directories],
        })
    return {
        "schema_version": 1,
        "claim": "exact_result_equivalence_on_predeclared_regression_matrix",
        "status": "PASS" if all(row["equivalent"] and not row["changed_manifest_identities"] for row in rows) else "FAIL",
        "ignored_result_fields": [], "cases": rows,
        "baseline_identity": identities[0], "candidate_identity": identities[1],
    }
