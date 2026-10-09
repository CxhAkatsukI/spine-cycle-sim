"""Orchestrate the fixed upstream functional matrix without changing simulator code."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .execution import dependency_identities, run_bounded
from .sources import prepare_regraph, read_pins, verify_snapshot
from .validation import validate_contract, validate_probe


def compiler_command(root: Path, source_root: Path, prepared: dict, probe: dict,
                     topology: dict | None, hls_include: Path, compiler: str,
                     case_dir: Path) -> list[str]:
    source = root / "cpp/tests/publication_sources" / probe["source"]
    command = [compiler, "-std=c++17", "-O1", "-g0", "-Wno-unknown-pragmas",
               "-Wno-deprecated-declarations", "-DDISABLE_MAX_HLS_STREAM_DEPTH_PRINT",
               "-MD", "-MF", str(case_dir / "dependencies.d"), "-MT", "probe",
               f"-I{hls_include}"]
    if probe["source"] == "grasu_cache_probe.cpp":
        command.append(f"-I{source_root / 'grasu/GraSU/GraSU_kernels/src'}")
    else:
        original = Path(prepared[probe["topology"]]["directory"])
        command.extend([
            "-DSW_EMU", f"-DLITTLE_KERNEL_NUM={topology['little']}",
            f"-DBIG_KERNEL_NUM={topology['big']}", "-DLITTLE_KERNEL_DST_BUFFER_SIZE=65536",
            "-DBIG_KERNEL_DST_BUFFER_SIZE=524288", "-DSRC_BUFFER_SIZE=4096",
            "-DLOG2_SRC_BUFFER_SIZE=12", "-DHAVE_APPLY_OUTDEG=1",
            "-DHAVE_VERTEX_PROP=0", "-DHAVE_UNSIGNED_PROP=0",
        ])
        family = "big" if probe["source"] == "regraph_big_probe.cpp" else "little"
        for directory in (
            ".", "acc_template/common", "acc_udfs/pr", f"acc_template/kernel_{family}_gs",
            f"acc_template/kernel_{family}_gs_merger", "acc_template/kernel_apply",
        ):
            command.append(f"-I{original / directory}")
    command.extend([str(source), "-pthread", "-lgmp", "-o", str(case_dir / "probe")])
    return command


def run_study(root: Path, contract_path: Path, pins_path: Path, source_root: Path,
              output: Path, hls_include: Path, compiler: str) -> dict:
    contract = json.loads(contract_path.read_text(encoding="ascii"))
    validate_contract(contract)
    if not (hls_include / "ap_int.h").is_file():
        raise ValueError("Vitis HLS headers are required for author-source controls")
    output.mkdir(parents=True, exist_ok=False)
    atomic_write_json(output / "contract.json", contract)
    atomic_write_json(output / "source_pins.json", json.loads(pins_path.read_text(encoding="ascii")))
    pins = read_pins(pins_path)
    source_identities = [verify_snapshot(source_root / name, pin) for name, pin in pins.items()]
    topologies = {row["id"]: row for row in contract["topologies"]}
    prepared = {}
    report = {
        "schema_version": 1, "evidence_class": contract["evidence_class"],
        "contract_sha256": sha256_file(contract_path), "pins_sha256": sha256_file(pins_path),
        "source_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "worktree_status": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=root, text=True).splitlines(),
        "compiler_version": subprocess.check_output([compiler, "--version"], text=True),
        "generator_python_version": subprocess.check_output(
            [contract["generator_python"], "--version"], text=True),
        "source_pins": source_identities, "prepared": prepared,
        "not_claimed": contract["not_claimed"], "device_cycles": None,
        "analysis_code": [
            {"path": str(path.relative_to(root)), "sha256": sha256_file(path)}
            for path in sorted((root / "spine_cycle_sim/experiments/upstream_controls").glob("*.py"))
        ] + [{"path": "scripts/run_upstream_stage_controls.py", "sha256": sha256_file(
            root / "scripts/run_upstream_stage_controls.py")}],
        "publication_rate_error_pct": None, "probes": [], "all_functional_probes_passed": False,
    }
    for name, topology in topologies.items():
        destination = output / "prepared" / name
        try:
            prepared[name] = prepare_regraph(source_root / "regraph", destination,
                                             topology["little"], topology["big"],
                                             contract["generator_python"])
            prepared[name]["directory"] = str(destination)
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            report["preparation_error"] = str(error)
            report["probes"] = [{"id": row["id"], "status": "NOT_RUN"}
                                for row in contract["probes"]]
            atomic_write_json(output / "report.json", report)
            return report
    limits = {"memory_gib": contract["memory_limit_gib"], "reserve_gib": contract["reserve_gib"]}
    for probe in contract["probes"]:
        print(f"Starting {probe['id']} (source-functional only)", flush=True)
        case_dir = output / probe["id"]
        case_dir.mkdir()
        row = {"id": probe["id"], "status": "FAILED", "expected": probe["expected"]}
        try:
            topology = topologies.get(probe.get("topology"))
            command = compiler_command(root, source_root, prepared, probe, topology,
                                       hls_include, compiler, case_dir)
            row["compile"] = run_bounded(command, root, case_dir / "compile",
                                           timeout=contract["compile_timeout_seconds"], **limits)
            if row["compile"]["exit_code"] != 0:
                raise ValueError("author-source compilation failed or timed out")
            row["dependencies"] = dependency_identities(case_dir / "dependencies.d", root)
            row["binary_sha256"] = sha256_file(case_dir / "probe")
            row["run"] = run_bounded([str(case_dir / "probe")], root, case_dir / "run",
                                       timeout=contract["run_timeout_seconds"], **limits)
            if row["run"]["exit_code"] != 0:
                raise ValueError("source-functional probe failed or timed out")
            row["observed"] = validate_probe(Path(row["run"]["stdout"]).read_text(),
                                              probe["expected"])
            for dependency in row["dependencies"]:
                if sha256_file(Path(dependency["path"])) != dependency["sha256"]:
                    raise ValueError("compiled dependency changed during probe")
            row["status"] = "FUNCTIONAL_PASS_NOT_TIMING"
        except (ValueError, RuntimeError, OSError) as error:
            row["error"] = str(error)
        report["probes"].append(row)
        atomic_write_json(output / "report.json", report)
        print(f"  {row['status']}: {row.get('error', 'oracle and stream checks passed')}", flush=True)
    for name, pin in pins.items():
        verify_snapshot(source_root / name, pin)
    for item in report["analysis_code"]:
        if sha256_file(root / item["path"]) != item["sha256"]:
            raise ValueError("control orchestration code changed during the study")
    report["all_functional_probes_passed"] = all(
        row["status"] == "FUNCTIONAL_PASS_NOT_TIMING" for row in report["probes"])
    atomic_write_json(output / "report.json", report)
    return report
