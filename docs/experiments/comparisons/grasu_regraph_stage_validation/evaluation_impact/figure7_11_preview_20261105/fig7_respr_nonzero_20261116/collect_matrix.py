"""Collect measured nonzero ResPR pairs; never fill gaps with old data."""

import argparse
import csv
import math
import shutil
from pathlib import Path


DATASETS = ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19")


def record(path, tag):
    for line in reversed(path.read_text().splitlines()):
        if line.startswith(tag + " "):
            return dict(token.split("=", 1) for token in line.split()[1:] if "=" in token)
    raise ValueError(f"{path.name}: missing {tag}")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def measured_row(dataset, folder):
    au = dataset == "AU"
    suffix = ".board.log" if au else ".log"
    delta_log, gr_log = (folder / f"{name}{suffix}" for name in ("spine", "gr"))
    delta_bdf = record(delta_log, "SPINE_DEVICE")["bdf"]
    gr_bdf = record(gr_log, "GRASU_REGRAPH_DEVICE")["bdf"]
    preflight = record(folder / ("spine-preflight.log" if au else "preflight.log"), "RESIDENT_PREFLIGHT")
    active = record(delta_log, "RESIDENT_PROPAGATION")
    delta = record(delta_log, "SPINE_RESIDENT_BENCHMARK_PASS")
    timing = record(gr_log, "RESIDUAL_PR_PMA_NATIVE_SHARDED_TIMING")
    inputs = record(gr_log, "RESIDUAL_PR_PMA_NATIVE_SHARDED_INPUT")
    results = record(gr_log, "RESIDUAL_PR_PMA_NATIVE_SHARDED_RESULT")
    old = record(gr_log, "SHARED_RESPR_CHECKPOINT")

    require(active["status"] == results["status"] == "PASS", "board correctness failed")
    require(delta_bdf == gr_bdf, "pair measured on different FPGA devices")
    require(all(results[key] == "0" for key in ("rank_mismatches", "degree_mismatches")),
            "G+R state mismatch")
    require(old["old_active"] == "0", "shared checkpoint already had active residual")
    require(inputs["oracle_converged"] == results["hardware_converged"] == "1",
            "G+R did not converge")
    require(delta["logical_updates"] == inputs["logical_updates"] == "8", "expected eight insertions")
    require(delta["vertices"] == inputs["vertices"], "vertex count mismatch")
    require(float(active["epsilon"]) == float(inputs["epsilon"]), "threshold mismatch")
    require(float(preflight["old_max_residual"]) < float(active["epsilon"])
            < float(preflight["updated_max_residual"]), "threshold outside clean activity window")
    require(int(active["initial_active"]) > 0 and int(inputs["oracle_correction_active"]) > 0,
            "empty propagation seed")
    require(int(active["rounds"]) > 0 and int(results["propagation_rounds"]) > 0,
            "no board propagation")
    require(active["rounds"] == delta["iterations"], "Delta.hls round count inconsistent")
    require(results["propagation_rounds"] == inputs["oracle_propagation_rounds"],
            "G+R board and oracle round counts differ")
    delta_ms, gr_ms = float(delta["wall_ms"]), float(timing["setup_inclusive_ms"])
    require(all(math.isfinite(t) and t > 0 for t in (delta_ms, gr_ms)), "invalid time")

    return [
        dataset, "ResPR", inputs["vertices"], inputs["static_edges"], inputs["logical_updates"],
        inputs["epsilon"], old["old_active"], active["initial_active"],
        inputs["oracle_correction_active"], active["rounds"], results["propagation_rounds"],
        active["logical_edges_served"], delta["wall_ms"], timing["setup_inclusive_ms"],
        f"{gr_ms / delta_ms:.6f}", active["status"], results["status"], 1, delta_bdf,
    ]


def retain_evidence(folder, target):
    target.mkdir(parents=True, exist_ok=True)
    allowed = {".command", ".end", ".exit", ".log", ".memory", ".peak", ".sha256", ".start"}
    for path in sorted(folder.iterdir()):
        if path.is_file() and (path.suffix in allowed or path.name == "epsilon.txt"):
            shutil.copyfile(path, target / path.name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scratch", type=Path, help="original AU replay directory")
    parser.add_argument("--matrix", type=Path, help="alternate scratch directory for the seven runs")
    args = parser.parse_args()
    matrix = args.matrix or args.scratch / "respr-matrix"
    handoff = Path(__file__).resolve().parent
    with (handoff / "au_respr.csv").open(newline="") as stream:
        header = [*next(csv.reader(stream)), "fpga_bdf"]

    rows, status = [], []
    for dataset in DATASETS:
        folder = args.scratch if dataset == "AU" else matrix / dataset
        if dataset != "AU" and not (folder / "case.exit").is_file():
            status.append((dataset, "PENDING", "no completed attempt recorded"))
            continue
        try:
            if dataset != "AU":
                require((folder / "case.exit").read_text().strip() == "0", "runner failed")
            row = measured_row(dataset, folder)
            rows.append(row)
            activity_match = row[7] == row[8] and row[9] == row[10]
            status.append((dataset, "PASS", "same seed and round counts" if activity_match
                           else "seed or round counts differ; check raw evidence"))
        except (OSError, ValueError, KeyError) as exc:
            status.append((dataset, "NO_ADMITTED_PAIR", str(exc)))
        if dataset != "AU" and folder.is_dir() and (folder / "case.exit").is_file():
            retain_evidence(folder, handoff / "evidence" / dataset)

    for name, fields, data in (
        ("respr_nonzero_fpga.csv", header, rows),
        ("matrix_status.csv", ("dataset", "status", "detail"), status),
    ):
        with (handoff / name).open("w", newline="") as stream:
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(fields)
            writer.writerows(data)
    print(f"{len(rows)}/{len(DATASETS)} measured nonzero FPGA pairs")


if __name__ == "__main__":
    main()
