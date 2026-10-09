"""Re-admit actual source packets and all A4 observations; no matched timing claim."""

import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..analysis import analyze as analyze_a4
from ..preparation import verify_inputs
from .analysis import STATUS, analyze
from .regression import preserve
from .study import identities
from .validation import INPUT_NEGATIVES, capture_negatives


def recheck(root: Path, run: Path):
    report = json.loads((run / "report.json").read_text()); contract = json.loads((run / "contract.json").read_text())
    canonical = root / "configs/experiments/original_regraph_adapter_source_v1.json"
    if (report["status"] != STATUS or report["source_identities"] != identities(root) or contract != json.loads(canonical.read_text()) or
            report["contract_sha256"] != sha256_file(canonical) or report["adapter_sha256"] != contract["adapter_source_sha256"] or
            sha256_file(run / "source/pma_to_regraph_adapter.cpp") != contract["adapter_source_sha256"] or
            report["device_cycles"] is not None or report["matched_A4_B_overhead"] is not None): raise ValueError("adapter source checkpoint incomplete or changed")
    baseline = Path(report["baseline"]); previous = json.loads((baseline / "baseline.json").read_text())
    if preserve(root, baseline) != report["preservation"]: raise ValueError("adapter old-source preservation changed")
    required = ["adapter_normal_compile", "adapter_ubsan_compile"]
    required += ["adapter_" + name + "_" + suffix for name in contract["inputs"] for suffix in ("first", "repeat", "ubsan")]
    required += ["negative_" + name for name, *_ in INPUT_NEGATIVES]
    required += ["configure", "build", "ctest"] + ["a4_" + row["id"] for row in previous["cases"]]
    required += ["ubsan_compile"] + [name + "_ubsan" for name in previous["contract"]["instrumented_cases"]] + ["focused_tests"]
    steps = {step["id"]: step for step in report["steps"]}
    if list(steps) != required or len(steps) != len(report["steps"]): raise ValueError("adapter complete source/regression steps missing")
    for name, step in steps.items():
        expected = 1 if name.startswith("negative_") else 0
        if step["exit_code"] != expected or step["timed_out"]: raise ValueError("adapter raw step status changed")
        resources = json.loads((run / (name + ".resources.json")).read_text())
        if resources != {key: value for key, value in step.items() if key != "id"}: raise ValueError("adapter resources changed")
    verify_inputs(report["inputs"]); indexed = []
    if [row["id"] for row in report["cases"]] != contract["inputs"] or [row["id"] for row in report["inputs"]] != contract["inputs"]: raise ValueError("adapter full matrix changed")
    for item, row in zip(report["inputs"], report["cases"], strict=True):
        directory = Path(item["directory"])
        for field in item["adapter_layout"]["files"]:
            path = directory / field["name"]
            if sha256_file(path) != field["sha256"] or path.stat().st_size != field["bytes"]: raise ValueError("adapter input changed")
            indexed.append({"path": str(path), **field})
        if row["status"] != STATUS or len(row["runs"]) != 3: raise ValueError("adapter repeated/instrumented cases incomplete")
        for suffix, observed in zip(("first", "repeat", "ubsan"), row["runs"], strict=True):
            step = steps["adapter_" + row["id"] + "_" + suffix]; capture = Path(observed["directory"])
            value = analyze(directory, capture, Path(step["stdout"]), Path(step["stderr"]))
            if value != observed["analysis"] or value != row["runs"][0]["analysis"]: raise ValueError("adapter raw capture changed")
            indexed.append({"path": str(capture / "adapter_edges.u32le"), "bytes": value["capture_bytes"], "sha256": value["capture_sha256"]})
    for name, filename, _, _, diagnostic in INPUT_NEGATIVES:
        if diagnostic not in Path(steps["negative_" + name]["stderr"]).read_text(): raise ValueError("adapter input negative changed")
    step = steps["adapter_boundary_ring_first"]; inputs = Path(report["inputs"][0]["directory"])
    if capture_negatives(inputs, run / "captures/boundary_ring/first", Path(step["stdout"]), Path(step["stderr"])) != report["capture_negatives"]:
        raise ValueError("adapter actual-output negative changed")
    regression = report["wiring_regression"]
    if regression["all_eight_full_observations_identical"] is not True or regression["ubsan_three_inputs_identical"] is not True: raise ValueError("adapter A4 extraction not admitted")
    if len(regression["cases"]) != len(previous["cases"]): raise ValueError("adapter A4 regression cases missing")
    for case, old, observed in zip(previous["contract"]["cases"], previous["cases"], regression["cases"], strict=True):
        item = next(item for item in report["inputs"] if item["id"] == case["input"]); step = steps["a4_" + case["id"]]
        value = analyze_a4(Path(step["stdout"]).read_text(), Path(observed["runs"][0]["directory"]), case, item, previous["contract"])
        if old["analysis"] != value or value != observed["runs"][0]["analysis"] or Path(step["stdout"]).read_text() != old["stdout"]: raise ValueError("adapter A4 raw regression changed")
        for field in value["files"]: indexed.append({**field, "path": str(Path(observed["runs"][0]["directory"]) / field["path"])})
    for name in previous["contract"]["instrumented_cases"]:
        case = next(row for row in previous["contract"]["cases"] if row["id"] == name); item = next(item for item in report["inputs"] if item["id"] == case["input"])
        step = steps[name + "_ubsan"]; value = analyze_a4(Path(step["stdout"]).read_text(), run / "ubsan" / name, case, item, previous["contract"])
        if value != next(row for row in previous["cases"] if row["id"] == name)["analysis"] or Path(step["stderr"]).read_text(): raise ValueError("adapter A4 UBSan changed")
    for binary in report["binaries"] + regression["binaries"]:
        for field in [binary, *binary.get("dependencies", [])]:
            if sha256_file(Path(field["path"])) != field["sha256"]: raise ValueError("adapter dependency/binary changed")
    return report, indexed


