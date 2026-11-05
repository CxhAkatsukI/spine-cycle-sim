"""Package checked ten-batch predictions separately from all FPGA measurements."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.evaluation_impact.figure_refresh import analysis

DATASETS = ("AU", "SU", "WK", "SO", "PK")
STATUS = "PERSISTENT_PAIRED_SETUP_PREDICTION"


def checked(pin):
    content = Path(pin["path"]).read_bytes()
    if len(content) != pin["bytes"] or hashlib.sha256(content).hexdigest() != pin["sha256"]:
        raise ValueError("changed persistent receipt: " + pin["path"])
    return content


def collect(dataset, path, *, updates=4096, batches=10, sensitivity=False):
    report_bytes = path.read_bytes()
    report = json.loads(report_bytes)
    comparison = report["comparisons"]["trace"]
    if (dataset not in DATASETS or report["status"] != STATUS or comparison["status"] != STATUS
            or comparison["baseline_admitted"] is not False
            or (comparison["updates"], comparison["batches"], comparison["host_samples_per_arm"]) != (updates, batches, 1)):
        raise ValueError("expected one matched persistent-update prediction")
    if sensitivity and (dataset != "AU" or updates != 131072 or batches not in (10, 100, 1000)):
        raise ValueError("unexpected batch sensitivity input scope")
    prefix = f"AU_b{batches}" if sensitivity else dataset
    members = {f"{prefix}/results.json": report_bytes}
    manifests = [pin for pin in report["pins"] if
                 Path(pin["path"]).name == "manifest.json" and (
                     Path(pin["path"]).parent.parent.name == "batch_sensitivity" if sensitivity else
                     Path(pin["path"]).parts[-3:] == ("cross_dataset", dataset.lower(), "manifest.json"))]
    if len(manifests) != 1:
        raise ValueError("dataset does not match the pinned cross-dataset manifest")
    manifest_bytes = checked(manifests[0])
    manifest = json.loads(manifest_bytes)
    members[f"{prefix}/input_manifest.json"] = manifest_bytes
    for key in ("graph", "updates"):
        pin = next(pin for pin in report["pins"] if pin["path"] == manifest[key])
        checked(pin)
    for arm in ("spine", "gr"):
        name = "trace_" + arm
        row = report["rows"][name]
        device = analysis.persistent_device(report["steps"][name], arm=arm, updates=updates, batch_count=batches)
        host = analysis.persistent_host(report["steps"][name + "_host"], arm=arm, updates=updates, batch_count=batches)
        if device != {key: row[key] for key in ("device", "batches")} or host != row["host"]:
            raise ValueError("stored rows differ from checked device/host logs")
        for key in ("config", "backend", "stdout"):
            pin = row[key]
            members[f"{prefix}/{arm}/{key}" + Path(pin["path"]).suffix] = checked(pin)
        config = json.loads(checked(row["config"]))
        if any(config[key] != manifest[key] for key in ("graph", "updates")):
            raise ValueError("device arm used different input data")
        for key, pin in row["host_evidence"].items():
            members[f"{prefix}/{arm}/host_{key}" + Path(pin["path"]).suffix] = checked(pin)
        if not all(math.isfinite(comparison[arm][key]) and comparison[arm][key] > 0
                   for key in ("host_seconds", "transfer_seconds", "device_seconds", "setup_inclusive_seconds")):
            raise ValueError("invalid timing terms")
    recalculated = analysis.persistent_comparison(
        {arm: report["rows"]["trace_" + arm] for arm in ("spine", "gr")}, updates=updates, batch_count=batches)
    if comparison != recalculated:
        raise ValueError("comparison does not match the declared setup formula")
    row = dict(dataset=dataset, status=STATUS, updates=updates, batches=batches,
               host_samples_per_arm=1, cpu=report["cpu"], baseline_admitted=False,
               speedup_gr_over_spine=comparison["speedup_gr_over_spine"],
               receipt_sha256=hashlib.sha256(report_bytes).hexdigest())
    for arm in ("spine", "gr"):
        row.update({arm + "_" + key: value for key, value in comparison[arm].items()})
        row[arm + "_device_cycles"] = report["rows"]["trace_" + arm]["device"]["cycles"]
    return row, members


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", nargs=2, metavar=("DATASET", "RESULTS_JSON"), required=True)
    parser.add_argument("--sweep", action="append", nargs=2, metavar=("BATCHES", "RESULTS_JSON"), default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {name: Path(path) for name, path in args.case}
    if len(paths) != len(args.case) or set(paths) - set(DATASETS):
        raise ValueError("unique, predeclared dataset labels required")
    rows, members = [], {}
    for dataset in DATASETS:
        if dataset in paths:
            row, files = collect(dataset, paths[dataset])
            rows.append(row)
            members.update(files)
    sweep_paths = {int(count): Path(path) for count, path in args.sweep}
    if len(sweep_paths) != len(args.sweep) or set(sweep_paths) - {10, 100, 1000}:
        raise ValueError("unique, predeclared batch counts required")
    sweep_rows = []
    for count in sorted(sweep_paths):
        row, files = collect("AU", sweep_paths[count], updates=131072, batches=count, sensitivity=True)
        sweep_rows.append(row)
        members.update(files)
    scope = dict(status="COMPLETE" if len(rows) == len(DATASETS) else "PARTIAL_RETAINED",
                 evidence="single-sample host plus simulator/transfer prediction, not FPGA",
                 expected=list(DATASETS), measured=[row["dataset"] for row in rows],
                 missing=[name for name in DATASETS if name not in paths],
                 sensitivity=dict(expected_batches=[10, 100, 1000], total_updates=131072,
                                  measured_batches=sorted(sweep_paths)),
                 batch_override="b10 reuses b100's frozen graph/update input; explicit command sets ten batches")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "fig8_ten_batch_scope.json").write_text(json.dumps(scope, indent=2) + "\n")
    with (args.output / "fig8_ten_batch.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    if sweep_rows:
        with (args.output / "fig8_batch_sensitivity.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(sweep_rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(sweep_rows)
    with (args.output / "fig8_ten_batch_receipts.tar.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                for name, content in sorted(members.items()):
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))


if __name__ == "__main__":
    main()
