"""Export fresh Figure 9 predictions after replaying ledgers and energy sums."""

import argparse
import json
import math
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh import analysis
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.analysis import write_csv
from spine_cycle_sim.experiments.evaluation_impact.figure_refresh.realized_work.delivery import archive


def validate_scope(report):
    expected = {(a, d) for a in ("SSSP", "CC", "ResPR") for d in ("AU", "SU", "WK")}
    rows = report["rows"]
    if (report["status"] != "COMPLETE_SUPPORTED_SCOPE" or report["failures"]
            or report["pins_unchanged"] is not True or report["baseline_admitted"] is not False
            or len(rows) != 9 or {(r["algorithm"], r["dataset"]) for r in rows} != expected):
        raise ValueError("expected the complete, unchanged nine-pair simulator prediction")
    for row in rows:
        if (row["status"], row["baseline_admitted"], row["figure"], row["updates"]) != (
                "PREDICTION_ONLY", False, 9, 8):
            raise ValueError("mixed timing evidence or input scope")


def export(campaign, output):
    report_path = campaign / "results.json"
    report = json.loads(report_path.read_text())
    validate_scope(report)
    steps = {Path(s["command"][-1]).parent: s for s in report["steps"]
             if s["command"][-1].endswith("/config.json")}
    pairs, arms, files = [], [], [(report_path, "results.json")]
    for row in report["rows"]:
        for arm in ("spine", "gr"):
            stored = row[arm]
            directory = Path(stored["evidence"])
            observed = analysis.device(steps[directory])
            if any(stored.get(k) != value for k, value in observed.items()):
                raise ValueError("stored arm differs from its completed log")
            energy = analysis.energy_details(directory)
            if energy != stored["energy_details"] or energy["total_energy_pj"] != stored["energy_pj"]:
                raise ValueError("stored energy differs from the 32-channel ledger")
            for name in ("old_state", "expected", "final"):
                path = directory / (name + ".u32le")
                if sha256_file(path) != stored["state_hashes"][name]:
                    raise ValueError("changed final-state or oracle receipt")
            pin = stored["final_state"]
            if sha256_file(Path(pin["path"])) != pin["sha256"]:
                raise ValueError("changed pinned final state")
            absolute = dict(algorithm=row["algorithm"], dataset=row["dataset"], arm=arm,
                updates=8, status="PREDICTION_ONLY", baseline_admitted=False,
                cycles=stored["cycles"], rounds=stored["rounds"], read_bytes=stored["read_bytes"],
                write_bytes=stored["write_bytes"], energy_pj=stored["energy_pj"], **energy)
            absolute.update({"state_" + k + "_sha256": v for k, v in stored["state_hashes"].items()})
            arms.append(absolute)
        checked = analysis.comparison(row, {arm: row[arm] for arm in ("spine", "gr")})
        for key in ("accepted_bytes_ratio", "hbm_energy_ratio"):
            if not math.isclose(row[key], checked[key], rel_tol=1e-12):
                raise ValueError("plotted ratio differs from absolute counters")
        pairs.append({key: row[key] for key in (
            "algorithm", "dataset", "updates", "status", "baseline_admitted",
            "accepted_bytes_ratio", "hbm_energy_ratio")})
    # Keep logs, configurations and all channel ledgers; index rather than duplicate
    # full input graphs, final-state arrays, toolchains and compiled plugins.
    for directory in (p for p in campaign.iterdir() if p.is_dir() and
                      (p.name.startswith("fig9_") or p.name.startswith("smoke_"))):
        files.extend((p, str(p.relative_to(campaign))) for p in sorted(directory.rglob("*"))
                     if p.is_file() and p.suffix != ".u32le")
    files.extend((p, str(p.relative_to(campaign))) for p in sorted((campaign / "raw").glob("*"))
                 if p.is_file())
    source = campaign / "sources.tar.gz"
    if source.is_file():
        files.append((source, source.name))
    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "fig9_memory_energy_rows.csv", pairs)
    write_csv(output / "fig9_arms.csv", arms)
    index = archive(output / "fig9_receipts.tar.gz", files)
    scope = dict(status="COMPLETE_SIMULATOR_PREDICTION", pairs=9, arms=18,
        baseline_admitted=False, report_sha256=sha256_file(report_path),
        model=report["model"], source_pins=report["pins"], evidence=index,
        not_packaged="graph/state arrays and tool binaries are path/hash-indexed, not embedded",
        not_claimed="not FPGA timing/energy, not a hardware-equivalent complete G+R image")
    atomic_write_json(output / "fig9_scope.json", scope)
    return {key: scope[key] for key in ("status", "pairs", "arms", "baseline_admitted")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.campaign.resolve(), args.output.resolve()), indent=2))


if __name__ == "__main__":
    main()
