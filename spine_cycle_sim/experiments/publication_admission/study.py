"""Bounded full-input controls with fixed inputs, code and preserved failures."""

import json
from pathlib import Path
import platform
import sqlite3
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..upstream_controls.execution import run_bounded
from .analysis import analyze_order, compare_denominator
from .denominators import residual_event_hypothesis
from .temporal import connect, ingest


def identities(root: Path):
    paths = sorted((root / "spine_cycle_sim/experiments/publication_admission").glob("*.py"))
    paths += [root / name for name in ("scripts/audit_publication_workloads.py",
        "tests/test_publication_workload_admission.py", "configs/experiments/grasu_publication_workload_admission_v1.json",
        "spine_cycle_sim/experiments/campaign_runtime.py", "spine_cycle_sim/experiments/upstream_controls/execution.py")]
    return [{"path": str(path.relative_to(root)), "sha256": sha256_file(path)} for path in paths]


def collect(contract: dict, dataset_id: str, source_root: Path, out: Path):
    out.mkdir(parents=True, exist_ok=False)
    dataset = next(row for row in contract["datasets"] if row["id"] == dataset_id)
    source = source_root / dataset["source"]
    database = out / "events.sqlite3"
    limits = contract["limits"]
    stats = ingest(source, dataset["sha256"], database, limits["max_events"], limits["sqlite_cache_kib"])
    report = {"dataset": dataset, "input": stats, "orders": [], "timing_match": None}
    with connect(database, limits["sqlite_cache_kib"]) as connection:
        for ordering in contract["ordering_controls"]:
            row = analyze_order(connection, ordering, stats["events"], dataset["base_events"],
                contract["paper"]["batch_count"], dataset["base_rounding_half_width"])
            row["denominator_comparison"] = compare_denominator(row, dataset["paper_seconds"], dataset["paper_rate_million"])
            report["orders"].append(row)
            atomic_write_json(out / "counts.json", report)
    report["exploratory_denominator"] = residual_event_hypothesis(stats, report["orders"], dataset)
    atomic_write_json(out / "counts.json", report)
    database.unlink()
    return report


def run(root: Path, source_root: Path, out: Path):
    out.mkdir(parents=True, exist_ok=False)
    contract_path = root / "configs/experiments/grasu_publication_workload_admission_v1.json"
    contract = json.loads(contract_path.read_text())
    frozen = identities(root)
    report = {"status": "RUNNING", "contract": contract, "code": frozen,
        "environment": {"python": sys.version, "executable": sys.executable,
            "executable_sha256": sha256_file(Path(sys.executable).resolve()),
            "sqlite": sqlite3.sqlite_version, "platform": platform.platform()},
        "rows": [], "steps": [], "publication_timing_match": None}
    path = out / "report.json"
    atomic_write_json(path, report)
    try:
        for dataset in contract["datasets"]:
            reference = None
            for repeat in range(contract["repetitions"]):
                capture = out / "captures" / dataset["id"] / str(repeat)
                step = run_bounded([sys.executable, str(root / "scripts/audit_publication_workloads.py"),
                    "--worker", dataset["id"], "--source-root", str(source_root), "--out", str(capture)],
                    root, out / "logs" / f'{dataset["id"]}_{repeat}',
                    timeout=contract["limits"]["timeout_seconds"],
                    memory_gib=contract["limits"]["memory_gib"], reserve_gib=contract["limits"]["reserve_gib"])
                report["steps"].append(step)
                atomic_write_json(path, report)
                if step["exit_code"] or step["timed_out"]:
                    raise ValueError(f'full temporal count failed: {dataset["id"]}/{repeat}')
                observed = json.loads((capture / "counts.json").read_text())
                if reference is not None and observed != reference:
                    raise ValueError("repeated complete temporal counts differ")
                reference = observed
                report["rows"].append({"id": dataset["id"], "repeat": repeat,
                    "capture": str(capture / "counts.json"), "sha256": sha256_file(capture / "counts.json"),
                    "result": observed})
                atomic_write_json(path, report)
        if identities(root) != frozen:
            raise ValueError("workload admission code changed during collection")
        report["status"] = "FULL_TEMPORAL_COUNTS_REPEAT_PASS_NOT_PUBLICATION_TIMING"
    except Exception as error:
        report["status"] = "FAILED"
        report["error"] = str(error)
    atomic_write_json(path, report)
    return report
