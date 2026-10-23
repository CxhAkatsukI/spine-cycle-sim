"""Portable same-batch A4 evidence, including the common-warm reference matrix."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ...original_regraph_inputs.analysis import records
from .a4_analysis import summarize
from .delivery import validate as validate_warm

STATUS = "COMPLETE_SAME_BATCH_A4_PREDICTION"


def validate(report, read, states, warm_states):
    if (report["status"] != STATUS or report["pins_unchanged"] is not True or
            report["failures"] or report["host_time_included"] is not False or
            report["baseline_admitted"] is not False or len(report["steps"]) != 14):
        raise ValueError("complete same-batch device prediction required")
    warm = json.loads(read("warm/results.json"))
    validate_warm(warm, lambda name: read("warm/" + name), warm_states)
    if warm["rows"] != report["warm_rows"]:
        raise ValueError("common-warm reference differs")
    for step in report["steps"]:
        label = Path(step["stdout"]).name.removesuffix(".stdout.txt")
        if (step["exit_code"] or step["timed_out"] or
                json.loads(read("raw/" + label + ".resources.json")) != step):
            raise ValueError("failed or changed command record")
        read("raw/" + label + ".stdout.txt"); read("raw/" + label + ".stderr.txt")
    expected = set()
    for row in report["rows"]:
        label = f"{row['workload']}_lat{row['latency']}_a4_order{row['reverse']}"
        text = read("raw/" + label + ".stdout.txt").decode()
        if (records(text, "WARM_INPUT ") != [row["input"]] or
                records(text, "DEMO_RESULT ") != [row["result"]] or
                records(text, "DEMO_ROUND ") != row["rounds"] or
                json.loads(read("raw/" + label + ".resources.json")) != row["resources"]):
            raise ValueError("A4 raw input/result/rounds changed")
        result = row["result"]
        if (result["passed"] is not True or result["arm"] != "a4_io16" or result["cycles"] <= 0 or
                result["replicas"] != 4 or len(row["replica_hashes"]) != 4 or
                len(set(row["replica_hashes"])) != 1 or
                result["rounds"] != len(row["rounds"]) or
                result["rounds"] != row["input"]["oracle_rounds"] or
                [r["round"] for r in row["rounds"]] != list(range(result["rounds"])) or
                sum(r["cycles"] for r in row["rounds"]) != result["cycles"] or
                any(r["arm"] != "a4_io16" or r["cycles"] <= 0 for r in row["rounds"]) or
                row["rounds"][-1]["active"] != 0 or
                row["state_hashes"]["expected"] != row["state_hashes"]["final"]):
            raise ValueError("A4 full convergence required")
        for name, digest in row["state_hashes"].items():
            key = label + "/" + name + ".u32le"
            expected.add(key)
            if states[key]["sha256"] != digest or states[key]["bytes"] != row["input"]["vertices"] * 4:
                raise ValueError("A4 full state identity differs")
        aligned = (row["input"]["vertices"] + 65535) // 65536 * 65536
        for copy, digest in enumerate(row["replica_hashes"]):
            key = label + f"/replica{copy}.u32le"
            expected.add(key)
            if states[key]["sha256"] != digest or states[key]["bytes"] != aligned * 4:
                raise ValueError("A4 full replica identity differs")
    comparisons = summarize(report["rows"], report["warm_rows"])
    if set(states) != expected or comparisons != report["comparisons"]:
        raise ValueError("A4 state membership or comparison changed")
    return comparisons


def package(output, attempt, comparison):
    report = json.loads((attempt / "results.json").read_text())
    for item in report["pins"]:
        path = Path(item["path"])
        if path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError("pinned artifact changed before delivery")
    files = {}
    for name in ("results.json", "harness_sources.tar.gz", "admission.json", "live_memory.json"):
        files[name] = attempt / name
    files.update({"raw/" + p.name: p for p in (attempt / "raw").iterdir() if p.is_file()})
    for workload in ("smoke", "amazon"):
        for suffix in ("_input", "_layout"):
            files.update({workload + suffix + "/" + p.name: p
                          for p in (attempt / (workload + suffix)).iterdir() if p.is_file()})
    warm = json.loads(comparison.read_text())
    files["warm/results.json"] = comparison
    files.update({"warm/raw/" + p.name: p for p in (comparison.parent / "raw").iterdir() if p.is_file()})
    def collect(rows, base, original):
        states = {}
        for row in rows:
            arm = row["arm"] if original else "a4"
            label = f"{row['workload']}_lat{row['latency']}_{arm}_order{row['reverse']}"
            for path in (base / label).glob("*.u32le"):
                digest = sha256_file(path)
                member = "blobs/" + digest
                files.setdefault(member, path)
                states[label + "/" + path.name] = dict(member=member, sha256=digest, bytes=path.stat().st_size)
        return states
    states = collect(report["rows"], attempt, False)
    warm_states = collect(warm["rows"], comparison.parent, True)
    failures = []
    for previous in sorted(attempt.parent.glob("attempt-v*")):
        if previous == attempt:
            continue
        old = json.loads((previous / "results.json").read_text())
        if old["status"] != "FAILED_RETAINED":
            raise ValueError("unaccounted sibling attempt")
        failures.append(dict(path=str(previous), failures=old["failures"]))
        files["failures/" + previous.name + "/results.json"] = previous / "results.json"
        files.update({"failures/" + previous.name + "/raw/" + p.name: p
                      for p in (previous / "raw").iterdir() if p.is_file()})
    validate(report, lambda name: files[name].read_bytes(), states, warm_states)
    if any(p.is_symlink() for p in files.values()):
        raise ValueError("regular evidence files required")
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "evidence.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in sorted(files.items()):
            handle.add(path, arcname=name, recursive=False)
    atomic_write_json(output / "index.json", dict(status=STATUS, archive=archive.name,
        sha256=sha256_file(archive), source_attempt=str(attempt), comparisons=report["comparisons"],
        states=states, warm_states=warm_states, failures=failures,
        members=[dict(path=name, sha256=sha256_file(p), bytes=p.stat().st_size) for name, p in sorted(files.items())],
        baseline_admitted=False, host_time_included=False,
        external="Compiler, core libraries and pinned upstream checkout remain machine-local; new compact layouts, common states, raw records and harness snapshot are included."))
    return verify(output)


def verify(output):
    index = json.loads((output / "index.json").read_text())
    if (index["status"] != STATUS or index["baseline_admitted"] is not False or
            index["host_time_included"] is not False or index["archive"] != "evidence.tar.gz" or
            sha256_file(output / index["archive"]) != index["sha256"]):
        raise ValueError("capsule identity changed")
    with tarfile.open(output / index["archive"]) as handle:
        names = [row["path"] for row in index["members"]]
        if (len(set(names)) != len(names) or sorted(handle.getnames()) != sorted(names) or
                any(PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts for n in names)):
            raise ValueError("invalid archive membership")
        def read(name):
            if not handle.getmember(name).isfile():
                raise ValueError("regular file required")
            return handle.extractfile(name).read()
        hashes = {}
        for item in index["members"]:
            value = read(item["path"])
            hashes[item["path"]] = hashlib.sha256(value).hexdigest(), len(value)
            if hashes[item["path"]] != (item["sha256"], item["bytes"]):
                raise ValueError("archive member changed")
        for blob in (*index["states"].values(), *index["warm_states"].values()):
            if hashes.get(blob["member"]) != (blob["sha256"], blob["bytes"]):
                raise ValueError("full state blob changed")
        result = validate(json.loads(read("results.json")), read, index["states"], index["warm_states"])
        if result != index["comparisons"]:
            raise ValueError("index comparison changed")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path)
    parser.add_argument("--comparison", type=Path)
    args = parser.parse_args()
    if bool(args.attempt) != bool(args.comparison):
        parser.error("packaging requires both --attempt and --comparison")
    result = package(args.output, args.attempt, args.comparison) if args.attempt else verify(args.output)
    print(json.dumps(dict(status=result["status"], comparisons=result["comparisons"])))
