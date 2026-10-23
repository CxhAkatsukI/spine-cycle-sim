"""Freeze partial-host samples; require the independently verified warm-device capsule."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from . import delivery as device_delivery
from . import host_analysis as analysis


def warm_rows(directory):
    index = device_delivery.verify(directory)
    with tarfile.open(directory / index["archive"]) as handle:
        return json.loads(handle.extractfile("results.json").read())["rows"]


def package(output, attempt, warm):
    report = json.loads((attempt / "results.json").read_text())
    if report["warm_rows"] != warm_rows(warm):
        raise ValueError("CPU reference differs from verified warm-device capsule")
    for item in report["pins"]:
        path = Path(item["path"])
        if path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError("pinned artifact changed before delivery")
    files = {name: attempt / name for name in ("results.json", "harness_sources.tar.gz",
        "admission.json", "final_memory.json", "smoke.batch.txt", "amazon.batch.txt")}
    if (attempt / "live_memory.json").exists():
        files["live_memory.json"] = attempt / "live_memory.json"
    files.update({"raw/" + p.name: p for p in (attempt / "raw").iterdir() if p.is_file()})
    prior_attempts = []
    for previous in sorted(attempt.parent.glob("attempt-v*")):
        if previous == attempt:
            continue
        old = json.loads((previous / "results.json").read_text())
        if old["status"] not in ("FAILED_RETAINED", analysis.STATUS):
            raise ValueError("unaccounted sibling attempt")
        prior_attempts.append(dict(path=str(previous), status=old["status"], failures=old["failures"]))
        files.update({"prior_attempts/" + previous.name + "/" + str(p.relative_to(previous)): p
                      for p in previous.rglob("*") if p.is_file() and "build" not in p.relative_to(previous).parts})
    analysis.validate(report, lambda name: files[name].read_bytes())
    if any(path.is_symlink() for path in files.values()):
        raise ValueError("regular evidence files required")
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "evidence.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in sorted(files.items()):
            handle.add(path, arcname=name, recursive=False)
    atomic_write_json(output / "index.json", dict(status=analysis.STATUS, archive=archive.name,
        sha256=sha256_file(archive), source_attempt=str(attempt), prior_attempts=prior_attempts,
        warm_index_sha256=sha256_file(warm / "index.json"), comparisons=report["comparisons"],
        baseline_admitted=False, full_host_time_included=False,
        members=[dict(path=name, sha256=sha256_file(p), bytes=p.stat().st_size) for name, p in sorted(files.items())],
        external="Requires the unchanged adjacent warm-device capsule; compiler and numerical libraries remain hash-indexed, not redistributed."))
    return verify(output, warm)


def verify(output, warm):
    index = json.loads((output / "index.json").read_text())
    if (index["status"] != analysis.STATUS or index["full_host_time_included"] is not False or
            index["baseline_admitted"] is not False or index["archive"] != "evidence.tar.gz" or
            sha256_file(output / index["archive"]) != index["sha256"] or
            sha256_file(warm / "index.json") != index["warm_index_sha256"]):
        raise ValueError("partial-host capsule or warm-reference identity changed")
    expected_warm = warm_rows(warm)
    with tarfile.open(output / index["archive"]) as handle:
        names = [item["path"] for item in index["members"]]
        if (len(set(names)) != len(names) or sorted(names) != sorted(handle.getnames()) or
                any(PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts for n in names)):
            raise ValueError("invalid archive membership")
        def read(name):
            if not handle.getmember(name).isfile():
                raise ValueError("regular archive member required")
            return handle.extractfile(name).read()
        for item in index["members"]:
            value = read(item["path"])
            if (hashlib.sha256(value).hexdigest(), len(value)) != (item["sha256"], item["bytes"]):
                raise ValueError("CPU evidence member changed")
        report = json.loads(read("results.json"))
        if (report["warm_rows"] != expected_warm or
                analysis.validate(report, read) != index["comparisons"]):
            raise ValueError("partial-host comparisons or full-state reference changed")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warm-evidence", type=Path, required=True)
    parser.add_argument("--attempt", type=Path)
    args = parser.parse_args()
    result = (package(args.output, args.attempt, args.warm_evidence) if args.attempt
              else verify(args.output, args.warm_evidence))
    print(json.dumps(dict(status=result["status"], comparisons=result["comparisons"])))
