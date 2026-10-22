"""Check passive observations against the complete pre-observation R matrix."""

import argparse
import csv
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import identity
from .compact_analysis import MATRIX


TABLES = {
    "frontend_waits": ("worker", "packets", "emitted", "source_waits", "edge_waits",
        "output_stalls", "pipeline_stalls", "request_stalls", "source_lines", "gather_reset",
        "gather_merge", "gather_drain", "gather_output_stalls", "gather_conflicts", "gather_rows"),
    "source_waits": ("service", "blocks", "lines", "terminators", "parents", "completions",
        "output_stalls", "issue_stalls", "max_pending"),
    "backend_waits": ("merger_output_stalls", "apply_output_stalls", "apply_read_stalls",
        "apply_pipeline_stalls", "apply_write_stalls", "writeback_pipeline_stalls",
        "writeback_write_stalls", "apply_max_reads", "apply_max_pipeline", "apply_max_writes",
        "writeback_max_pipeline", "writeback_max_writes"),
}


def read_table(path, name):
    fields = TABLES[name]
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(fields):
            raise ValueError("unexpected observation schema: " + name)
        rows = []
        for row in reader:
            if set(row) != set(fields) or any(value is None or not value.isascii() or
                    not value.isdecimal() or str(int(value)) != value for value in row.values()):
                raise ValueError("noncanonical unsigned observation: " + name)
            rows.append({key: int(value) for key, value in row.items()})
    count = {"frontend_waits": 4, "source_waits": 2, "backend_waits": 1}[name]
    if len(rows) != count or (name != "backend_waits" and
            [row[fields[0]] for row in rows] != list(range(count))):
        raise ValueError("missing, extra or reordered observation rows: " + name)
    return rows


def summarize(rows, previous, observations):
    if any([identity(row) for row in matrix] != MATRIX for matrix in (rows, previous)):
        raise ValueError("complete ordered twelve-row matrices required")
    expected = {key for key in MATRIX if key[2] != "a4_io16"}
    if set(observations) != expected:
        raise ValueError("complete eight-row wait matrix required")
    for row, old in zip(rows, previous):
        if any(row[field] != old[field] for field in ("observations", "outputs")):
            raise ValueError("passive observation changed cycles, traffic, trajectory or state")
        key = identity(row)
        if key not in observations:
            continue
        tables = observations[key]
        if any(f["packets"] != f["emitted"] for f in tables["frontend_waits"]):
            raise ValueError("unclosed Scatter packets")
        if any(s["parents"] != s["completions"] for s in tables["source_waits"]):
            raise ValueError("unclosed source parents")
        if tables["backend_waits"][0]["apply_read_stalls"] > row["observations"]["result"]["cycles"]:
            raise ValueError("sampled Apply waits exceed execution cycles")
        if key[1] == 1 and tables != observations[(key[0], 0, key[2])]:
            raise ValueError("wait observations depend on registration order")
    return {"status": "PASS_PASSIVE_OBSERVATION_NOT_PERFORMANCE_ADMISSION",
        "all_numerical_rows_replayed_exactly": 12, "wait_registration_order_pairs": 4,
        "exclusive_stage_breakdown": False, "hardware_timing_admitted": False,
        "production_baseline_admitted": False,
        "observations": [{"latency": key[0], "arm": key[2], **observations[key]}
                         for key in MATRIX if key[1] == 0 and key in observations]}


def analyze(run, reference):
    reports = [json.loads(path.read_text()) for path in (run, reference)]
    for report in reports:
        if (report.get("status") != "COMPACT_CONVERGENCE_COMPLETE_NOT_HARDWARE_ADMISSION" or
                report.get("pins_unchanged") is not True or report.get("failures")):
            raise ValueError("completed unchanged-source convergence reports required")
    pins = {p["path"]: p for p in reports[0]["progress"]}
    observations = {}
    for latency, reverse, arm in MATRIX:
        if arm == "a4_io16":
            continue
        directory = run.parent / "progress" / f"lat{latency}_reverse{reverse}_{arm}"
        tables = {}
        for name in TABLES:
            path = directory / (name + ".csv")
            frozen = pins.get(str(path))
            if (frozen is None or path.stat().st_size != frozen["bytes"] or
                    sha256_file(path) != frozen["sha256"]):
                raise ValueError("missing or changed observation pin: " + str(path))
            tables[name] = read_table(path, name)
        observations[(latency, reverse, arm)] = tables
    result = summarize(reports[0]["r_rows"], reports[1]["r_rows"], observations)
    result["inputs"] = [{"path": str(path), "sha256": sha256_file(path)} for path in (run, reference)]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("choose a fresh analysis output")
    result = analyze(args.run.resolve(), args.reference.resolve())
    atomic_write_json(args.output, result)
    print(json.dumps({key: value for key, value in result.items() if key not in ("observations", "inputs")}))
