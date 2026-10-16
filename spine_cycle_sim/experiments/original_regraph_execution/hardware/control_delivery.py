"""Seal raw offline-control observations and sources, never board claims."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from . import artifact, control_analysis as analysis

CLAIMS = ("board_programmed", "hardware_timing_measured", "publication_match")


def terminal(report):
    legacy = "board_abis" not in report
    expected = {"missing_lease", "unknown_binding", "symlink_input",
                "a4_board_abi" if legacy else "missing_lease_a4"}
    if (report["status"] != analysis.STATUS or report["errors"] or
            any(report.get(key) is not False for key in CLAIMS) or
            set(report["negative_controls"]) != expected or
            (not legacy and report["board_abis"] != ["original_example", "a4"])):
        raise ValueError("complete offline controls required without promoted hardware claims")
    analysis.matrix(report["rows"])


def package(root, attempt, audit, output, failures):
    report = json.loads((attempt / "results.json").read_text())
    terminal(report)
    if any(artifact.identity(Path(pin["path"])) != pin for pin in report["pins"]):
        raise ValueError("offline-control source or dependency changed")
    reference = json.loads((audit / "results.json").read_text())
    files = [(attempt / "results.json", "run/results.json"), (audit / "results.json", "reference/audit.json")]
    for row in report["rows"]:
        directory = Path(row["directory"])
        case = next(item for item in reference["cases"] if item["id"] == row["topology"] + "_" + row["graph"])
        observed = json.loads((directory / "result.json").read_text())
        if observed != row["observation"] or analysis.inspect(observed, directory, case) != row["analysis"]:
            raise ValueError("raw control outputs disagree with observations")
        files.append((directory / "result.json", "run/cases/" + directory.name + "/result.json"))
    for step in report["steps"]:
        prefix = attempt / "steps" / step["id"]
        raw = json.loads(prefix.with_suffix(".resources.json").read_text())
        if raw != {key: value for key, value in step.items() if key != "id"} or step["timed_out"]:
            raise ValueError("bounded step log differs")
        for suffix in (".resources.json", ".stdout.txt", ".stderr.txt"):
            files.append((prefix.with_suffix(suffix), "run/steps/" + step["id"] + suffix))
    paths = {Path(pin["path"]) for pin in report["pins"]}
    paths.add(Path(__file__).resolve())
    files += [(path, "source/" + path.relative_to(root).as_posix()) for path in sorted(paths)
              if path.is_relative_to(root) and path.suffix in (".py", ".hpp", ".cpp")]
    for failed in failures:
        result = json.loads((failed / "results.json").read_text())
        if result["status"] != "FAILED_RETAINED" or not result["errors"]:
            raise ValueError("failed-attempt record required")
        files.append((failed / "results.json", "attempts/" + failed.name + "/results.json"))
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "original_r_control.tar.gz"
    index = {"status": analysis.STATUS, "archive": archive.name, "files": seal(files, archive),
             "sha256": sha256_file(archive), "rows": len(report["rows"]),
             "indexed_not_archived": ["large captured graph/state files", "expected binary outputs",
                                      "compiled binaries", "external compiler, headers and libraries"],
             **dict.fromkeys(CLAIMS, False)}
    atomic_write_json(output / "index.json", index)
    return verify(output)


def verify(output):
    index = json.loads((output / "index.json").read_text())
    if (index["status"] != analysis.STATUS or index["rows"] != 48 or
            any(index.get(key) is not False for key in CLAIMS)):
        raise ValueError("invalid offline-control capsule boundary")
    archive = output / index["archive"]
    if archive.parent != output or sha256_file(archive) != index["sha256"]:
        raise ValueError("offline-control archive changed")
    with tarfile.open(archive) as bundle:
        if bundle.getnames() != [row["path"] for row in index["files"]]:
            raise ValueError("offline-control membership changed")
        for row in index["files"]:
            name, info = PurePosixPath(row["path"]), bundle.getmember(row["path"])
            if name.is_absolute() or ".." in name.parts or not info.isfile() or info.size != row["bytes"] or \
                    hashlib.sha256(bundle.extractfile(info).read()).hexdigest() != row["sha256"]:
                raise ValueError("offline-control member changed")
        terminal(json.load(bundle.extractfile("run/results.json")))
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("attempt", "audit", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--failed", type=Path, action="append", default=[])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[4]
    print(package(root, args.attempt.resolve(), args.audit.resolve(), args.output.resolve(),
                  [path.resolve() for path in args.failed])["status"], flush=True)
