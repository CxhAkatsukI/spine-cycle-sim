"""Freeze the complete credit matrix, raw controls and deduplicated state evidence."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from ..analysis import parse_demo
from .analysis import MATRIX, summarize

STATUS = "R_CREDIT_SENSITIVITY_COMPLETE_NOT_BASELINE_ADMISSION"
CLAIMS = ("strict_resource_match_admitted", "hardware_timing_admitted",
          "publication_match_admitted", "production_baseline_admitted",
          "new_spine_comparison_executed")


def validate(report, reference, read, blobs):
    if (report["status"] != STATUS or report["failures"] or
            report.get("pins_unchanged") is not True or
            report.get("production_baseline_admitted") is not False):
        raise ValueError("complete unpromoted credit study required")
    analysis = summarize(report["r_rows"], reference["r_rows"])
    if analysis != report["analysis"] or report["matrix"] != [list(case) for case in MATRIX]:
        raise ValueError("declared matrix or analysis changed")
    expected = ["compiler", "configure", "build", "control_test", "regression"] + [
        f"r_lat{latency}_reverse{reverse}_{arm}" for latency, reverse, arm in MATRIX]
    if len(report["steps"]) != len(expected):
        raise ValueError("complete command records required")
    steps = {}
    for label, step in zip(expected, report["steps"]):
        if (step["exit_code"] or step["timed_out"] or
                json.loads(read("raw/" + label + ".resources.json")) != step):
            raise ValueError("failed or changed command record")
        for stream in ("stdout", "stderr"):
            if Path(step[stream]).name != label + "." + stream + ".txt":
                raise ValueError("raw command log identity differs")
            read("raw/" + Path(step[stream]).name)
        steps[label] = step
    expected_states = set()
    for row in report["r_rows"]:
        label = f"r_lat{row['latency']}_reverse{row['reverse']}_{row['arm']}"
        if parse_demo(read("raw/" + label + ".stdout.txt").decode()) != row["observations"]:
            raise ValueError("raw numerical output differs from observations")
        command = steps[label]["command"]
        if command[-4:] != [str(row["latency"]), str(row["reverse"]),
                             str(report["maximum_cycles"]), row["arm"]]:
            raise ValueError("executed case identity differs from matrix")
        for state in row["outputs"]:
            name = "states/" + label + "/" + state["name"]
            expected_states.add(name)
            blob = blobs[name]
            if (blob["sha256"], blob["bytes"]) != (state["sha256"], state["bytes"]):
                raise ValueError("full state evidence differs from reported replica")
    if {name for name in blobs if name.startswith("states/")} != expected_states:
        raise ValueError("state evidence membership differs from matrix")
    return analysis


def package(output: Path, attempt: Path):
    report = json.loads((attempt / "results.json").read_text())
    before = Path(next(pin["path"] for pin in report["pins"]
                       if pin["path"].endswith("/freeze.json"))).parent
    frozen = json.loads((before / "freeze.json").read_text())
    if frozen["status"] != "PRE_EXTRACTION_FROZEN":
        raise ValueError("pre-extraction reference required")
    for pin in report["pins"] + frozen["artifacts"] + frozen["external"]:
        path = Path(pin["path"])
        if path.stat().st_size != pin["bytes"] or sha256_file(path) != pin["sha256"]:
            raise ValueError("pinned source/input/binary changed before delivery")
    files = {"results.json": attempt / "results.json", "sources.tar.gz": attempt / "sources.tar.gz"}
    for folder, prefix in ((attempt / "raw", "raw"), (before, "pre_edit")):
        files.update({prefix + "/" + path.name: path for path in sorted(folder.iterdir()) if path.is_file()})
    for name in ("CMakeCache.txt", "compile_commands.json"):
        files["build/" + name] = attempt / "build" / name
    blobs = {}
    for folder in (attempt / "inputs", attempt / "states"):
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            digest = sha256_file(path)
            member = "blobs/" + digest
            files.setdefault(member, path)
            blobs[path.relative_to(attempt).as_posix()] = {
                "member": member, "sha256": digest, "bytes": path.stat().st_size}
    validate(report, json.loads((before / "reference.json").read_text()),
             lambda name: files[name].read_bytes(), blobs)
    if any(path.is_symlink() for path in files.values()):
        raise ValueError("symlink evidence is not accepted")
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "evidence.tar.gz"
    members = []
    with tarfile.open(archive, "w:gz") as handle:
        for name, path in sorted(files.items()):
            handle.add(path, arcname=name, recursive=False)
            members.append({"path": name, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    index = {"status": STATUS, "source_attempt": str(attempt), "archive": archive.name,
             "sha256": sha256_file(archive), "members": members, "blobs": blobs,
             "rows": len(MATRIX), "analysis": report["analysis"], **dict.fromkeys(CLAIMS, False),
             "boundary": report["boundary"],
             "omitted": "Compiled executables/libraries are hash-indexed, not redistributed; sources, compiler/flags, inputs and all final states are included."}
    atomic_write_json(output / "index.json", index)
    return verify(output)


def verify(output: Path):
    index = json.loads((output / "index.json").read_text())
    if index["status"] != STATUS or index["rows"] != 28 or any(
            index.get(key) is not False for key in CLAIMS):
        raise ValueError("invalid sensitivity-only claim")
    archive = output / index["archive"]
    if archive.parent != output or sha256_file(archive) != index["sha256"]:
        raise ValueError("archive identity changed")
    with tarfile.open(archive) as handle:
        names = [row["path"] for row in index["members"]]
        if (len(names) != len(set(names)) or sorted(handle.getnames()) != sorted(names) or
                any(PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts for name in names)):
            raise ValueError("invalid archive membership")

        def read(name):
            member = handle.getmember(name)
            if not member.isfile():
                raise ValueError("non-file archive member")
            return handle.extractfile(member).read()

        hashes = {}
        for row in index["members"]:
            value = read(row["path"])
            actual = (hashlib.sha256(value).hexdigest(), len(value))
            if actual != (row["sha256"], row["bytes"]):
                raise ValueError("archive member changed")
            hashes[row["path"]] = actual
        for blob in index["blobs"].values():
            if hashes.get(blob["member"]) != (blob["sha256"], blob["bytes"]):
                raise ValueError("input or state blob identity changed")
        report = json.loads(read("results.json"))
        analysis = validate(report, json.loads(read("pre_edit/reference.json")), read, index["blobs"])
        for pin in report["pins"]:
            path = Path(pin["path"])
            if "inputs" not in path.parts:
                continue
            name = path.relative_to(Path(index["source_attempt"])).as_posix()
            blob = index["blobs"][name]
            if (blob["sha256"], blob["bytes"]) != (pin["sha256"], pin["bytes"]):
                raise ValueError("input identity differs from frozen pin")
        if analysis != index["analysis"] or index["boundary"] != report["boundary"]:
            raise ValueError("index analysis or timing boundary changed")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt", type=Path)
    args = parser.parse_args()
    result = (package(args.output.resolve(), args.attempt.resolve()) if args.attempt
              else verify(args.output.resolve()))
    print(json.dumps({"status": result["status"], "rows": result["rows"]}))
