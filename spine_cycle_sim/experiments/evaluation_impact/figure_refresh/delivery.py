"""Package selected data and every attempt; verify without the original raw tree."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from . import tables


def equivalence(before, after):
    old, new = (json.loads(p.read_text()) for p in (before, after))
    key = lambda r: (r["workload"], r["latency"], r["arm"], r["reverse"])
    previous = {key(r): r for r in old["rows"]}
    if (len(previous) != 12 or len(new["rows"]) != 12 or
            new.get("pins_unchanged") is not True or new.get("failures") != []):
        raise ValueError("complete unchanged twelve-execution replay required")
    for row in new["rows"]:
        for field in ("input", "result", "state_hashes"):
            if row[field] != previous[key(row)][field]:
                raise ValueError("harness extraction changed " + field)
    return dict(status="EXACT_TWELVE_EXECUTION_REPLAY", fields=["input", "result", "state_hashes"],
        before=dict(path=str(before), sha256=sha256_file(before)),
        after=dict(path=str(after), sha256=sha256_file(after)))


def validate_raw(summary, read):
    """Reconcile exported arms with independent archived logs and memory ledgers."""
    for row in summary["comparisons"]:
        attempt = Path(row["source_report"]).parent.name
        report = json.loads(read(attempt + "/results.json"))
        if (hashlib.sha256(read(attempt + "/results.json")).hexdigest() != row["source_report_sha256"]
                or report.get("pins_unchanged") is not True):
            raise ValueError("selected report identity changed")
        for arm in ("spine", "gr"):
            expected = row[arm]
            label = Path(expected["evidence"]).name
            prefix = attempt + "/"
            steps = [s for s in report["steps"] if Path(s["stdout"]).name == label + ".stdout.txt"]
            if len(steps) != 1 or steps[0]["exit_code"] or steps[0]["timed_out"]:
                raise ValueError("successful selected device command required")
            if json.loads(read(prefix + "raw/" + label + ".resources.json")) != steps[0]:
                raise ValueError("device command record differs")
            stdout = read(prefix + "raw/" + label + ".stdout.txt").decode()
            raw = [json.loads(s[len("WARM_RESULT "):]) for s in stdout.splitlines() if s.startswith("WARM_RESULT ")]
            if (len(raw) != 1 or "REFRESH_COMPLETE" not in stdout or
                    any(expected.get(k) != v for k, v in raw[0].items()) or
                    raw[0].get("correctness") is not True or raw[0].get("ledger_closed") is not True):
                raise ValueError("selected arm differs from complete raw result")
            config = json.loads(read(prefix + label + "/config.json"))
            if any(config[k] != row["case"][v] for k, v in
                   (("root", "root"), ("graph", "graph"), ("updates", "update_file"))):
                raise ValueError("selected input/source differs from run configuration")
            ledger = json.loads(read(prefix + label + "/backend.json"))
            if (ledger["ledger_closed"] is not True or ledger["pending_intents"] or ledger["pending_grants"] or
                    len({ledger[k] for k in ("unique_intents", "grants", "consumed_grants")}) != 1):
                raise ValueError("undrained physical request ledger")
            energy = 0.0
            for channel in range(32):
                contents = json.loads(read(prefix + label + f"/dram/channel{channel}/dramsim3.json"))
                energy += sum(float(v["total_energy"]) for v in contents.values())
            if energy != expected["energy_pj"]:
                raise ValueError("selected all-channel energy differs")
            if row["figure"] == 8:
                host_label = Path(expected["host"]["evidence"]).name
                host_steps = [s for s in report["steps"] if Path(s["stdout"]).name == host_label + ".stdout.txt"]
                if len(host_steps) != 1 or host_steps[0]["exit_code"] or host_steps[0]["timed_out"]:
                    raise ValueError("successful selected host command required")
                text = read(prefix + "raw/" + host_label + ".stdout.txt").decode()
                samples = [json.loads(s[len("HOST_RESULT "):]) for s in text.splitlines() if s.startswith("HOST_RESULT ")]
                if samples != expected["host"]["samples"] or "REFRESH_COMPLETE" not in text:
                    raise ValueError("host repetitions differ from raw measurements")


def package(output, small, large, propagation, attempts, before, after, historical):
    data = output / "data"
    summary = tables.export(data, small, large, propagation, historical)
    replay = equivalence(before, after)
    atomic_write_json(data / "harness_equivalence.json", replay)
    evidence = output / "evidence"
    evidence.mkdir(exist_ok=False)
    files = {}
    indexed_attempts = []
    for directory in [*sorted(attempts.glob("attempt-v*")), after.parent]:
        report = json.loads((directory / "results.json").read_text())
        if report["status"].startswith("RUNNING"):
            raise ValueError("cannot package running attempt")
        indexed_attempts.append(dict(path=str(directory), status=report["status"], failures=report["failures"]))
        for path in directory.rglob("*"):
            if not path.is_file() or "build" in path.relative_to(directory).parts:
                continue
            if path.is_symlink():
                raise ValueError("symlink evidence is not accepted")
            if path.suffix in (".json", ".csv", ".txt", ".gz", ".u32le"):
                files[directory.name + "/" + str(path.relative_to(directory))] = path
    files["pre_extraction/results.json"] = before
    for path in data.iterdir():
        files["data/" + path.name] = path
    validate_raw(summary, lambda name: files[name].read_bytes())
    for source in summary["source_reports"]:
        report = json.loads(Path(source["path"]).read_text())
        for pin in report["pins"]:
            if pin["path"].endswith("/sources.tar.gz"):
                if sha256_file(Path(pin["path"])) != pin["sha256"]:
                    raise ValueError("frozen source archive changed")
    archive = evidence / "evidence.tar.gz"
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in sorted(files.items()):
            handle.add(path, arcname=name, recursive=False)
    index = dict(status=summary["status"], baseline_admitted=False, archive=archive.name,
        sha256=sha256_file(archive), attempts=indexed_attempts, equivalence=replay,
        members=[dict(path=name, bytes=p.stat().st_size, sha256=sha256_file(p)) for name, p in sorted(files.items())],
        external="Complete graph/update inputs, compiler and numerical libraries are external hash-indexed dependencies in run reports; logs/configurations/DRAM reports/full output states/source snapshots are portable.")
    atomic_write_json(evidence / "index.json", index)
    return verify(output)


def verify(output):
    index = json.loads((output / "evidence/index.json").read_text())
    archive = output / "evidence" / index["archive"]
    if index["archive"] != "evidence.tar.gz" or sha256_file(archive) != index["sha256"]:
        raise ValueError("evidence archive changed")
    with tarfile.open(archive) as handle:
        names = [m["path"] for m in index["members"]]
        if len(names) != len(set(names)) or sorted(handle.getnames()) != sorted(names):
            raise ValueError("duplicate or changed archive membership")
        def read(name):
            member = handle.getmember(name)
            if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts or not member.isfile():
                raise ValueError("unsafe evidence member")
            return handle.extractfile(member).read()
        for member in index["members"]:
            blob = read(member["path"])
            if (len(blob), hashlib.sha256(blob).hexdigest()) != (member["bytes"], member["sha256"]):
                raise ValueError("archive member changed")
            if member["path"].startswith("data/") and (output / member["path"]).read_bytes() != blob:
                raise ValueError("exported table differs from frozen evidence")
        summary = json.loads(read("data/summary.json"))
        if summary["baseline_admitted"] is not False or summary["status"] != index["status"]:
            raise ValueError("prediction scope changed")
        validate_raw(summary, read)
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    for name in ("small", "large", "propagation", "attempts", "before", "after", "historical"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if not args.verify and any(getattr(args, key) is None for key in
            ("small", "large", "propagation", "attempts", "before", "after", "historical")):
        parser.error("packaging requires all seven source paths")
    result = verify(args.output) if args.verify else package(args.output, args.small, args.large,
        args.propagation, args.attempts, args.before, args.after, args.historical)
    print(json.dumps(dict(status=result["status"], archive_sha256=result["sha256"])))
