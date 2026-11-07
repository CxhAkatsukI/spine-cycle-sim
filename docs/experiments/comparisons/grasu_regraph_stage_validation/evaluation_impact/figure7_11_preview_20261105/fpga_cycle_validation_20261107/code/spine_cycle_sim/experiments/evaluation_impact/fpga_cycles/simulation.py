"""Bounded warm-SSSP runs using the production SST engine."""

import argparse
import json
from pathlib import Path
import sys

from ...upstream_controls.execution import run_bounded
from ...original_regraph_execution.hardware.source_retention.runtime import identity, save

ROOT = Path(__file__).resolve().parents[4]


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    plan = json.loads(args.inputs.read_text())
    report = dict(status="RUNNING", inputs=identity(args.inputs), profile=identity(args.profile),
                  plugin=identity(args.library / "libspine_cycle.so"), rows=[])
    for case in plan["cases"]:
        if case["split"] != args.split:
            continue
        output = args.output / case["name"]
        command = [sys.executable, str(ROOT / "scripts/run_sst_spine_vertical.py"),
                   "--validation-mode", "generic", "--profile", str(args.profile.resolve()),
                   "--scenario", "dynamic_sssp", "--sssp-warm-start", "--source", "0",
                   "--workload", case["initial"], "--update-workload", case["update"],
                   "--out-dir", str(output), "--lib-dir", str(args.library.resolve()),
                   "--max-cycles", "10000000", "--max-rounds", "32", "--no-build"]
        if args.transport_read_cycles is not None:
            command += ["--axi-transport-read-cycles", str(args.transport_read_cycles)]
        step = run_bounded(command, ROOT, args.output / "raw" / case["name"],
                           timeout=120, memory_gib=4, reserve_gib=32)
        row = dict(case, execution=step, result_path=str(output / "result.json"))
        row["status"] = "PASS" if step["exit_code"] == 0 and not step["timed_out"] else "FAILED_RETAINED"
        if row["status"] == "PASS":
            result = json.loads((output / "result.json").read_text())
            row.update(cycles=result["update_cycles"], rounds=result["rounds"],
                       maintenance_cycles=result["maintenance_end_cycle"] - result["maintenance_start_cycle"])
        report["rows"].append(row)
        save(args.output / "results.json", report)
        print(case["name"], row["status"], row.get("cycles"), flush=True)
    report["status"] = "COMPLETE" if all(row["status"] == "PASS" for row in report["rows"]) else "PARTIAL_RETAINED"
    save(args.output / "results.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("inputs", "profile", "library", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--split", choices=("development", "holdout"), required=True)
    parser.add_argument("--transport-read-cycles", type=int)
    run(parser.parse_args())
