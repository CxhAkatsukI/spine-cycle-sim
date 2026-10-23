"""Freeze and independently check the exploratory matrix without local raw paths."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from .analysis import summarize

STATUS = "COMPLETE_EXPLORATORY_DEVICE_PREDICTION"


def validate(report, read, states):
    if (report.get("status") != STATUS or report.get("pins_unchanged") is not True or
            report.get("failures") != [] or report.get("baseline_admitted") is not False or
            report.get("host_time_included") is not False):
        raise ValueError("complete exploratory device prediction required")
    if len(report["rows"]) != 12 or len(report["steps"]) != 13:
        raise ValueError("complete matrix and build evidence required")
    for step in report["steps"]:
        label = Path(step["stdout"]).name.removesuffix(".stdout.txt")
        if (step["exit_code"] or step["timed_out"] or
                json.loads(read("raw/" + label + ".resources.json")) != step):
            raise ValueError("failed or changed command record")
        read("raw/" + label + ".stdout.txt")
        read("raw/" + label + ".stderr.txt")
    expected_states = set()
    for row in report["rows"]:
        label = f"{row['workload']}_lat{row['latency']}_{row['arm']}_order{row['reverse']}"
        stdout = read("raw/" + label + ".stdout.txt").decode().splitlines()
        for prefix, expected in (("WARM_INPUT ", row["input"]), ("WARM_RESULT ", row["result"])):
            parsed = [json.loads(line[len(prefix):]) for line in stdout if line.startswith(prefix)]
            if parsed != [expected]:
                raise ValueError("raw input/result differs from matrix")
        result = row["result"]
        if (result["arm"] != row["arm"] or result["correctness"] is not True or
                result["ledger_closed"] is not True or result["cycles"] <= 0 or
                row["state_hashes"]["expected"] != row["state_hashes"]["final"]):
            raise ValueError("correctness and drained ledger required")
        if row["arm"] == "gr" and (result["physical_handoff"] is not True or
                result["cycles"] != result["g_cycles"] + result["r_cycles"] + result["handoff_cycle_gap"]):
            raise ValueError("complete physical G-to-R window required")
        if row["resources"] != json.loads(read("raw/" + label + ".resources.json")):
            raise ValueError("row execution identity differs from raw record")
        for name, digest in row["state_hashes"].items():
            key = label + "/" + name + ".u32le"
            expected_states.add(key)
            blob = states[key]
            if (blob["sha256"] != digest or blob["bytes"] != row["input"]["vertices"] * 4):
                raise ValueError("complete state identity or size differs")
    if set(states) != expected_states or summarize(report["rows"]) != report["comparisons"]:
        raise ValueError("matrix state membership or comparison changed")
    return report["comparisons"]


def package(output, attempt):
    report = json.loads((attempt / "results.json").read_text())
    for pin in report["pins"]:
        path = Path(pin["path"])
        if path.stat().st_size != pin["bytes"] or sha256_file(path) != pin["sha256"]:
            raise ValueError("pinned source, binary or input changed before delivery")
    files = {"results.json": attempt / "results.json",
             "harness_sources.tar.gz": attempt / "harness_sources.tar.gz"}
    for name in ("admission.json", "live_memory.json"):
        files[name] = attempt / name
    files.update({"raw/" + p.name: p for p in (attempt / "raw").iterdir() if p.is_file()})
    states = {}
    for row in report["rows"]:
        label = f"{row['workload']}_lat{row['latency']}_{row['arm']}_order{row['reverse']}"
        for path in (attempt / label).iterdir():
            if path.suffix == ".csv":
                files[label + "/" + path.name] = path
            elif path.suffix == ".u32le":
                digest = sha256_file(path)
                member = "blobs/" + digest
                files.setdefault(member, path)
                states[label + "/" + path.name] = dict(
                    member=member, sha256=digest, bytes=path.stat().st_size)
    failures = []
    for previous in sorted(attempt.parent.glob("attempt-v*")):
        if previous == attempt:
            continue
        earlier = json.loads((previous / "results.json").read_text())
        if earlier["status"] != "FAILED_RETAINED":
            raise ValueError("all sibling attempts must be explicitly accounted for")
        failures.append(dict(path=str(previous), failures=earlier["failures"]))
        files["failures/" + previous.name + "/results.json"] = previous / "results.json"
        files.update({"failures/" + previous.name + "/raw/" + p.name: p
                      for p in (previous / "raw").iterdir() if p.is_file()})
    validate(report, lambda name: files[name].read_bytes(), states)
    if any(path.is_symlink() for path in files.values()):
        raise ValueError("symlink evidence is not accepted")
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "evidence.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in sorted(files.items()):
            handle.add(path, arcname=name, recursive=False)
    atomic_write_json(output / "index.json", dict(status=STATUS, source_attempt=str(attempt),
        archive=archive.name, sha256=sha256_file(archive), states=states, failures=failures,
        members=[dict(path=name, sha256=sha256_file(path), bytes=path.stat().st_size)
                 for name, path in sorted(files.items())],
        comparisons=report["comparisons"], baseline_admitted=False, host_time_included=False,
        external="Original graph/input, core libraries and compiler remain hash-indexed in results.json; all full output states, source snapshot, command logs and five failed-attempt reports/logs are included."))
    return verify(output)


def verify(output):
    index = json.loads((output / "index.json").read_text())
    if (index["status"] != STATUS or index["baseline_admitted"] is not False or
            index["host_time_included"] is not False or index["archive"] != "evidence.tar.gz" or
            sha256_file(output / index["archive"]) != index["sha256"]):
        raise ValueError("exploratory capsule identity changed")
    with tarfile.open(output / index["archive"]) as handle:
        names = [row["path"] for row in index["members"]]
        if (len(names) != len(set(names)) or sorted(handle.getnames()) != sorted(names) or
                any(PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts for n in names)):
            raise ValueError("invalid archive membership")

        def read(name):
            if not handle.getmember(name).isfile():
                raise ValueError("regular file evidence required")
            return handle.extractfile(name).read()

        hashes = {}
        for row in index["members"]:
            value = read(row["path"])
            hashes[row["path"]] = (hashlib.sha256(value).hexdigest(), len(value))
            if hashes[row["path"]] != (row["sha256"], row["bytes"]):
                raise ValueError("archive member identity changed")
        for blob in index["states"].values():
            if hashes.get(blob["member"]) != (blob["sha256"], blob["bytes"]):
                raise ValueError("full state blob changed")
        comparisons = validate(json.loads(read("results.json")), read, index["states"])
        if comparisons != index["comparisons"]:
            raise ValueError("index comparison changed")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path)
    args = parser.parse_args()
    result = (package(args.output.resolve(), args.attempt.resolve()) if args.attempt
              else verify(args.output.resolve()))
    print(json.dumps(dict(status=result["status"], comparisons=result["comparisons"])))
