"""Collect the two fixed-threshold Fig. 7 ResPR FPGA matrices."""

import argparse
import csv
import math
import shutil
from pathlib import Path


DATASETS = ("AU", "SU", "WK", "SO", "PK", "LJ", "LJ08", "R19")
THRESHOLDS = {"high": "1e-7", "low": "3e-9"}
RETAINED = {("high", "AU"), ("high", "SU"), ("high", "R19"), ("low", "SO")}
FIELDS = (
    "dataset", "absolute_threshold", "vertices", "initial_edges", "insertions",
    "checkpoint_old_max_abs_residual", "batch_max_abs_residual", "checkpoint_old_active",
    "spine_initial_active", "gr_initial_active", "spine_rounds", "gr_rounds",
    "spine_logical_edges_served", "spine_wall_ms", "gr_wall_ms", "spine_speedup",
    "activity_counts_match", "spine_correctness", "gr_correctness", "pairs", "fpga_bdf",
    "origin", "evidence",
)
ARTIFACTS = {".command", ".end", ".exit", ".log", ".memory", ".peak", ".sha256", ".start"}


def record(path, tag):
    with path.open() as stream:
        for line in stream:
            if line.startswith(tag + " "):
                return dict(token.split("=", 1) for token in line.split()[1:] if "=" in token)
    raise ValueError(f"{path.name}: missing {tag}")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def measured_row(dataset, group, source, preflight, retained):
    tag = "RESIDUAL_PR_PMA_NATIVE_SHARDED_"
    epsilon = THRESHOLDS[group]
    suffix = ".board.log" if retained and dataset == "AU" else ".log"
    spine_log, gr_log = (source / f"{arm}{suffix}" for arm in ("spine", "gr"))
    for arm in ("spine", "gr"):
        require((source / f"{arm}.exit").read_text().strip() == "0", f"{arm} did not complete")
    board = record(spine_log, "SPINE_DEVICE")["bdf"]
    active = record(spine_log, "RESIDENT_PROPAGATION")
    spine = record(spine_log, "SPINE_RESIDENT_BENCHMARK_PASS")
    old = record(gr_log, "SHARED_RESPR_CHECKPOINT")
    inputs = record(gr_log, tag + "INPUT")
    timing = record(gr_log, tag + "TIMING")
    results = record(gr_log, tag + "RESULT")
    require(board == record(gr_log, "GRASU_REGRAPH_DEVICE")["bdf"] == "0000:82:00.1",
            "not a pair on the selected U55C")
    require(float(epsilon) == float(active["epsilon"]) == float(inputs["epsilon"]),
            "wrong absolute threshold")
    require(inputs["threshold_semantics"] == "direct_per_vertex", "wrong threshold semantics")
    require(old["old_active"] == "0" and float(preflight["old_max_residual"]) < float(epsilon),
            "old checkpoint has active residual")
    require(Path(old["path"]).name == "rank.f32", "unexpected loaded rank checkpoint")
    require(spine["logical_updates"] == inputs["logical_updates"] == "8", "not eight insertions")
    require(spine["vertices"] == inputs["vertices"], "different graph sizes")
    require(active["status"] == results["status"] == "PASS", "CPU correctness check failed")
    require(all(results[key] == "0" for key in ("rank_mismatches", "degree_mismatches")),
            "G+R state differs from the reference")
    require(inputs["oracle_converged"] == results["hardware_converged"] == "1",
            "G+R did not converge")
    require(active["rounds"] == spine["iterations"], "Delta.hls round count inconsistent")
    require(results["propagation_rounds"] == inputs["oracle_propagation_rounds"],
            "G+R board and oracle round counts differ")
    spine_rounds, gr_rounds = int(active["rounds"]), int(results["propagation_rounds"])
    if group == "low":
        require(spine_rounds > 0 and gr_rounds > 0, "both systems must propagate at the low threshold")
    spine_ms, gr_ms = float(spine["wall_ms"]), float(timing["setup_inclusive_ms"])
    require(all(math.isfinite(t) and t > 0 for t in (spine_ms, gr_ms)), "invalid wall time")
    matched = (active["initial_active"] == inputs["oracle_correction_active"]
               and spine_rounds == gr_rounds)
    return [
        dataset, epsilon, inputs["vertices"], inputs["static_edges"], inputs["logical_updates"],
        preflight["old_max_residual"], preflight["updated_max_residual"], old["old_active"],
        active["initial_active"], inputs["oracle_correction_active"], spine_rounds, gr_rounds,
        active["logical_edges_served"], spine["wall_ms"], timing["setup_inclusive_ms"],
        f"{gr_ms / spine_ms:.6f}", int(matched), active["status"], results["status"], 1, board,
        "retained_exact" if retained else "new", f"evidence/{group}/{dataset}/",
    ]


def archive(folder, target, cpu_log, previous, dataset, retained):
    target.mkdir(parents=True, exist_ok=True)
    au_pilot = retained and dataset == "AU"
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix not in ARTIFACTS:
            continue
        if au_pilot and not (path.name.startswith(("spine.", "gr."))
                             or path.name in {"board.memory", "run-inputs.sha256"}):
            continue
        shutil.copyfile(path, target / path.name)
    shutil.copyfile(cpu_log, target / "cpu-preflight.log")
    checkpoint_manifest = previous if dataset == "AU" else previous / "respr-matrix" / dataset
    manifest = checkpoint_manifest / "run-inputs.sha256"
    if manifest.exists() and folder != checkpoint_manifest:
        shutil.copyfile(manifest, target / "prior-inputs.sha256")


def write_csv(path, fields, rows):
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(fields)
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("previous", type=Path, help="original checked checkpoint/replay directory")
    parser.add_argument("scratch", type=Path, help="new fixed-threshold run directory")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    status = []
    for group, epsilon in THRESHOLDS.items():
        rows = []
        for dataset in DATASETS:
            au = dataset == "AU"
            preflight_dir = args.previous if au else args.previous / "respr-matrix" / dataset
            cpu_log = preflight_dir / ("spine-preflight.log" if au else "preflight.log")
            retained = (group, dataset) in RETAINED
            folder = preflight_dir if retained else args.scratch / group / dataset
            target = args.output / "evidence" / group / dataset
            if not retained and not (folder / "case.exit").exists():
                status.append((group, epsilon, dataset, "PENDING", "", "attempt not finished"))
                continue
            archive(folder, target, cpu_log, args.previous, dataset, retained)
            try:
                if not (retained and au):
                    code = (folder / "case.exit").read_text().strip()
                    require(code == "0", f"runner exited {code}; see case.log and arm logs")
                row = measured_row(dataset, group, folder, record(cpu_log, "RESIDENT_PREFLIGHT"), retained)
                rows.append(row)
                detail = "activity counts match" if row[FIELDS.index("activity_counts_match")] else "activity counts differ"
                status.append((group, epsilon, dataset, "PASS", row[FIELDS.index("origin")], detail))
            except (OSError, ValueError, KeyError) as exc:
                status.append((group, epsilon, dataset, "NO_VALID_PAIR", "new" if not retained else "retained_exact",
                               str(exc)))
        write_csv(args.output / f"respr_{group}.csv", FIELDS, rows)
        print(f"{group} ({epsilon}): {len(rows)}/{len(DATASETS)} valid FPGA pairs")
    write_csv(args.output / "matrix_status.csv",
              ("group", "absolute_threshold", "dataset", "status", "origin", "detail"), status)


if __name__ == "__main__":
    main()
