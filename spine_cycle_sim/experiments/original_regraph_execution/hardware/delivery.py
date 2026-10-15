"""Seal offline original-R evidence, keeping FPGA and publication claims false."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from . import artifact, oracle, study

CLAIMS = ("board_programmed", "board_correctness", "hardware_timing_measured", "publication_match")
CHECKPOINT = "ORIGINAL_R_OFFLINE_AUDIT_CHECKPOINT_NOT_BOARD_ADMISSION"


def terminal(report):
    if report["status"] not in (study.STATUS, "FAILED_RETAINED") or any(
            report.get(key) is not False for key in CLAIMS):
        raise ValueError("terminal offline audit with no promoted hardware claims required")
    if bool(report["errors"]) != (report["status"] == "FAILED_RETAINED"):
        raise ValueError("audit status disagrees with retained failures")
    if report["status"] == study.STATUS and (len(report["cases"]) != len(study.EXPECTED) or
            {row["id"] for row in report["cases"]} != study.EXPECTED):
        raise ValueError("complete six-input audit required")


def recheck(attempt, report):
    terminal(report)
    if report["status"] != study.STATUS:
        raise ValueError("recheck requires the completed offline audit")
    if any(artifact.identity(Path(pin["path"])) != pin for pin in report["pins"]):
        raise ValueError("offline audit input, artifact or runner changed")
    review = report["source_review"]
    for pin in review["identities"]:
        if artifact.identity(Path(pin["path"])) != pin:
            raise ValueError("reviewed author source changed")
    observed = artifact.inspect(attempt / "artifact", Path(report["artifact"]["saved_timing"]["report"]["path"]))
    if json.loads(json.dumps(observed)) != report["artifact"]:
        raise ValueError("artifact metadata disagrees with audit")
    inputs = json.loads(Path(report["pins"][0]["path"]).read_text())
    study.validate_matrix(inputs)
    actual = []
    for case in inputs["cases"]:
        first = case["runs"][0]
        result = oracle.audit(Path(first["directory"]), first["analysis"])
        result.pop("pins")
        actual.append({"id": case["id"], **result})
    if actual != report["cases"]:
        raise ValueError("raw CSR/task binding audit disagrees with delivered observations")
    extraction = json.loads((attempt / "extract.resources.json").read_text())
    if extraction != report["extraction"] or extraction["exit_code"] or extraction["timed_out"]:
        raise ValueError("successful read-only extraction required")


def package(attempt, retained, output):
    report = json.loads((attempt / "results.json").read_text())
    recheck(attempt, report)
    files = []
    for directory in (attempt, *retained):
        if (directory / "results.json").exists():
            terminal(json.loads((directory / "results.json").read_text()))
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError("offline evidence cannot contain symlinks")
            if path.is_file():
                if path.suffix not in (".json", ".txt") or path.stat().st_size > 8 * 1024**2:
                    raise ValueError("only bounded metadata and logs belong in offline capsule")
                files.append((path, directory.name + "/" + path.relative_to(directory).as_posix()))
    root = Path(__file__).resolve().parents[4]
    for pin in report["pins"]:
        path = Path(pin["path"])
        if path.suffix == ".py" and path.is_relative_to(root):
            files.append((path, "runner/" + path.relative_to(root).as_posix()))
    for index, pin in enumerate(report["source_review"]["identities"]):
        path = Path(pin["path"])
        files.append((path, f"reviewed_author/{index}-{path.name}"))
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "original_r_offline_audit.tar.gz"
    index = {"status": CHECKPOINT, "files": seal(files, archive), "archive": archive.name,
             "sha256": sha256_file(archive), "audit_status": report["status"], "cases": report["cases"],
             "result_member": attempt.name + "/results.json", **dict.fromkeys(CLAIMS, False),
             "retained": [path.name for path in retained],
             "external_inputs": "large CSR/task captures, xclbin and tool binaries are hash-indexed, not archived"}
    atomic_write_json(output / "index.json", index)
    return verify(output)


def verify(output):
    index = json.loads((output / "index.json").read_text())
    if index["status"] != CHECKPOINT or any(index.get(key) is not False for key in CLAIMS):
        raise ValueError("invalid offline checkpoint claim boundary")
    archive = output / index["archive"]
    if archive.parent != output or sha256_file(archive) != index["sha256"]:
        raise ValueError("offline evidence archive changed")
    with tarfile.open(archive) as bundle:
        if bundle.getnames() != [row["path"] for row in index["files"]]:
            raise ValueError("offline archive membership changed")
        for row in index["files"]:
            name, info = PurePosixPath(row["path"]), bundle.getmember(row["path"])
            if name.is_absolute() or ".." in name.parts or not info.isfile() or info.size != row["bytes"] or \
                    hashlib.sha256(bundle.extractfile(info).read()).hexdigest() != row["sha256"]:
                raise ValueError("offline archived evidence changed")
        report = json.load(bundle.extractfile(index["result_member"]))
    terminal(report)
    if report["status"] != index["audit_status"] or report["cases"] != index["cases"]:
        raise ValueError("offline capsule index disagrees with raw report")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("attempt", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--retain", type=Path, action="append", default=[])
    args = parser.parse_args()
    package(args.attempt.resolve(), [path.resolve() for path in args.retain], args.output.resolve())
