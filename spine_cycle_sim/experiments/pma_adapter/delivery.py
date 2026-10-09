"""Recheck every admitted pair and preserve incomplete rows without claiming a match."""

import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..original_regraph_execution.analysis import analyze as analyze_a4
from ..original_regraph_execution.preparation import verify_inputs
from ..original_regraph_execution.adapter.analysis import inspect
from .analysis import STATUS, analyze, check_matrix
from .preparation import preserve
from .study import identities
from .execution import step_order


def recheck(root: Path, run: Path):
    report = json.loads((run / "report.json").read_text())
    canonical = root / "configs/experiments/pma_regraph_finite_control_v1.json"
    contract = json.loads((run / "contract.json").read_text())
    if (report["status"] not in (STATUS, "FINITE_A4_B_PARTIAL_MATRIX_NOT_ADMITTED") or
            report["FPGA_measured_cycles"] is not None or report["publication_rate_error_pct"] is not None or
            report["source_identities"] != identities(root) or contract != json.loads(canonical.read_text()) or
            report["contract_sha256"] != sha256_file(canonical) or
            sha256_file(run / "source/pma_to_regraph_adapter.cpp") != contract["adapter_source_sha256"]):
        raise ValueError("finite PMA report/source/claim/contract is not admitted")
    baseline = Path(report["baseline"])
    previous = json.loads((baseline / "baseline.json").read_text())
    if preserve(root, baseline) != report["preservation"]:
        raise ValueError("finite PMA pre-edit source/user preservation changed")
    if [row["id"] for row in report["cases"]] != [row["id"] for row in contract["cases"]]:
        raise ValueError("finite PMA complete declared case matrix missing")
    required = step_order(contract, report["instrumented_cases"])
    if [step["id"] for step in report["steps"]] != required:
        raise ValueError("finite PMA raw step matrix missing or reordered")
    steps = {step["id"]: step for step in report["steps"]}
    if len(steps) != len(report["steps"]):
        raise ValueError("finite PMA duplicate step")
    for name, step in steps.items():
        resources = json.loads((run / (name + ".resources.json")).read_text())
        if resources != {key: value for key, value in step.items() if key != "id"}:
            raise ValueError("finite PMA resource record changed")
        if (step["timed_out"] or step["exit_code"]) and not name.startswith(("pma_", "ubsan_")):
            raise ValueError("finite PMA non-iteration prerequisite failed")
    verify_inputs(report["inputs"])
    indexed = []
    for item in report["inputs"]:
        facts, controls = inspect(Path(item["directory"]))
        if facts != item["source_counts"] or controls != item["compatibility_controls"]:
            raise ValueError("finite PMA source counts or compatibility conditions changed")
        for field in item["adapter_layout"]["files"]:
            path = Path(item["directory"]) / field["name"]
            if sha256_file(path) != field["sha256"] or path.stat().st_size != field["bytes"]:
                raise ValueError("finite PMA input changed")
            indexed.append({**field, "path": str(path)})
        for field in item["files"]:
            indexed.append({**field})
        descriptor = Path(item["directory"]) / "execution.u32le"
        indexed.append({"path": str(descriptor), "bytes": descriptor.stat().st_size, "sha256": sha256_file(descriptor)})
    for case, row, old in zip(contract["cases"], report["cases"], previous["cases"], strict=True):
        item = next(item for item in report["inputs"] if item["id"] == case["input"])
        for label in ("legacy", "matched"):
            step = steps[label + "_" + case["id"]]
            value = analyze_a4(Path(step["stdout"]).read_text(), Path(row[label]["directory"]), case, item, previous["contract"])
            if label == "matched" and value["result"].pop("input_parent_credits", None) != 16:
                raise ValueError("finite PMA matched compact control credits differ")
            if value != old["analysis"] or value != row[label]["analysis"] or Path(step["stderr"]).read_text():
                raise ValueError("finite PMA legacy/matched compact A4 changed")
            if label == "legacy" and Path(step["stdout"]).read_text() != old["stdout"]:
                raise ValueError("finite PMA legacy stdout changed")
            for field in value["files"]:
                indexed.append({**field, "path": str(Path(row[label]["directory"]) / field["path"])})
        step = steps["pma_" + case["id"]]
        if row["status"] == STATUS:
            if step["exit_code"] or step["timed_out"]:
                raise ValueError("finite PMA accepted iteration did not exit successfully")
            value = analyze(Path(step["stdout"]).read_text(), Path(step["stderr"]).read_text(), Path(row["directory"]), case, item, row["matched"]["analysis"], contract)
            if value != row["analysis"]:
                raise ValueError("finite PMA complete iteration changed")
            indexed.extend({**field, "path": str(Path(row["directory"]) / field["path"])} for field in value["files"])
        elif row["status"] == "TIMEOUT" and not step["timed_out"] or row["status"] == "FAILED" and not step["exit_code"]:
            raise ValueError("finite PMA rejected iteration has no terminal failure evidence")
        elif row["status"] not in ("TIMEOUT", "FAILED"):
            raise ValueError("finite PMA unexecuted case cannot be delivered")
    if [row["id"] for row in report["instrumented_cases"]] != contract["instrumented_inputs"]:
        raise ValueError("finite PMA instrumented input matrix differs")
    for row in report["instrumented_cases"]:
        case = next(case for case in contract["cases"] if case["input"] == row["id"])
        normal = next(item for item in report["cases"] if item["id"] == case["id"])
        if row["status"] == STATUS:
            step = steps["ubsan_" + row["id"]]
            item = next(item for item in report["inputs"] if item["id"] == row["id"])
            value = analyze(Path(step["stdout"]).read_text(), Path(step["stderr"]).read_text(), Path(row["directory"]), case, item, normal["matched"]["analysis"], contract)
            if value != row["analysis"] or value != normal["analysis"] or step["exit_code"] or step["timed_out"]:
                raise ValueError("finite PMA instrumented observations changed")
            indexed.extend({**field, "path": str(Path(row["directory"]) / field["path"])} for field in value["files"])
        elif row["status"] == "NOT_RUN_NORMAL_NOT_ADMITTED":
            if normal["status"] == STATUS:
                raise ValueError("finite PMA instrumented case improperly skipped")
        else:
            if row["status"] not in ("TIMEOUT", "FAILED"):
                raise ValueError("finite PMA instrumented case has an unknown status")
            step = steps["ubsan_" + row["id"]]
            if row["status"] == "TIMEOUT" and not step["timed_out"] or row["status"] == "FAILED" and not step["exit_code"]:
                raise ValueError("finite PMA UBSan failure has no evidence")
    if check_matrix(report["cases"]) != report["matrix_checks"]:
        raise ValueError("finite PMA matrix checks changed")
    for field in report["conformance"]["captures"]:
        if sha256_file(Path(field["path"])) != field["sha256"] or Path(field["path"]).stat().st_size != field["bytes"]:
            raise ValueError("finite PMA source/cold/stale packet capture changed")
        indexed.append(field)
    for field in report["schedules"]["files"]:
        if sha256_file(run / "schedules" / field["path"]) != field["sha256"]:
            raise ValueError("finite PMA HLS schedule source changed")
    for binary in report["binaries"] + [report["instrumented_binary"]] + report["conformance"]["binaries"]:
        for field in [binary, *binary.get("dependencies", [])]:
            if sha256_file(Path(field["path"])) != field["sha256"]:
                raise ValueError("finite PMA executable/dependency changed")
    admitted = all(row["status"] == STATUS for row in report["cases"] + report["instrumented_cases"])
    if (report["status"] == STATUS) != admitted:
        raise ValueError("finite PMA overall status hides an incomplete row")
    return report, indexed


