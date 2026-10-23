"""Audit and seal current ResPR execution on three declared historical u8 inputs."""

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import struct
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .. import analysis
from . import delivery, matrix, tables, validation
from .residual_followup import record
from .study import residual_threshold


STATUS = "COMPLETE_HISTORICAL_INPUT_RES_PR_DIAGNOSTIC"


def check_arm(report, case, arm, result, read):
    prefix = "matrix/"
    name = Path(result["evidence"]).name
    text = read(prefix + "raw/" + name + ".stdout.txt").decode()
    raw = record(text, "WARM_RESULT ")
    if ("REFRESH_COMPLETE" not in text or raw.get("correctness") is not True or
            raw.get("ledger_closed") is not True or any(result.get(k) != v for k, v in raw.items())):
        raise ValueError("correctness-admitted raw arm required")
    steps = [s for s in report["steps"] if Path(s["stdout"]).name == name + ".stdout.txt"]
    if (len(steps) != 1 or steps[0]["exit_code"] or steps[0]["timed_out"] or
            steps[0] != json.loads(read(prefix + "raw/" + name + ".resources.json"))):
        raise ValueError("successful bounded command required")
    config = json.loads(read(prefix + name + "/config.json"))
    if config["arm"] != arm or any(config[k] != case[v] for k, v in
            (("algorithm", "algorithm"), ("graph", "graph"), ("updates", "update_file"))):
        raise ValueError("historical arm input changed")
    epsilon, bound = validation.pagerank_threshold(config, report["model"], case["vertices"])
    for state in ("old_state", "expected", "final"):
        blob = read(prefix + name + "/" + state + ".u32le")
        values = [v for (v,) in struct.iter_unpack("<f", blob)]
        if (len(values) != case["vertices"] or any(not math.isfinite(v) or v < 0 for v in values) or
                hashlib.sha256(blob).hexdigest() != result["state_hashes"][state]):
            raise ValueError("complete finite rank state identity required")
    residual = [v for (v,) in struct.iter_unpack("<f", read(prefix + name + "/residual.u32le"))]
    if len(residual) != case["vertices"] or any(not math.isfinite(v) or abs(v) > epsilon for v in residual):
        raise ValueError("complete converged residual required")
    oracle = record(text, "PR_ORACLE ")
    if (any(not math.isfinite(v) or v < 0 for v in oracle.values()) or
            not math.isclose(oracle["l1_error_bound"], bound, rel_tol=2e-5) or
            oracle["l1_error"] > bound):
        raise ValueError("independent PageRank oracle gate failed")
    ledger = json.loads(read(prefix + name + "/backend.json"))
    if (ledger["ledger_closed"] is not True or ledger["pending_intents"] or ledger["pending_grants"] or
            len({ledger[k] for k in ("unique_intents", "grants", "consumed_grants")}) != 1):
        raise ValueError("physical request ledger did not drain")
    energy = validation.energy_details(read, prefix + name)
    if energy != result["energy_details"] or energy["total_energy_pj"] != result["energy_pj"]:
        raise ValueError("all-channel energy changed")
    return text, oracle, max(abs(v) for v in residual)


