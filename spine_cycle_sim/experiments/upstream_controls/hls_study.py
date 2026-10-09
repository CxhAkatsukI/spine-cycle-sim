"""Bounded scheduling study, separate from functional probes and board timing."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .execution import run_bounded
from .hls_preparation import prepare_hls_job, validate_synthesis_contract
from .hls_reports import collect_interfaces, collect_reports, log_diagnostics
from .sources import read_pins, verify_snapshot


def run_synthesis_study(root: Path, contract_path: Path, pins_path: Path,
                        source_root: Path, output: Path, tool: Path) -> dict:
    contract = json.loads(contract_path.read_text(encoding="ascii"))
    validate_synthesis_contract(contract)
    pins = read_pins(pins_path)
    identities = [verify_snapshot(source_root / name, pin) for name, pin in pins.items()]
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(contract_path, output / "contract.json")
    shutil.copyfile(pins_path, output / "source_pins.json")
    code = [root / "scripts/run_upstream_stage_synthesis.py",
            root / "cpp/tests/publication_sources/hls_portability.hpp",
            *sorted((root / "spine_cycle_sim/experiments/upstream_controls").glob("*.py"))]
    report = {
        "schema_version": 1, "evidence_class": contract["evidence_class"],
        "contract_sha256": sha256_file(contract_path), "source_pins": identities,
        "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                     cwd=root, text=True).strip(),
        "worktree_status": subprocess.check_output(["git", "status", "--porcelain"],
                                                    cwd=root, text=True).splitlines(),
        "analysis_code": [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)}
                          for path in code],
        "tool": str(tool), "tool_launcher_sha256": sha256_file(tool),
        "tool_include": str(tool.parent.parent / "include"),
        "not_claimed": contract["not_claimed"], "jobs": [], "all_synthesized": False,
        "publication_rate_error_pct": None, "FPGA_measured_cycles": None,
    }
    atomic_write_json(output / "report.json", report)
    version = run_bounded([str(tool), "-version"], output, output / "tool_version",
                          timeout=60, memory_gib=contract["memory_limit_gib"],
                          reserve_gib=contract["reserve_gib"])
    report["tool_version_run"] = version
    if version["exit_code"] != 0:
        report["error"] = "HLS tool version query failed"
        report["jobs"] = [{"id": job["id"], "status": "NOT_RUN", "configuration": job}
                          for job in contract["jobs"]]
        atomic_write_json(output / "report.json", report)
        return report
    report["tool_version"] = Path(version["stdout"]).read_text()
    for job in contract["jobs"]:
        print(f"Synthesis {job['id']} (schedule estimate, not board timing)", flush=True)
        case = output / job["id"]
        case.mkdir()
        row = {"id": job["id"], "status": "FAILED", "configuration": job}
        try:
            row["preparation"] = prepare_hls_job(job, contract, source_root, case,
                                                  tool.parent.parent / "include",
                                                  root / "cpp/tests/publication_sources/hls_portability.hpp")
            prepared = row["preparation"]
            row["run"] = run_bounded([str(tool), "-f", prepared["script"]], case,
                                       case / "synthesis", timeout=contract["timeout_seconds"],
                                       memory_gib=contract["memory_limit_gib"],
                                       reserve_gib=contract["reserve_gib"])
            stdout = Path(row["run"]["stdout"]).read_text(errors="replace")
            stderr = Path(row["run"]["stderr"]).read_text(errors="replace")
            row["diagnostics"] = log_diagnostics(stdout + "\n" + stderr)
            if row["run"]["exit_code"] != 0:
                raise ValueError("synthesis failed or exceeded the declared limit")
            row["reports"] = collect_reports(Path(prepared["solution"]), prepared["top"])
            row["interfaces"] = collect_interfaces(Path(prepared["solution"]))
            for item in prepared["source_files"]:
                if sha256_file(case / item["path"]) != item["sha256"]:
                    raise ValueError("prepared source changed during synthesis")
            row["status"] = "SYNTHESIZED_NOT_BOARD_VALIDATED"
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError, ET.ParseError) as error:
            row["error"] = str(error)
        report["jobs"].append(row)
        atomic_write_json(output / "report.json", report)
        print(f"  {row['status']}: {row.get('error', 'structured reports saved')}", flush=True)
    for name, pin in pins.items():
        verify_snapshot(source_root / name, pin)
    for item in report["analysis_code"]:
        if sha256_file(root / item["path"]) != item["sha256"]:
            raise ValueError("synthesis orchestration changed during the study")
    report["all_synthesized"] = all(row["status"] == "SYNTHESIZED_NOT_BOARD_VALIDATED"
                                    for row in report["jobs"])
    atomic_write_json(output / "report.json", report)
    return report