def deliver(root: Path, run: Path, destination: Path, attempts=()):
    report, indexed = recheck(root, run)
    if len(set(attempts)) != len(attempts) or run in attempts:
        raise ValueError("finite PMA historical attempt duplicated")
    files = [(Path(report["baseline"]) / "baseline.json", "baseline/baseline.json")]
    for directory, prefix in [(run, "finite"), *((path, "attempts/" + path.name) for path in attempts)]:
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.is_symlink() and path.suffix in (".json", ".txt", ".rpt", ".xml", ".v", ".env", ".d", ".cpp"):
                files.append((path, prefix + "/" + path.relative_to(directory).as_posix()))
            elif path.is_file() and path.suffix == ".u32le" and path.stat().st_size <= 768:
                files.append((path, prefix + "/" + path.relative_to(directory).as_posix()))
    manifest = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path, name in files]
    if len({item["path"] for item in manifest}) != len(manifest):
        raise ValueError("finite PMA archive members duplicated")
    results, verification, archive = [destination / name for name in ("finite_pma_results.json", "finite_pma_verification.json", "raw_finite_pma.tar.gz")]
    if any(path.exists() for path in (results, verification, archive)):
        raise ValueError("refuse to overwrite finite PMA delivery")
    with tarfile.open(archive, "w:gz") as bundle:
        for path, name in files:
            bundle.add(path, arcname=name, recursive=False)
    with tarfile.open(archive, "r:gz") as bundle:
        if bundle.getnames() != [item["path"] for item in manifest]:
            raise ValueError("finite PMA archive membership changed")
        for item in manifest:
            with bundle.extractfile(item["path"]) as stream:
                if hashlib.sha256(stream.read()).hexdigest() != item["sha256"]:
                    raise ValueError("finite PMA archive contents changed")
    shutil.copyfile(run / "report.json", results)
    if any(sha256_file(path) != field["sha256"] for (path, _), field in zip(files, manifest, strict=True)) or identities(root) != report["source_identities"]:
        raise ValueError("finite PMA source/evidence changed during packaging")
    record = {"schema_version": 1, "status": report["status"], "archive_sha256": sha256_file(archive),
        "archive_bytes": archive.stat().st_size, "results_sha256": sha256_file(results), "files": manifest,
        "indexed_large_inputs_and_states": indexed, "historical_attempts_not_accepted": [str(path) for path in attempts],
        "all_legacy_matched_and_completed_PMA_rows_rechecked": True, "FPGA_or_publication_timing_match": False}
    atomic_write_json(verification, record)
    return record