def summarize(report, core, read, *, expected_core_tests=39):
    if (report.get("status") != "COMPLETE_SUPPORTED_SCOPE" or report.get("failures") != [] or
            report.get("pins_unchanged") is not True or report.get("baseline_admitted") is not False or
            report.get("case_set") != "historical-residual-u8" or
            report["model"].get("residual_epsilon") != residual_threshold(1e-6)):
        raise ValueError("complete fixed-threshold historical-input matrix required")
    declared = {dataset: run_id for dataset, _, run_id in matrix.HISTORICAL_RESIDUAL}
    cases = report["matrix"]
    if (len(cases) != 3 or len(report["rows"]) != 3 or {c["dataset"] for c in cases} != set(declared)):
        raise ValueError("all three predeclared cases required")
    validation.source_snapshot(report, read, "matrix/")
    validation.core_gates(core, report, read, "core-gates/", expected_tests=expected_core_tests)
    pins = {p["path"]: p for p in report["pins"]}
    rows = []
    for case in cases:
        if (case["algorithm"] != "ResPR" or case["updates"] != 8 or case["physical_update_records"] != 16 or
                case["historical_run_id"] != declared[case["dataset"]]):
            raise ValueError("registered reciprocal historical u8 case required")
        for key in ("graph", "update_file", "manifest"):
            identity = pins[case[key]]["sha256"]
            if hashlib.sha256(read("inputs/" + identity)).hexdigest() != identity:
                raise ValueError("historical input pin changed")
        matches = [r for r in report["rows"] if r["dataset"] == case["dataset"]]
        if len(matches) != 1:
            raise ValueError("one comparison per declared case required")
        row = matches[0]
        if analysis.comparison(case, {a: row[a] for a in ("spine", "gr")}) != row or any(
                row["spine"]["state_hashes"][k] != row["gr"]["state_hashes"][k] for k in ("old_state", "expected")):
            raise ValueError("comparison arithmetic or shared initial/oracle state changed")
        evidence = {a: check_arm(report, case, a, row[a], read) for a in ("spine", "gr")}
        correction = record(evidence["spine"][0], "CORRECTION_TRACE ")
        propagation = record(evidence["spine"][0], "PROPAGATION_TRACE ")
        scan = record(evidence["gr"][0], "R_SCAN_TRACE ")
        round_rows = list(csv.DictReader(io.StringIO(read("matrix/" + Path(
            row["spine"]["evidence"]).name + "/rounds.csv").decode())))
        if (row["spine"].get("correction_oracle_directed") is not True or correction["oracle_directed"] is not True or
                len(round_rows) != row["spine"]["rounds"] or
                propagation["nonempty_rounds"] != sum(int(r["active_in"]) > 0 for r in round_rows) or
                propagation["active_vertex_visits"] != sum(int(r["active_in"]) for r in round_rows) or
                propagation["reader_edges"] != propagation["computed_edges"] or
                scan["rounds"] != row["gr"]["rounds"] or
                scan["live_edges_scanned"] != (case["initial_edges"] + 16) * scan["rounds"]):
            raise ValueError("propagation work or complete-graph scan ledger changed")
        result = dict(dataset=case["dataset"], vertices=case["vertices"], initial_edges=case["initial_edges"],
            logical_updates=8, physical_records=16, initial_active=correction["active_vertices"], **propagation,
            spine_cycles=row["spine"]["cycles"], gr_cycles=row["gr"]["cycles"],
            speedup_gr_over_spine=row["gr"]["cycles"] / row["spine"]["cycles"],
            spine_rounds=row["spine"]["rounds"], gr_rounds=row["gr"]["rounds"],
            gr_live_edges_scanned=scan["live_edges_scanned"],
            accepted_bytes_ratio=row["accepted_bytes_ratio"], hbm_energy_ratio=row["hbm_energy_ratio"])
        for arm in ("spine", "gr"):
            result.update({arm + "_" + k: v for k, v in evidence[arm][1].items()})
            result[arm + "_maximum_stored_residual"] = evidence[arm][2]
        result["has_nonempty_propagation"] = propagation["reader_edges"] > 0 and propagation["nonempty_rounds"] > 0
        rows.append(result)
    return dict(status=STATUS, baseline_admitted=False, model=report["model"], rows=rows)


def package(output, report_path, core_path):
    if output.exists() or report_path.parent.name != "matrix" or core_path.parent.name != "core-gates":
        raise ValueError("fresh output and named matrix/core-gates evidence required")
    report = json.loads(report_path.read_text())
    files = {}
    for directory in (report_path.parent, core_path.parent):
        for path in directory.rglob("*"):
            if path.is_file() and "build" not in path.relative_to(directory).parts and path.suffix in (
                    ".json", ".csv", ".txt", ".gz", ".u32le"):
                if path.is_symlink():
                    raise ValueError("symlink evidence rejected")
                files[directory.name + "/" + str(path.relative_to(directory))] = path
    for case in report["matrix"]:
        for key in ("graph", "update_file", "manifest"):
            path = Path(case[key])
            files["inputs/" + sha256_file(path)] = path
    files["analysis/propagation_followup.py"] = Path(__file__)
    read = lambda name: files[name].read_bytes()
    summary = summarize(report, json.loads(core_path.read_text()), read)
    (output / "data").mkdir(parents=True)
    (output / "evidence").mkdir()
    atomic_write_json(output / "data/summary.json", summary)
    (output / "data/propagation_comparison.csv").write_bytes(tables.csv_bytes(summary["rows"]))
    files.update({"data/" + p.name: p for p in (output / "data").iterdir()})
    archive = output / "evidence/evidence.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in sorted(files.items()):
            handle.add(path, arcname=name, recursive=False)
    atomic_write_json(output / "evidence/index.json", dict(status=STATUS, archive=archive.name,
        sha256=sha256_file(archive), external="Compiler, SST, DRAMSim3 and linked binaries are pinned external dependencies.",
        members=[dict(path=n, bytes=p.stat().st_size, sha256=sha256_file(p)) for n, p in sorted(files.items())]))
    return verify(output)


def verify(output):
    index = json.loads((output / "evidence/index.json").read_text())
    archive = output / "evidence/evidence.tar.gz"
    if index["archive"] != archive.name or sha256_file(archive) != index["sha256"]:
        raise ValueError("historical-input archive identity changed")
    with tarfile.open(archive) as handle:
        read = delivery.checked_archive(handle, index)
        summary = summarize(json.loads(read("matrix/results.json")), json.loads(read("core-gates/results.json")), read)
        for name in ("summary.json", "propagation_comparison.csv"):
            archived = read("data/" + name)
            matches = (json.loads(archived) == summary if name.endswith(".json") else
                       archived == tables.csv_bytes(summary["rows"]))
            if (output / "data" / name).read_bytes() != archived or not matches:
                raise ValueError("export differs from raw propagation evidence")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--core-tests", type=Path)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if not args.verify and (args.report is None or args.core_tests is None):
        parser.error("packaging requires --report and --core-tests")
    result = verify(args.output) if args.verify else package(args.output, args.report, args.core_tests)
    print(json.dumps(dict(status=result["status"], sha256=result["sha256"])))
