"""Combine disjoint one-pass Fig. 8 campaigns without rerunning any arm."""

import argparse
import copy
import json
from pathlib import Path
import shutil

from . import analysis, delivery


CONFIG = ("boundary", "samples_per_arm", "warmups", "timing_source", "metadata_replicas",
          "bdf", "device", "inputs", "hardware", "artifacts", "memory_gib", "memory_profile")
OPTIONAL_CONFIG = ("persistent_layout", "memory_high_gib", "memory_max_bytes", "memory_high_bytes",
                   "memory_swap_max", "live_reserve_gib", "bootstrap_min_level", "physical_limit",
                   "active_buffer_records", "active_buffer_policy", "graph_uploads",
                   "sparse_scratch_init", "host_bound_scratch", "metadata_uploads", "compact_host_staging",
                   "uninitialized_host_backing")
REPAIRS = {
    "fixed-carry-v3": dict(persistent_layout="fixed-v3", physical_limit=8192),
    "fixed-carry-v4": dict(persistent_layout="fixed-v4", physical_limit=8192,
                           bootstrap_min_level=10, active_buffer_records=1,
                           active_buffer_policy="maint-only"),
    "fixed-carry-v5": dict(persistent_layout="fixed-v5", physical_limit=8192,
                           bootstrap_min_level=10, active_buffer_records=1,
                           active_buffer_policy="maint-only", graph_uploads=1),
}
REPAIRS["fixed-carry-v6"] = dict(REPAIRS["fixed-carry-v5"], persistent_layout="fixed-v6",
                                sparse_scratch_init=1)
REPAIRS["fixed-carry-v7"] = dict(REPAIRS["fixed-carry-v6"], persistent_layout="fixed-v7",
                                host_bound_scratch=0, metadata_uploads=1)
REPAIRS["fixed-carry-v8"] = dict(REPAIRS["fixed-carry-v7"], persistent_layout="fixed-v8",
                                compact_host_staging=1)
REPAIRS["fixed-carry-v9"] = dict(REPAIRS["fixed-carry-v8"], persistent_layout="fixed-v9",
                                host_bound_scratch=1, uninitialized_host_backing=1)


