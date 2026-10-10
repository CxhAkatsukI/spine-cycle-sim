"""Recheck raw evidence and deliver an isolated DDR finding, never a G match."""

import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from . import analysis, fixtures, preparation
from .study import step_order


def check_manifest(report, contract, identities):
    if (report["status"] not in (analysis.STATUS, analysis.MISMATCH) or
            report["FPGA_measured_cycles"] is not None or report["publication_rate_error_pct"] is not None or
            report["source_identities"] != identities or report["evidence_class"] != contract["evidence_class"] or
            [row["id"] for row in report["cases"]] != [case["id"] for case in contract["cases"]] or
            [row["id"] for row in report["bus_controls"]] != [case["id"] for case in contract["bus_controls"]] or
            [step["id"] for step in report["steps"]] != step_order(contract)):
        raise ValueError("DDR report claim, source, or complete declared matrix differs")
    for row in report["cases"]:
        if (len(row["source"]) != 3 or row["source"] != [row["source"][0]] * 3 or
                len(row["rtl"]) != contract["repetitions"] or row["rtl"] != [row["rtl"][0]] * contract["repetitions"] or
                row["status"] != row["rtl"][0]["status"] or row["status"] not in (analysis.STATUS, analysis.MISMATCH)):
            raise ValueError("DDR source/RTL repetitions or admission differs")
    accepted = all(row["status"] == analysis.STATUS for row in report["cases"])
    if (report["status"] == analysis.STATUS) != accepted:
        raise ValueError("DDR overall status hides a state mismatch")


