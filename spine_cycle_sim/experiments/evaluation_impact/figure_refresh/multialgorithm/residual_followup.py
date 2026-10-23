"""Seal the fixed-epsilon rerun without rewriting the strict-threshold evidence."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from . import delivery, tables, validation
from .study import residual_threshold


EXPECTED = {("ResPR", dataset) for dataset in ("AU", "SU", "WK")}


def record(text, prefix):
    rows = [json.loads(line.removeprefix(prefix)) for line in text.splitlines() if line.startswith(prefix)]
    if len(rows) != 1:
        raise ValueError("one raw " + prefix + "record required")
    return rows[0]


def compare(report, previous, read):
    if report["model"].get("residual_epsilon") != residual_threshold(1e-6):
        raise ValueError("historical fixed per-vertex epsilon required")
    current = validation.selection(report, {}, expected=EXPECTED)
    prior = {(r["algorithm"], r["dataset"]): r for r in validation.selection(previous, {})}
    libraries = lambda r: {Path(p["path"]).name: p["sha256"] for p in r["pins"]
                           if p["path"].endswith(".a")}
    if len(libraries(report)) != 2 or libraries(report) != libraries(previous):
        raise ValueError("threshold-only follow-up must retain both core library identities")
    rows = []
    for row in current:
        old = prior[(row["algorithm"], row["dataset"])]
        if row["case"] != old["case"] or any(row[a]["state_hashes"][s] != old[a]["state_hashes"][s]
                for a in ("spine", "gr") for s in ("old_state", "expected")):
            raise ValueError("threshold comparison must retain graph, batch, old state and oracle")
        if row["spine"]["state_hashes"]["final"] != row["gr"]["state_hashes"]["final"]:
            raise ValueError("these fixed-epsilon arms must have identical final ranks")
        prefix = Path(row["spine"]["evidence"]).parent.name + "/raw/"
        text = read(prefix + Path(row["spine"]["evidence"]).name + ".stdout.txt").decode()
        correction, oracle = record(text, "CORRECTION_TRACE "), record(text, "PR_ORACLE ")
        rows.append(dict(dataset=row["dataset"], vertices=row["case"]["vertices"],
            initial_edges=row["case"]["initial_edges"], updates=8,
            strict_epsilon=residual_threshold(1e-5 / row["case"]["vertices"]),
            fixed_epsilon=report["model"]["residual_epsilon"],
            strict_spine_cycles=old["spine"]["cycles"], strict_gr_cycles=old["gr"]["cycles"],
            strict_spine_rounds=old["spine"]["rounds"], strict_gr_rounds=old["gr"]["rounds"],
            strict_speedup_gr_over_spine=old["gr"]["cycles"] / old["spine"]["cycles"],
            fixed_spine_cycles=row["spine"]["cycles"], fixed_gr_cycles=row["gr"]["cycles"],
            fixed_spine_rounds=row["spine"]["rounds"], fixed_gr_rounds=row["gr"]["rounds"],
            fixed_speedup_gr_over_spine=row["gr"]["cycles"] / row["spine"]["cycles"],
            correction_active_vertices=correction["active_vertices"],
            final_rank_equals_old=row["spine"]["state_hashes"]["final"] == row["spine"]["state_hashes"]["old_state"],
            oracle_max_error=oracle["maximum_error"], oracle_l1_error=oracle["l1_error"],
            oracle_l1_error_bound=oracle["l1_error_bound"],
            accepted_bytes_ratio=row["accepted_bytes_ratio"], hbm_energy_ratio=row["hbm_energy_ratio"]))
    return rows


def derived(summary):
    rows = [{key: row[key] for key in sorted(row)} for row in summary["threshold_comparison"]]
    return dict(tables.export_rows(summary),
                **{"threshold_comparison.csv": tables.csv_bytes(rows)})


def package(output, report_path, previous_path, core_path):
    if output.exists():
        raise ValueError("fresh threshold-follow-up directory required")
    report, previous = (json.loads(p.read_text()) for p in (report_path, previous_path))
    identity = dict(source_report=str(report_path), source_report_sha256=sha256_file(report_path))
    files = {"previous/results.json": previous_path}
    for directory in (report_path.parent, core_path.parent):
        for path in directory.rglob("*"):
            if not path.is_file() or "build" in path.relative_to(directory).parts:
                continue
            if path.is_symlink():
                raise ValueError("symlink evidence rejected")
            if path.suffix in (".json", ".csv", ".txt", ".gz", ".u32le"):
                files[directory.name + "/" + str(path.relative_to(directory))] = path
    read = lambda name: files[name].read_bytes()
    comparisons = validation.selection(report, identity, expected=EXPECTED)
    validation.validate_raw(comparisons, read, expected=EXPECTED)
    validation.core_gates(json.loads(core_path.read_text()), report, read, core_path.parent.name + "/")
    summary = dict(status="COMPLETE_FIXED_EPSILON_RES_PR_DIAGNOSTIC", baseline_admitted=False,
        model=report["model"], comparisons=comparisons, threshold_comparison=compare(report, previous, read),
        previous_report_sha256=sha256_file(previous_path),
        core_tests=dict(path=str(core_path), sha256=sha256_file(core_path)),
        scope="Resident device prediction only; zero-active cases are not evidence of general propagation speedup")
    (output / "data").mkdir(parents=True)
    (output / "evidence").mkdir()
    atomic_write_json(output / "data/summary.json", summary)
    for name, blob in derived(summary).items():
        (output / "data" / name).write_bytes(blob)
    files.update({"data/" + p.name: p for p in (output / "data").iterdir()})
    archive = output / "evidence/evidence.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in sorted(files.items()):
            handle.add(path, arcname=name, recursive=False)
    atomic_write_json(output / "evidence/index.json", dict(status=summary["status"],
        archive=archive.name, sha256=sha256_file(archive),
        external="Full graph/update inputs, compiler/SST/DRAMSim3 and linked binaries are external pinned dependencies; complete output states, sources and raw records are archived.",
        members=[dict(path=n, bytes=p.stat().st_size, sha256=sha256_file(p)) for n, p in sorted(files.items())]))
    return verify(output)


def verify(output):
    index = json.loads((output / "evidence/index.json").read_text())
    archive = output / "evidence" / index["archive"]
    if index["archive"] != "evidence.tar.gz" or sha256_file(archive) != index["sha256"]:
        raise ValueError("threshold archive identity changed")
    with tarfile.open(archive) as handle:
        read = delivery.checked_archive(handle, index)
        summary = json.loads(read("data/summary.json"))
        if (summary["status"] != index["status"] or summary["baseline_admitted"] is not False or
                (output / "data/summary.json").read_bytes() != read("data/summary.json")):
            raise ValueError("threshold diagnostic summary changed")
        for name, blob in derived(summary).items():
            if read("data/" + name) != blob or (output / "data" / name).read_bytes() != blob:
                raise ValueError("threshold table differs from frozen comparisons")
        validation.validate_raw(summary["comparisons"], read, expected=EXPECTED)
        prefix = Path(summary["comparisons"][0]["source_report"]).parent.name + "/"
        report = json.loads(read(prefix + "results.json"))
        previous_blob = read("previous/results.json")
        if hashlib.sha256(previous_blob).hexdigest() != summary["previous_report_sha256"]:
            raise ValueError("strict-threshold reference identity changed")
        if compare(report, json.loads(previous_blob), read) != summary["threshold_comparison"]:
            raise ValueError("threshold effect or work classification changed")
        core_prefix = Path(summary["core_tests"]["path"]).parent.name + "/"
        core_blob = read(core_prefix + "results.json")
        if hashlib.sha256(core_blob).hexdigest() != summary["core_tests"]["sha256"]:
            raise ValueError("core regression identity changed")
        validation.core_gates(json.loads(core_blob), report, read, core_prefix)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    for name in ("report", "previous", "core-tests"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if not args.verify and any(v is None for v in (args.report, args.previous, args.core_tests)):
        parser.error("packaging requires --report, --previous and --core-tests")
    result = verify(args.output) if args.verify else package(
        args.output, args.report, args.previous, args.core_tests)
    print(json.dumps(dict(status=result["status"], archive_sha256=result["sha256"])))