def repair_evidence(run, report, *, single_upload=False, sparse_scratch=False,
                    single_metadata_upload=False, compact_host_staging=False,
                    host_bound_scratch=0, uninitialized_host_backing=False):
    identified = False
    for case in report["cases"]:
        arm = case["arms"]["spine"]
        path = run / case["name"] / "spine.stdout.txt"
        text = path.read_text() if path.exists() else ""
        layouts = analysis.records(text, "SPINE_PERSISTENT_LAYOUT")
        if layouts and (len(layouts) != 1 or layouts[0].get("fixed") != "1"):
            raise ValueError("raw layout receipt contradicts the fixed-layout repair")
        identified |= bool(layouts)
        if arm["status"] != "PASS":
            continue
        if not layouts or "physical_launches" not in arm["timing"]:
            raise ValueError("repair requires fixed=1 and physical launch receipts")
        if single_upload:
            delivery.check_single_graph_upload(text)
        if sparse_scratch:
            delivery.check_sparse_scratch_init(text, single_metadata_upload=single_metadata_upload,
                                                compact_host_staging=compact_host_staging,
                                                host_bound_scratch=host_bound_scratch,
                                                uninitialized_host_backing=uninitialized_host_backing)
        total, number = case["updates"], case["batches"]
        for index, batch in enumerate(analysis.records(text, "SPINE_PERSISTENT_BATCH")):
            begin, end = index * total // number, (index + 1) * total // number
            if (int(batch.get("begin", -1)) != begin or int(batch.get("end", -1)) != end
                    or int(batch["physical_launches"]) != (end - begin + 8191) // 8192):
                raise ValueError("repair changed chronological spans or hid physical launches")
    return identified


def combine(runs, output, *, repair=None):
    runs, output = [Path(run).resolve() for run in runs], Path(output).resolve()
    if not runs or len(set(runs)) != len(runs):
        raise ValueError("distinct source campaign directories required")
    if output.exists() or any(run in output.parents for run in runs):
        raise ValueError("merge output must be fresh and outside source campaigns")
    if repair is not None and repair not in REPAIRS:
        raise ValueError("unsupported repair policy")
    reports = [delivery.checked_report(run, partial=True) for run in runs]
    first = reports[0]
    for report in reports:
        if any(key not in report for key in CONFIG):
            raise ValueError("missing campaign configuration")
        if any(report[key] != first[key] for key in CONFIG):
            raise ValueError("campaign inputs, artifacts or execution configuration differ")
        if any(report.get(key) != first.get(key) for key in OPTIONAL_CONFIG):
            raise ValueError("campaign memory or layout configuration differs")
    if first.get("persistent_layout", "").startswith("fixed-") and repair is None:
        raise ValueError("fixed-layout campaigns require an explicit --repair policy")
    policy = REPAIRS.get(repair, {})
    if any(key in first and first[key] != value for key, value in policy.items()):
        raise ValueError("declared repair contradicts recorded campaign configuration")
    plan = delivery.input_plan(runs[0], first)
    hardware = Path(first["hardware"]["path"])
    delivery.verify_file(hardware, first["hardware"])
    bindings = json.loads(hardware.read_text())
    if set(bindings) != {arm + "_" + kind for arm in ("spine", "gr") for kind in ("host", "image")}:
        raise ValueError("exactly four hardware bindings required")
    if set(bindings) != set(first["artifacts"]):
        raise ValueError("hardware bindings differ from artifact receipts")
    for key, artifact in first["artifacts"].items():
        if str(Path(bindings[key]).resolve()) != artifact["path"]:
            raise ValueError("artifact path differs from hardware binding")
        delivery.verify_file(artifact["path"], artifact)
    selected = {}
    for index, report in enumerate(reports):
        for case in report["cases"]:
            if case["name"] in selected:
                raise ValueError("duplicate case, including failed attempts: " + case["name"])
            selected[case["name"]] = case
    if set(selected) != {case["name"] for case in plan["cases"]}:
        raise ValueError("missing declared cases, including failed attempts")
    if repair:
        evidence = [repair_evidence(run, report, single_upload=policy.get("graph_uploads") == 1,
                                    sparse_scratch=policy.get("sparse_scratch_init") == 1,
                                    single_metadata_upload=policy.get("metadata_uploads") == 1,
                                    compact_host_staging=policy.get("compact_host_staging") == 1,
                                    host_bound_scratch=policy.get("host_bound_scratch", 0),
                                    uninitialized_host_backing=policy.get("uninitialized_host_backing") == 1)
                    for run, report in zip(runs, reports)]
        if not any(evidence):
            raise ValueError("no raw fixed-layout evidence for the declared repair")
    merged = {key: copy.deepcopy(first[key]) for key in (*CONFIG, *OPTIONAL_CONFIG) if key in first}
    merged["cases"] = [copy.deepcopy(selected[case["name"]]) for case in plan["cases"]]
    merged["status"] = ("COMPLETED" if all(c["status"] == "MEASURED" for c in merged["cases"])
                        else "COMPLETED_WITH_FAILURES")
    merged["memory_peak_bytes"] = max(report["memory_peak_bytes"] for report in reports)
    merged["source_campaigns"], merged["case_sources"] = [], {}
    if repair:
        merged.update(policy, repair=repair)
    output.mkdir(parents=True, exist_ok=False)
    for index, (run, report) in enumerate(zip(runs, reports)):
        retained = output / "source_campaigns" / f"{index:02d}"
        retained.mkdir(parents=True)
        for path in run.iterdir():
            if path.is_file():
                shutil.copy2(path, retained / path.name)
        journal = retained / "results.json"
        if json.loads(journal.read_text()) != report:
            raise ValueError("source journal changed during merge")
        receipt = dict(path=str(journal.relative_to(output)), sha256=delivery.checksum(journal),
                       bytes=journal.stat().st_size)
        merged["source_campaigns"].append(dict(directory=str(run), journal=receipt,
                                                status=report["status"],
                                                memory_peak_bytes=report["memory_peak_bytes"],
                                                memory_events=report.get("memory_events")))
        for case in report["cases"]:
            shutil.copytree(run / case["name"], output / case["name"])
            merged["case_sources"][case["name"]] = receipt["path"]
    source_plan = runs[0] / "inputs.json"
    shutil.copy2(source_plan if source_plan.exists() else first["inputs"]["path"], output / "inputs.json")
    shutil.copy2(hardware, output / "hardware.json")
    (output / "results.json").write_text(json.dumps(merged, indent=2) + "\n")
    analysis.write_table(merged, output / "fig8_fpga.csv")
    return delivery.checked_report(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repair", choices=tuple(REPAIRS))
    args = parser.parse_args()
    combine(args.run, args.output, repair=args.repair)
