"""Deliver the extension beside, never over, the preceding frozen figure data."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .. import delivery as legacy_delivery
from . import tables, validation


def checked_archive(handle, index):
    members = {m["path"]: m for m in index["members"]}
    if len(members) != len(index["members"]) or sorted(handle.getnames()) != sorted(members):
        raise ValueError("archive membership changed or duplicated")

    def read(name):
        path = PurePosixPath(name)
        member = handle.getmember(name)
        if path.is_absolute() or ".." in path.parts or not member.isfile():
            raise ValueError("unsafe evidence member")
        blob = handle.extractfile(member).read()
        if (len(blob), hashlib.sha256(blob).hexdigest()) != (members[name]["bytes"], members[name]["sha256"]):
            raise ValueError("evidence member identity changed")
        return blob
    for name in members:
        read(name)
    return read


def package(output, report_path, attempts, legacy, before, after, core_tests):
    if output.exists():
        raise ValueError("fresh extension output directory required")
    report = json.loads(report_path.read_text())
    identity = dict(source_report=str(report_path), source_report_sha256=sha256_file(report_path))
    comparisons = validation.selection(report, identity)
    legacy_delivery.verify(legacy)
    prior = json.loads((legacy / "data/summary.json").read_text())
    retained = [r for r in prior["comparisons"] if r["figure"] == 9]
    if {(r["algorithm"], r["dataset"]) for r in retained} != {("SSSP", d) for d in ("AU", "SU", "WK")}:
        raise ValueError("three pinned SSSP rows required, not historical missing CC/PR")
    replay = legacy_delivery.equivalence(before, after)
    with tarfile.open(legacy / "evidence/evidence.tar.gz") as handle:
        read = checked_archive(handle, json.loads((legacy / "evidence/index.json").read_text()))
        retained_energy = {r["dataset"]: {arm: validation.energy_details(read,
            Path(r["source_report"]).parent.name + "/" + Path(r[arm]["evidence"]).name)
            for arm in ("spine", "gr")} for r in retained}
    summary = dict(status="COMPLETE_NINE_PAIR_SIMULATOR_DIAGNOSTIC", baseline_admitted=False,
        fresh_pairs=6, retained_sssp_pairs=3, figure9_pairs=9, comparisons=comparisons,
        retained_sssp=retained, retained_energy_details=retained_energy,
        model=report["model"], sssp_regression=replay,
        core_tests=dict(path=str(core_tests), sha256=sha256_file(core_tests)),
        original_r_control=dict(status="NOT_ADMITTED_FOR_CC_OR_RES_PR",
            reason="Original source-derived control has fixed-point full PR and a local weighted-SSSP UDF, not CC or warm FP32 residual PR; SSSP timing parity is not transferred."),
        legacy_archive_sha256=sha256_file(legacy / "evidence/evidence.tar.gz"))
    output.mkdir(parents=True)
    (output / "data").mkdir()
    (output / "evidence").mkdir()
    atomic_write_json(output / "data/summary.json", summary)
    for name, blob in tables.export_rows(summary).items():
        (output / "data" / name).write_bytes(blob)
    files = {"legacy/evidence.tar.gz": legacy / "evidence/evidence.tar.gz",
             "legacy/index.json": legacy / "evidence/index.json", "pre_extension/results.json": before}
    indexed = []
    for directory in sorted(p for p in attempts.iterdir() if p.is_dir()):
        result_path = directory / "results.json"
        result = json.loads(result_path.read_text()) if result_path.exists() else {}
        if result.get("status", "").startswith("RUNNING"):
            raise ValueError("running attempts cannot be packaged")
        indexed.append(dict(path=str(directory), status=result.get("status", "BUILD_OR_TEST_RECORD"),
                            failures=result.get("failures", [])))
        for path in directory.rglob("*"):
            if not path.is_file() or "build" in path.relative_to(directory).parts:
                continue
            if path.is_symlink():
                raise ValueError("symlink evidence rejected")
            if path.suffix in (".json", ".csv", ".txt", ".gz", ".u32le"):
                files[directory.name + "/" + str(path.relative_to(directory))] = path
    if after.parent.name + "/results.json" not in files:
        raise ValueError("post-extension SSSP replay must be archived")
    if core_tests.parent.name + "/results.json" not in files:
        raise ValueError("full core regression report must be archived")
    for path in (output / "data").iterdir():
        files["data/" + path.name] = path
    validation.validate_raw(comparisons, lambda name: files[name].read_bytes())
    validation.core_gates(json.loads(core_tests.read_text()), report,
        lambda name: files[name].read_bytes(), core_tests.parent.name + "/")
    archive = output / "evidence/evidence.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in sorted(files.items()):
            handle.add(path, arcname=name, recursive=False)
    index = dict(status=summary["status"], baseline_admitted=False, archive=archive.name,
        sha256=sha256_file(archive), attempts=indexed,
        members=[dict(path=n, bytes=p.stat().st_size, sha256=sha256_file(p)) for n, p in sorted(files.items())],
        external="Full graph/update inputs, compiler/SST/DRAMSim3 and linked binaries are external pinned dependencies; full output states, logs, sources and memory reports are archived.")
    atomic_write_json(output / "evidence/index.json", index)
    return verify(output)


def verify(output):
    index = json.loads((output / "evidence/index.json").read_text())
    archive = output / "evidence/evidence.tar.gz"
    if index["archive"] != archive.name or sha256_file(archive) != index["sha256"]:
        raise ValueError("extension archive changed")
    with tarfile.open(archive) as handle:
        read = checked_archive(handle, index)
        summary = json.loads(read("data/summary.json"))
        if summary["baseline_admitted"] is not False or summary["status"] != index["status"]:
            raise ValueError("exploratory evidence boundary changed")
        for name, blob in tables.export_rows(summary).items():
            if read("data/" + name) != blob or (output / "data" / name).read_bytes() != blob:
                raise ValueError("derived table differs from frozen comparisons")
        if (output / "data/summary.json").read_bytes() != read("data/summary.json"):
            raise ValueError("exported summary changed")
        validation.validate_raw(summary["comparisons"], read)
        core_prefix = Path(summary["core_tests"]["path"]).parent.name + "/"
        core_blob = read(core_prefix + "results.json")
        if hashlib.sha256(core_blob).hexdigest() != summary["core_tests"]["sha256"]:
            raise ValueError("core regression report identity differs")
        matrix_report = json.loads(read(Path(summary["comparisons"][0]["source_report"]).parent.name + "/results.json"))
        validation.core_gates(json.loads(core_blob), matrix_report, read, core_prefix)
        prior_archive = read("legacy/evidence.tar.gz")
        if hashlib.sha256(prior_archive).hexdigest() != summary["legacy_archive_sha256"]:
            raise ValueError("retained SSSP archive differs")
        with tarfile.open(fileobj=io.BytesIO(prior_archive)) as prior_handle:
            prior_read = checked_archive(prior_handle, json.loads(read("legacy/index.json")))
            prior_summary = json.loads(prior_read("data/summary.json"))
            if [r for r in prior_summary["comparisons"] if r["figure"] == 9] != summary["retained_sssp"]:
                raise ValueError("SSSP rows differ from preceding pinned delivery")
            legacy_delivery.validate_raw(dict(comparisons=summary["retained_sssp"]), prior_read)
            for row in summary["retained_sssp"]:
                for arm in ("spine", "gr"):
                    directory = Path(row["source_report"]).parent.name + "/" + Path(row[arm]["evidence"]).name
                    if validation.energy_details(prior_read, directory) != summary["retained_energy_details"][row["dataset"]][arm]:
                        raise ValueError("retained SSSP energy components differ")
        replay = summary["sssp_regression"]
        old_blob = read("pre_extension/results.json")
        new_blob = read(Path(replay["after"]["path"]).parent.name + "/results.json")
        if any(hashlib.sha256(blob).hexdigest() != replay[key]["sha256"]
               for key, blob in (("before", old_blob), ("after", new_blob))):
            raise ValueError("SSSP regression evidence identity differs")
        old = json.loads(old_blob)
        new = json.loads(new_blob)
        key = lambda r: (r["workload"], r["latency"], r["arm"], r["reverse"])
        previous = {key(r): r for r in old["rows"]}
        if len(previous) != 12 or len(new["rows"]) != 12 or not new["pins_unchanged"] or new["failures"]:
            raise ValueError("complete SSSP replay required")
        for row in new["rows"]:
            if any(row[k] != previous[key(row)][k] for k in ("input", "result", "state_hashes")):
                raise ValueError("SSSP replay changed numerical result")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    for name in ("report", "attempts", "legacy", "before", "after", "core-tests"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if not args.verify and any(getattr(args, k) is None for k in ("report", "attempts", "legacy", "before", "after", "core_tests")):
        parser.error("packaging requires all six source paths")
    result = verify(args.output) if args.verify else package(args.output, args.report, args.attempts,
                                                           args.legacy, args.before, args.after, args.core_tests)
    print(json.dumps(dict(status=result["status"], archive_sha256=result["sha256"])))