def recheck(root: Path, run: Path):
    report = json.loads((run / "report.json").read_text())
    canonical = root / "configs/experiments/original_grasu_ddr_rtl_v1.json"
    contract = json.loads((run / "contract.json").read_text())
    check_manifest(report, contract, preparation.identities(root))
    if contract != json.loads(canonical.read_text()) or report["contract_sha256"] != sha256_file(canonical):
        raise ValueError("DDR frozen contract changed")
    if preparation.preserve(root, Path(report["baseline"])) != report["preservation"]:
        raise ValueError("DDR old code, evidence or user preservation changed")
    if ([row["name"] for row in report["tools"]] != ["hls", "xvlog", "xelab", "xsim"] or
            [Path(row["path"]).parent.name for row in report["source_binaries"]] != ["normal", "ubsan"] or
            [Path(row["path"]).parent.name for row in report["simulation_binaries"]] != ["grasu_ddr_sim", "grasu_memory_sim"]):
        raise ValueError("DDR complete tool or executable identity matrix missing")
    for row in report["tools"]:
        if len(row["files"]) != 2 or row["version_stdout"] != (run / ("version_" + row["name"] + ".stdout.txt")).read_text():
            raise ValueError("DDR tool version record changed")
        for field in row["files"]:
            if sha256_file(Path(field["path"])) != field["sha256"]:
                raise ValueError("DDR tool launcher/executable changed")
    for binary in report["source_binaries"] + report["simulation_binaries"]:
        for field in [binary, *binary.get("dependencies", [])]:
            if sha256_file(Path(field["path"])) != field["sha256"]:
                raise ValueError("DDR executable or header dependency changed")
    if not report["simulation_binaries"]:
        raise ValueError("DDR simulation binary identity missing")
    for field in report["rtl_files"] + report["schedules"]:
        if sha256_file(run / field["path"]) != field["sha256"]:
            raise ValueError("DDR frozen RTL or HLS schedule changed")
    complete_rtl = [{"path": str(path.relative_to(run)), "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path in sorted((run / "rtl").glob("*.v"))]
    if complete_rtl != report["rtl_files"] or not complete_rtl:
        raise ValueError("DDR complete generated RTL identity missing")
    if preparation.schedules(run) != report["schedules"]:
        raise ValueError("DDR inner-loop schedule changed")
    hls = report["hls_preparation"]
    if hls["compatibility"] or hls["top"] != "process_ddr" or sha256_file(Path(hls["script"])) != hls["script_sha256"]:
        raise ValueError("DDR original HLS preparation differs")
    for field in hls["source_files"]:
        if sha256_file(run / "hls" / field["path"]) != field["sha256"]:
            raise ValueError("DDR copied author source changed")
    for field in report["source_identities"]:
        path = Path(field["path"])
        if path.parts[:3] == ("cpp", "tests", "grasu_ddr_rtl") and sha256_file(run / "bench" / path.name) != field["sha256"]:
            raise ValueError("DDR copied test bench changed")
    steps = {step["id"]: step for step in report["steps"]}
    negative = {"bus_" + case["id"] for case in contract["bus_controls"] if case["rejection"] is not None}
    for name, step in steps.items():
        if json.loads((run / (name + ".resources.json")).read_text()) != {key: value for key, value in step.items() if key != "id"}:
            raise ValueError("DDR raw resource record changed")
        if step["timed_out"] or step["exit_code"] not in ((0, 1) if name in negative else (0,)):
            raise ValueError("DDR required step did not finish successfully")
    for control, row in zip(contract["bus_controls"], report["bus_controls"], strict=True):
        step = steps["bus_" + control["id"]]
        if {"id": control["id"], **analysis.bus(Path(step["stdout"]).read_text(), Path(step["stderr"]).read_text(), control)} != row:
            raise ValueError("DDR shared-memory selftest changed")
    with tempfile.TemporaryDirectory() as scratch:
        reference = Path(scratch) / "fixture"
        fixtures.prepare(reference, {"sequence": "empty"})
        for path in reference.iterdir():
            if path.read_bytes() != (run / "bus_fixture" / path.name).read_bytes():
                raise ValueError("DDR independent bus input changed")
    for case, row in zip(contract["cases"], report["cases"], strict=True):
        directory = Path(row["directory"])
        with tempfile.TemporaryDirectory() as scratch:
            reference = Path(scratch) / "fixture"
            if fixtures.prepare(reference, case) != row["fixture"]:
                raise ValueError("DDR input descriptor changed")
            for path in reference.iterdir():
                if path.read_bytes() != (directory / path.name).read_bytes():
                    raise ValueError("DDR complete input or independent oracle changed")
        for index, label in enumerate(("first", "repeat", "ubsan")):
            step = steps[case["id"] + "_source_" + label]
            capture = directory / (label + "_source")
            if ((capture / "expected.u32le").read_bytes() != (directory / "expected.u32le").read_bytes() or
                    analysis.source(Path(step["stdout"]).read_text(), Path(step["stderr"]).read_text(), capture, case) != row["source"][index]):
                raise ValueError("DDR original source complete-state evidence changed")
        for index in range(contract["repetitions"]):
            step = steps[case["id"] + f"_rtl_{index}"]
            if analysis.rtl(Path(step["stdout"]).read_text(), Path(step["stderr"]).read_text(), directory / f"rtl_{index}.hex", directory, case, contract) != row["rtl"][index]:
                raise ValueError("DDR RTL complete state or protocol evidence changed")
    return report


def deliver(root: Path, run: Path, destination: Path, attempts=()):
    report = recheck(root, run)
    targets = [destination / name for name in ("grasu_ddr_rtl_results.json", "grasu_ddr_rtl_verification.json", "raw_grasu_ddr_rtl.tar.gz")]
    if any(path.exists() for path in targets) or len(set(attempts)) != len(attempts) or run in attempts:
        raise ValueError("refuse to overwrite or duplicate DDR delivery")
    selected = [(Path(report["baseline"]) / "baseline.json", "baseline/baseline.json")]
    extensions = {".json", ".txt", ".log", ".xml", ".rpt", ".cpp", ".h", ".sv", ".v", ".tcl", ".d", ".hex", ".u32le"}
    for directory, prefix in [(run, "formal"), *((path, "attempts/" + path.name) for path in attempts)]:
        selected.extend((path, prefix + "/" + path.relative_to(directory).as_posix())
            for path in sorted(directory.rglob("*")) if path.is_file() and not path.is_symlink() and path.suffix in extensions)
    manifest = [{"path": name, "bytes": path.stat().st_size, "sha256": sha256_file(path)} for path, name in selected]
    if len({row["path"] for row in manifest}) != len(manifest):
        raise ValueError("duplicate DDR archive member")
    results, verification, archive = targets
    with tarfile.open(archive, "w:gz") as bundle:
        for path, name in selected:
            bundle.add(path, arcname=name, recursive=False)
    with tarfile.open(archive, "r:gz") as bundle:
        if bundle.getnames() != [row["path"] for row in manifest]:
            raise ValueError("DDR archive membership differs")
        for row in manifest:
            with bundle.extractfile(row["path"]) as stream:
                if hashlib.sha256(stream.read()).hexdigest() != row["sha256"]:
                    raise ValueError("DDR archive contents differ")
    if recheck(root, run) != report or any(sha256_file(path) != row["sha256"] for (path, _), row in zip(selected, manifest, strict=True)):
        raise ValueError("DDR evidence changed during delivery")
    shutil.copyfile(run / "report.json", results)
    record = {"schema_version": 1, "status": report["status"], "results_sha256": sha256_file(results),
        "archive_sha256": sha256_file(archive), "archive_bytes": archive.stat().st_size, "files": manifest,
        "historical_attempts_not_accepted": [str(path) for path in attempts], "all_raw_rows_rechecked": True,
        "complete_G_or_publication_or_board_timing_match": False}
    atomic_write_json(verification, record)
    return record
