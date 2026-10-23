"""Export explicit complete-pair selections; never fill gaps with historical rows."""

import copy
import csv
import json
from pathlib import Path

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from . import analysis, matrix


def write_csv(path, rows, fields=None):
    fields = fields or list(rows[0])
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def selected(small, large, propagation):
    """Each input role is fixed before looking at its numeric outcomes."""
    rows, missing, sources = [], matrix.unsupported(), []
    for path, figure, datasets in ((small, 8, {"AU", "SU", "WK"}),
                                  (large, 8, {"SO", "PK"}),
                                  (propagation, 9, {"AU", "SU", "WK"})):
        report = json.loads(path.read_text())
        if report.get("pins_unchanged") is not True or report.get("baseline_admitted") is not False:
            raise ValueError("unchanged pinned exploratory run required")
        sources.append(dict(path=str(path), sha256=sha256_file(path), status=report["status"]))
        for case in report["matrix"]:
            if case["figure"] != figure or case["dataset"] not in datasets:
                continue
            if figure == 9 and case["root"] != matrix.HISTORICAL_ROOTS[case["dataset"]]:
                raise ValueError("historical source required for Figure 9")
            matches = [r for r in report["rows"] if
                       (r.get("case", r).get("figure"), r.get("case", r).get("dataset"),
                        r.get("case", r).get("updates")) ==
                       (figure, case["dataset"], case["updates"])]
            if len(matches) != 1 or matches[0]["status"] != "PREDICTION_ONLY":
                missing.append(dict(figure=figure, dataset=case["dataset"], algorithm=case["algorithm"],
                    status="INCOMPLETE_RETAINED", reason="selected attempt has no complete pair"))
                continue
            row = copy.deepcopy(matches[0])
            if figure == 8:
                if row["spine"].get("physical_image_checked") is not True:
                    raise ValueError("physical Spine bootstrap/update image validation required")
                for arm in ("spine", "gr"):
                    samples = row[arm]["host"]["samples"]
                    if len(samples) != 5 or any(not s.get("bootstrap_complete") or
                            not s.get("batch_preparation_complete") for s in samples):
                        raise ValueError("complete bootstrap and batch preparation measurements required")
            if analysis.comparison(case, {arm: copy.deepcopy(row[arm]) for arm in ("spine", "gr")}) != row:
                raise ValueError("comparison arithmetic differs from recorded arms")
            row.update(case=case, source_report=str(path), source_report_sha256=sha256_file(path))
            rows.append(row)
    keys = [(r["figure"], r["dataset"], r["updates"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate comparison selection")
    expected = {(c["figure"], c["dataset"], c["updates"]) for c in matrix.cases()}
    accounted = set(keys) | {(m["figure"], m["dataset"], c["updates"]) for m in missing
        for c in matrix.cases() if c["figure"] == m["figure"] and c["dataset"] == m["dataset"]
        and c["algorithm"] == m["algorithm"]}
    if accounted != expected:
        raise ValueError("selection does not account for the complete declared matrix")
    return rows, missing, sources


def export(output, small, large, propagation, historical):
    rows, missing, sources = selected(small, large, propagation)
    output.mkdir(parents=True, exist_ok=False)
    update, memory, absolute_update, absolute_memory, changes = [], [], [], [], []
    for row in rows:
        case = row["case"]
        identity = dict(dataset=row["dataset"], algorithm=row["algorithm"], updates=row["updates"])
        if row["figure"] == 8:
            update.append(dict(dataset=row["dataset"], logical_updates=row["updates"], batch_count=1,
                updates_per_batch=row["updates"], spine_kups=row["spine"]["updates_per_second"] / 1000,
                grasu_kups=row["gr"]["updates_per_second"] / 1000, spine_speedup=row["speedup"]))
        else:
            memory.append(dict(dataset=row["dataset"], algorithm="weighted_sssp", algorithm_label="SSSP",
                memory_ratio_gr_over_spine=row["accepted_bytes_ratio"],
                hbm_energy_ratio_gr_over_spine=row["hbm_energy_ratio"],
                spine_memory_bytes=row["spine"]["read_bytes"] + row["spine"]["write_bytes"],
                gr_memory_bytes=row["gr"]["read_bytes"] + row["gr"]["write_bytes"]))
        for arm in ("spine", "gr"):
            data = row[arm]
            absolute = dict(**identity, arm=arm, source=case["root"], vertices=case["vertices"],
                initial_edges=case["initial_edges"], device_cycles=data["cycles"],
                read_bytes=data["read_bytes"], write_bytes=data["write_bytes"],
                evidence=data["evidence"], report_sha256=row["source_report_sha256"])
            if row["figure"] == 8:
                h = data["host"]
                absolute.update(host_median_ns=h["median_ns"], host_min_ns=min(s["nanoseconds"] for s in h["samples"]),
                    host_max_ns=max(s["nanoseconds"] for s in h["samples"]),
                    initial_h2d_bytes=h["initial_h2d_bytes"], batch_h2d_bytes=h["update_h2d_bytes"],
                    setup_seconds=data["setup_seconds"], setup_inclusive_seconds=data["setup_inclusive_seconds"],
                    updates_per_second=data["updates_per_second"])
                absolute.update({key: h["samples"][0][key] for key in (
                    "graph_bytes", "directory_bytes", "metadata_bytes", "constructor_payload_calls")})
                absolute_update.append(absolute)
            else:
                details = analysis.energy_details(Path(data["evidence"]))
                if details["total_energy_pj"] != data["energy_pj"]:
                    raise ValueError("energy differs from raw DRAMSim3 reports")
                absolute.update(rounds=data["rounds"], **details)
                absolute_memory.append(absolute)
    write_csv(output / "fig8_update_cross_dataset.csv", [r for r in update if r["logical_updates"] == 512])
    write_csv(output / "fig8_update_batch_sensitivity.csv", [r for r in update if r["dataset"] == "AU"])
    write_csv(output / "fig8_arms.csv", absolute_update)
    write_csv(output / "fig9_memory_energy_rows.csv", memory)
    write_csv(output / "fig9_arms.csv", absolute_memory)
    write_csv(output / "missing.csv", missing, ["figure", "dataset", "algorithm", "status", "reason"])
    old_files = [historical / name for name in ("fig8_update_cross_dataset.csv",
        "fig8_update_batch_sensitivity.csv", "fig9_memory_energy_rows.csv")]
    for path in old_files:
        old = read_csv(path)
        fresh = memory if path.name.startswith("fig9") else update
        for row in fresh:
            if path.name == "fig8_update_cross_dataset.csv" and row["logical_updates"] != 512:
                continue
            if path.name == "fig8_update_batch_sensitivity.csv" and row["dataset"] != "AU":
                continue
            match = [v for v in old if (v.get("dataset", "AU") == row["dataset"] and
                (v.get("algorithm", "weighted_sssp") == row.get("algorithm", "weighted_sssp")) and
                (int(float(v.get("logical_updates", 8))) == row.get("logical_updates", 8)))]
            if len(match) != 1:
                raise ValueError("unique historical row required")
            metrics = ("spine_speedup",) if path.name.startswith("fig8") else (
                "memory_ratio_gr_over_spine", "hbm_energy_ratio_gr_over_spine")
            for metric in metrics:
                prior = float(match[0][metric])
                changes.append(dict(table=path.name, dataset=row["dataset"], updates=row.get("logical_updates", 8),
                    metric=metric, old=prior, new=row[metric], new_over_old=row[metric] / prior,
                    controlled_ablation=False, caveat="new implementation and traces; energy includes all 32 budget channels"))
    write_csv(output / "old_new_comparison.csv", changes)
    summary = dict(status="COMPLETE_SUPPORTED_SCOPE_WITH_UNSUPPORTED_ALGORITHMS", baseline_admitted=False,
        figure8_pairs=len(update), figure9_pairs=len(memory), missing=missing, source_reports=sources,
        historical_files=[dict(path=str(p), sha256=sha256_file(p)) for p in old_files],
        comparisons=rows, figures=dict(fig8="setup-inclusive one-batch update-only; CPU measured/device predicted",
            fig9="SSSP complete common-warm propagation; accepted bytes and all-channel modeled HBM energy"))
    if len(update) != 7 or len(memory) != 3:
        summary["status"] = "PARTIAL_RETAINED"
    atomic_write_json(output / "summary.json", summary)
    return summary
