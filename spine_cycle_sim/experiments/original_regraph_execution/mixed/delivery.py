"""Re-admit mixed evidence and package reproducible logs, keeping large states indexed."""

import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_validation.analysis import same_typed
from .analysis import STATUS, analyze, matrix
from .preparation import verify
from .regression import recheck
from .study import identities


def should_archive(relative: Path) -> bool:
    # Exclude damaged input directories, but retain root-level rejection logs.
    if any(part in ("CMakeFiles", "legacy_a4", "legacy_a4_inputs") or part.startswith("negative_")
           for part in relative.parts[:-1]): return False
    return relative.name.endswith((".stdout.txt", ".stderr.txt", ".resources.json", "dependencies.d")) or relative.name in (
        "report.json", "contract.json", "analysis.json", "mixed.u32le", "CMakeCache.txt", "compile_commands.json", "LastTest.log")


def deliver(root: Path, run: Path, destination: Path) -> dict:
    report = json.loads((run / "report.json").read_text()); contract = json.loads((run / "contract.json").read_text())
    canonical = root / "configs/experiments/original_regraph_mixed_execution_v1.json"
    if (report.get("status") != STATUS or report.get("ubsan_identical_no_diagnostics") is not True or
            report["source_identities"] != identities(root) or report["contract_sha256"] != sha256_file(canonical) or
            not same_typed(contract, json.loads(canonical.read_text())) or report["FPGA_cycles"] is not None or
            report["publication_error_pct"] is not None): raise ValueError("mixed checkpoint incomplete or changed")
    if [row["id"] for row in report["cases"]] != [row["id"] for row in contract["cases"]]: raise ValueError("mixed matrix changed")
    verify(report["inputs"])
    recheck(root, run, report)
    if len(report["legacy"]["checks"]) != 16 or any(item["identical"] is not True for item in report["legacy"]["checks"]):
        raise ValueError("mixed complete regression missing")
    negatives = report["negative_controls"]
    if [item["id"] for item in negatives] != ["capacity_boundary_ring", "capacity_amazon", "header", "assignment", "source",
            "arithmetic", "edge_value", "truncated"] or any(item["expected_rejection"] is not True for item in negatives):
        raise ValueError("mixed negative/allocation gates missing")
    for item in negatives:
        if "path" in item and sha256_file(Path(item["path"])) != item["sha256"]: raise ValueError("mixed negative input changed")
    if len({item["id"] for item in report["steps"]}) != len(report["steps"]): raise ValueError("mixed duplicate raw step identity")
    for step in report["steps"]:
        if step["timed_out"] or step["exit_code"] != int(step["id"].startswith("negative_")):
            raise ValueError("mixed raw step contains unexpected failure")
        if step["id"].startswith("negative_"):
            item = next(item for item in negatives if item["id"] == step["id"].removeprefix("negative_"))
            if item["diagnostic"] not in Path(step["stderr"]).read_text(): raise ValueError("mixed rejection diagnostic changed")
    for case, row in zip(contract["cases"], report["cases"], strict=True):
        admitted = next(item for item in report["inputs"] if item["id"] == case["input"])
        for suffix, observed in zip(("first", "repeat"), row["runs"], strict=True):
            step = next(item for item in report["steps"] if item["id"] == case["id"] + "_" + suffix)
            if (Path(step["stderr"]).read_text() or sha256_file(Path(observed["directory"]) / "analysis.json") != observed["sha256"] or
                    not same_typed(analyze(Path(step["stdout"]).read_text(), Path(observed["directory"]), case, admitted, contract), observed["analysis"])):
                raise ValueError("mixed raw output/state changed")
        if row["status"] != STATUS or not same_typed(row["runs"][0]["analysis"], row["runs"][1]["analysis"]):
            raise ValueError("mixed complete repeated result differs")
        if case["id"] in contract["instrumented_cases"]:
            step = next(item for item in report["steps"] if item["id"] == case["id"] + "_ubsan")
            if Path(step["stderr"]).read_text() or not same_typed(analyze(Path(step["stdout"]).read_text(), run / "ubsan" / case["id"],
                    case, admitted, contract), row["runs"][0]["analysis"]): raise ValueError("mixed instrumented output changed")
    if not same_typed(matrix(report["cases"]), report["analysis"]): raise ValueError("mixed matrix analysis changed")
    for item in report["binaries"]:
        for identity in [item, *item.get("dependencies", [])]:
            if sha256_file(Path(identity["path"])) != identity["sha256"]: raise ValueError("mixed dependency or binary changed")
    baseline = Path(report["legacy_baseline"])
    if sha256_file(baseline / "baseline.json") != report["legacy"]["baseline_sha256"]: raise ValueError("mixed baseline changed")
    files = [(path, "baseline/" + path.name) for path in sorted(baseline.iterdir()) if path.is_file()]
    for path in sorted(run.rglob("*")):
        rel = path.relative_to(run)
        if not path.is_file() or path.is_symlink(): continue
        if should_archive(rel):
            files.append((path, "mixed/" + rel.as_posix()))
    index = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path, name in files]
    destination.mkdir(parents=True, exist_ok=True)
    paths = [destination / name for name in ("mixed_results.json", "mixed_verification.json", "raw_mixed_execution.tar.gz")]
    if any(path.exists() for path in paths): raise ValueError("refuse to overwrite mixed delivery")
    with tarfile.open(paths[2], "w:gz") as bundle:
        for path, name in files: bundle.add(path, arcname=name, recursive=False)
    with tarfile.open(paths[2], "r:gz") as bundle:
        if bundle.getnames() != [item["path"] for item in index]: raise ValueError("mixed archive membership changed")
        for item in index:
            with bundle.extractfile(item["path"]) as stream:
                if hashlib.sha256(stream.read()).hexdigest() != item["sha256"]: raise ValueError("mixed archive member changed")
    if any(sha256_file(path) != item["sha256"] for (path, _), item in zip(files, index, strict=True)): raise ValueError("mixed raw evidence changed while packaging")
    shutil.copyfile(run / "report.json", paths[0])
    record = {"schema_version": 1, "status": STATUS, "files": index, "archive_sha256": sha256_file(paths[2]),
        "archive_bytes": paths[2].stat().st_size, "results_sha256": sha256_file(paths[0]),
        "raw_source_input_binary_and_archive_members_rechecked": True,
        "indexed_not_archived": ["complete_state_replicas", "original_host_captures_regenerate_from_input_checkpoint"],
        "excluded": ["compiled_binaries", "regenerable_malformed_inputs"]}
    atomic_write_json(paths[1], record); return record
