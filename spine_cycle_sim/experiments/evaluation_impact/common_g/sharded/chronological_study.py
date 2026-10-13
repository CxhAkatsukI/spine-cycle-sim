"""Prepare, run or package chronological controls through the shared G runner."""

import argparse
from functools import partial
import json
from pathlib import Path
import sys

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json
from spine_cycle_sim.experiments.upstream_controls.execution import run_bounded
from ..study import ROOT
from .chronological_contract import case_names, contract
from .chronological_inputs import DATASETS, STATUS
from .delivery import package
from .real_analysis import analyze
from .study import run


def prepare(output):
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "PREPARING", "datasets": list(DATASETS), "steps": []}
    try:
        for dataset in DATASETS:
            print("PREPARE " + dataset, flush=True)
            step = run_bounded([sys.executable, "-m",
                "spine_cycle_sim.experiments.evaluation_impact.common_g.sharded.chronological_inputs",
                "--output", str(output / dataset), "--dataset", dataset], ROOT, output / "raw" / dataset,
                timeout=900, memory_gib=2, reserve_gib=8)
            report["steps"].append(step)
            if step["exit_code"] or step["timed_out"]:
                raise ValueError("bounded chronological preparation failed: " + dataset)
        report["status"] = "PREPARED"
        atomic_write_json(output / "preparation.json", report)
        contract(output)
    except BaseException as error:
        report.update(status="FAILED_RETAINED", error=repr(error))
        raise
    finally:
        atomic_write_json(output / "preparation.json", report)
    print(json.dumps({"status": report["status"], "datasets": report["datasets"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--output", required=True, type=Path)
    execute = commands.add_parser("run")
    execute.add_argument("--output", required=True, type=Path)
    execute.add_argument("--prepared", required=True, type=Path)
    execute.add_argument("--core-build", required=True, type=Path)
    deliver = commands.add_parser("package")
    deliver.add_argument("--output", required=True, type=Path)
    deliver.add_argument("--matrix", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.output.resolve())
    elif args.command == "run":
        declared = contract(args.prepared.resolve())
        run(args.output.resolve(), args.core_build.resolve(), contract=declared,
            analyze_rows=partial(analyze, contract=declared, names=case_names()),
            target="real_sharded_g_execution", tag="REAL_G_RESULT", status=STATUS)
    else:
        report = json.loads(args.matrix.read_text())
        result = package(args.output.resolve(), args.matrix.resolve(), status=STATUS,
            analyze_rows=partial(analyze, contract=report["contract"], names=case_names()))
        print(json.dumps({key: result[key] for key in ("status", "prediction_rows")}))


if __name__ == "__main__":
    main()