def deliver(root: Path, run: Path, destination: Path, attempts: tuple[Path, ...] = ()):
    report, indexed = recheck(root, run)
    if len(set(attempts)) != len(attempts) or run in attempts: raise ValueError("adapter duplicate historical attempt")
    files = [(Path(report["baseline"]) / "baseline.json", "baseline/baseline.json")]
    for directory, prefix in [(run, "adapter"), *((attempt, "attempts/" + attempt.name) for attempt in attempts)]:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.is_symlink() and path.suffix in (".json", ".txt", ".d", ".cpp"):
                files.append((path, prefix + "/" + path.relative_to(directory).as_posix()))
    index = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path, name in files]
    if len({item["path"] for item in index}) != len(index): raise ValueError("adapter duplicate archive members")
    destination.mkdir(parents=True, exist_ok=True)
    results, verification, archive = [destination / name for name in ("adapter_source_results.json", "adapter_source_verification.json", "raw_adapter_source.tar.gz")]
    if any(path.exists() for path in (results, verification, archive)): raise ValueError("refuse to overwrite adapter delivery")
    with tarfile.open(archive, "w:gz") as bundle:
        for path, name in files: bundle.add(path, arcname=name, recursive=False)
    with tarfile.open(archive, "r:gz") as bundle:
        if bundle.getnames() != [item["path"] for item in index]: raise ValueError("adapter archive membership changed")
        for item in index:
            with bundle.extractfile(item["path"]) as stream:
                if hashlib.sha256(stream.read()).hexdigest() != item["sha256"]: raise ValueError("adapter archive member changed")
    if any(sha256_file(path) != item["sha256"] for (path, _), item in zip(files, index, strict=True)): raise ValueError("adapter evidence changed during packaging")
    shutil.copyfile(run / "report.json", results)
    record = {"schema_version": 1, "status": STATUS, "files": index, "indexed_large_inputs_states_and_packets": indexed,
        "archive_sha256": sha256_file(archive), "archive_bytes": archive.stat().st_size, "results_sha256": sha256_file(results),
        "historical_attempts_not_accepted": [{"path": str(path), "accepted": False} for path in attempts],
        "all_raw_packets_layouts_and_A4_observations_rechecked": True, "finite_adapter_timing_validated": False, "matched_A4_B_overhead_validated": False}
    atomic_write_json(verification, record); return record
