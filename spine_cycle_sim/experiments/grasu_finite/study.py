"""Bounded preparation/execution/validation with immutable model identities."""

import json
from pathlib import Path
import subprocess

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..upstream_controls.execution import run_bounded
from ..upstream_controls.grasu.analysis import analyze as analyze_source
from .analysis import analyze, equivalent
from .preparation import build_identity, identities, prepare, preserve


def run(root: Path, binary: Path, baseline: Path, out: Path, smoke=False, ubsan_binary=None):
    out.mkdir(parents=True, exist_ok=False)
    contract_path = root / "configs/experiments/original_grasu_finite_v1.json"
    contract = json.loads(contract_path.read_text())
    report = {"status": "RUNNING", "contract": contract, "baseline": str(baseline),
              "steps": [], "rows": [], "source_rows": [], "source_ubsan_rows": [], "ubsan_rows": []}
    report_path = out / "report.json"
    atomic_write_json(report_path, report)
    try:
        checkout = root / "build/publication_sources/grasu"
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=checkout, text=True)
        if revision != contract["source_revision"] or dirty:
            raise ValueError("original G source must be pinned and clean")
        source_binary = root / contract["source_probe"]
        if sha256_file(source_binary) != contract["source_probe_sha256"]:
            raise ValueError("original G source probe binary identity differs")
        frozen = identities(root)
        frozen_binary = sha256_file(binary)
        report["model"] = {"files": frozen, "binary": str(binary), "binary_sha256": frozen_binary,
            "source_binary": str(source_binary), "source_binary_sha256": sha256_file(source_binary)}
        if not smoke:
            if ubsan_binary is None:
                raise ValueError("finite G formal admission requires a fresh UBSan build")
            report["builds"] = [build_identity(binary), build_identity(ubsan_binary)]
            if not report["builds"][1]["compile_commands"] or not all("-fsanitize=undefined" in row["command"] and "-fno-sanitize-recover=undefined" in row["command"]
                       for row in report["builds"][1]["compile_commands"]):
                raise ValueError("finite G UBSan flags are missing")
            original = json.loads((root / "results/upstream_stage_controls/grasu_source_path_final_v1/report.json").read_text())
            report["source_binaries"] = original["binaries"][:2]
            for item in report["source_binaries"]:
                for field in [item, *item["dependencies"]]:
                    if sha256_file(Path(field["path"])) != field["sha256"]:
                        raise ValueError("frozen original-source executable or dependencies changed")
        report["preservation"] = preserve(root, baseline)
        limits = contract["limits"]

        def execute(command, name):
            record = run_bounded(command, root, out / "logs" / name,
                timeout=limits["timeout_seconds"], memory_gib=limits["memory_gib"], reserve_gib=limits["reserve_gib"])
            report["steps"].append(record)
            atomic_write_json(report_path, report)
            if record["exit_code"] or record["timed_out"]:
                raise ValueError(f"bounded G step failed: {name}")
            return record

        matrix = contract["matrix"][:1] if smoke else contract["matrix"]
        for case in sorted({row["case"] for row in matrix}):
            report.setdefault("inputs", {})[str(case)] = prepare(out / "inputs" / str(case), case)
        if not smoke:
            for case in range(8):
                capture = out / "source" / str(case)
                capture.mkdir(parents=True)
                step = execute([str(source_binary), str(case), str(capture / "protocol.u32le"), str(capture / "state.u32le")],
                    f"source_{case}")
                report["source_rows"].append(analyze_source(capture, case, Path(step["stdout"]), Path(step["stderr"])))
                sanitized = out / "source_ubsan" / str(case)
                sanitized.mkdir(parents=True)
                source_ubsan = root / contract["source_ubsan_probe"]
                if sha256_file(source_ubsan) != contract["source_ubsan_probe_sha256"]:
                    raise ValueError("original source UBSan binary identity differs")
                step = execute([str(source_ubsan), str(case), str(sanitized / "protocol.u32le"), str(sanitized / "state.u32le")],
                    f"source_ubsan_{case}")
                result = analyze_source(sanitized, case, Path(step["stdout"]), Path(step["stderr"]))
                equivalent(report["source_rows"][-1], result)
                report["source_ubsan_rows"].append(result)
                atomic_write_json(report_path, report)
        for row in matrix:
            reference = None
            for repetition in range(1 if smoke else contract["repetitions"]):
                capture = out / "finite" / row["id"] / str(repetition)
                capture.mkdir(parents=True)
                memory = {**contract["memory"], **row}
                step = execute([str(binary), str(out / "inputs" / str(row["case"])), str(capture),
                    str(memory["fifo_depth"]), str(memory["latency"]), str(memory["bank_credits"]),
                    str(row.get("reverse", 0)), str(limits["max_cycles_per_batch"]), "1"],
                    f'{row["id"]}_{repetition}')
                result = analyze(capture, row["case"], Path(step["stdout"]), Path(step["stderr"]))
                if any(result[key] != memory[field] for key, field in (("fifo_depth", "fifo_depth"),
                        ("memory_latency", "latency"), ("bank_credits", "bank_credits"))):
                    raise ValueError("finite G execution configuration differs from contract")
                if result["timing"] != contract["timing"]:
                    raise ValueError("finite G compiled component timing differs from contract")
                if reference is not None:
                    equivalent(reference, result)
                reference = result
                report["rows"].append({"id": row["id"], "repetition": repetition, "result": result})
                atomic_write_json(report_path, report)
            if not smoke:
                source = report["source_rows"][row["case"]]
                if reference["oracle_state_sha256"] != source["state_sha256"] or reference["search_reads"] != source["memory_requests"]:
                    raise ValueError("finite/source merged state or search trace extent differs")
            if not smoke and row["id"] in contract["ubsan_rows"]:
                capture = out / "ubsan" / row["id"]
                capture.mkdir(parents=True)
                step = execute([str(ubsan_binary), str(out / "inputs" / str(row["case"])), str(capture),
                    str(memory["fifo_depth"]), str(memory["latency"]), str(memory["bank_credits"]),
                    str(row.get("reverse", 0)), str(limits["max_cycles_per_batch"]), "1"], f'{row["id"]}_ubsan')
                result = analyze(capture, row["case"], Path(step["stdout"]), Path(step["stderr"]))
                equivalent(reference, result)
                report["ubsan_rows"].append({"id": row["id"], "result": result})
        by_id = {row["id"]: row["result"] for row in report["rows"]}
        if not smoke:
            for first, reverse in (("lane_257", "lane_257_reverse"), ("mixed_three_batches", "mixed_reverse")):
                equivalent(by_id[first], by_id[reverse])
        if identities(root) != frozen or sha256_file(binary) != frozen_binary:
            raise ValueError("G model identity changed during execution")
        if not smoke and report["builds"] != [build_identity(binary), build_identity(ubsan_binary)]:
            raise ValueError("G compiler/build identity changed during execution")
        for rows in report["inputs"].values():
            if any(sha256_file(Path(row["path"])) != row["sha256"] for row in rows):
                raise ValueError("G prepared input changed during execution")
        report["preservation"] = preserve(root, baseline)
        report["status"] = "SMOKE_PASS_NOT_ADMITTED" if smoke else "G_FINITE_SOURCE16_STATE_LEDGER_PASS_NOT_TIMING"
    except Exception as error:
        report["status"] = "FAILED"
        report["error"] = str(error)
    atomic_write_json(report_path, report)
    return report
