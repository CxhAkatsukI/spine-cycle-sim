"""Recheck and seal measured board controls without promoting publication claims."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

from spine_cycle_sim.experiments.campaign_runtime import atomic_write_json, sha256_file
from spine_cycle_sim.experiments.original_regraph_execution.sssp_real_round.delivery import seal
from .. import artifact
from ..source_build import gates
from ..source_build.snapshot import unchanged
from . import analysis, preparation

EXCLUDED_CLAIMS = ("publication_match", "convergence_measured", "host_inclusive_measured")


def terminal(report, topology):
    if (report["status"] != analysis.pass_status(topology) or report["errors"] or
            report["configuration"] != topology or report["boundary"] != preparation.BOUNDARY or
            any(report.get(key) is not True for key in
                ("board_launch_attempted", "board_programmed", "hardware_timing_measured")) or
            any(report.get(key) is not False for key in EXCLUDED_CLAIMS)):
        raise ValueError("complete measured board control without promoted claims required")


def matrix(report):
    terminal(report, report["configuration"])
    if report["summaries"] != analysis.matrix(report["rows"]):
        raise ValueError("board summary differs from the complete eighteen-row matrix")
    expected = {f"r{row['repeat']}_{row['graph']}_{row['binding']}" for row in report["rows"]}
    attempts = report["attempts"]
    if (len(attempts) != 18 or {item["name"] for item in attempts} != expected or
            any(item["exit_code"] != 0 or item["timed_out"] is not False or
                item["lease_fd_forwarded"] is not True for item in attempts)):
        raise ValueError("all declared guarded host attempts must have completed")


def recheck(attempt):
    supervisor = json.loads((attempt / "results.json").read_text())
    job = json.loads((attempt / "manifest.json").read_text())
    board = json.loads((attempt / "board/results.json").read_text())
    preparation.validate_plan(job)
    terminal(supervisor, job["configuration"])
    matrix(board)
    if (board["configuration"] != job["configuration"] or
            supervisor["child"] != artifact.identity(attempt / "board/results.json") or
            supervisor["summaries"] != board["summaries"]):
        raise ValueError("supervisor and measured worker disagree")
    execution = supervisor["execution"]
    raw_execution = json.loads((attempt / "worker.resources.json").read_text())
    if (execution != raw_execution or execution["exit_code"] != 0 or
            execution["stop_reason"] != "process_exit" or execution["cleanup_snapshot_error"]):
        raise ValueError("successful bounded worker execution required")
    reviewed = supervisor["routed_admission"]
    # The timing report's parent is not assumed: the exact route manifest is pinned.
    manifests = [Path(pin["path"]) for pin in supervisor["pins"]
                 if Path(pin["path"]).name == "manifest.json" and
                 Path(pin["path"]).parent != attempt]
    route_manifests = [path for path in manifests if (path.parent / "link/reports").is_dir()]
    if len(route_manifests) != 1:
        raise ValueError("unique pinned source-route manifest required")
    route = route_manifests[0].parent
    inspected = gates.inspect_routed(attempt / "routed_admission/metadata", route / "link/reports",
                                    configuration=job["configuration"])
    # Topology rows are tuples in memory and arrays in the frozen JSON report.
    if json.loads(json.dumps(inspected)) != reviewed["analysis"] or reviewed["xclbin"] != job["xclbin"]:
        raise ValueError("freshly read routed topology, clock or strict timing differs")
    unchanged([*supervisor["pins"], *board["pins"], *reviewed["pins"]])
    for row in board["rows"]:
        case = next(item for item in job["cases"] if
                    (item["graph"], item["binding"]) == (row["graph"], row["binding"]))
        directory = attempt / "board/cases" / f"r{row['repeat']}_{row['graph']}_{row['binding']}"
        if Path(row["directory"]) != directory:
            raise ValueError("board row must name its declared raw case directory")
        observed = json.loads((directory / "result.json").read_text())
        if observed != row["observation"] or analysis.inspect(observed, directory, case,
                board["runtime"]["device"]["bdf"]) != row["analysis"]:
            raise ValueError("raw board output or independent oracle recheck differs")
    return supervisor, board


def small_files(directory, prefix):
    files = []
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("symlink in raw evidence")
        if path.is_file() and path.suffix in (".json", ".txt"):
            files.append((path, prefix + "/" + path.relative_to(directory).as_posix()))
    return files


def package(attempt, output, failures):
    supervisor, board = recheck(attempt)
    files = small_files(attempt, "run")
    for failed in failures:
        report = json.loads((failed / "results.json").read_text())
        if report["status"] != "FAILED_RETAINED" or not report["errors"]:
            raise ValueError("failed-attempt record required")
        files.extend(small_files(failed, "attempts/" + failed.name))
    output.mkdir(parents=True, exist_ok=False)
    archive = output / "board_controls.tar.gz"
    index = {"status": board["status"], "configuration": board["configuration"],
             "boundary": board["boundary"], "rows": len(board["rows"]), "summaries": board["summaries"],
             "archive": archive.name, "files": seal(files, archive), "sha256": sha256_file(archive),
             "source_report": artifact.identity(attempt / "results.json"),
             "external_pins": preparation.unique([*supervisor["pins"], *board["pins"]]),
             "indexed_not_archived": ["graph inputs and complete binary output replicas",
                                      "compiled hosts, XOs, xclbin and vendor tools",
                                      "frozen runner sources and runtime libraries"],
             "raw_outputs_rechecked_before_packaging": True, "hardware_timing_measured": True,
             **dict.fromkeys(EXCLUDED_CLAIMS, False)}
    atomic_write_json(output / "index.json", index)
    return verify(output)


def verify(output):
    index = json.loads((output / "index.json").read_text())
    if (index["status"] != analysis.pass_status(index["configuration"]) or index["rows"] != 18 or
            index["boundary"] != preparation.BOUNDARY or index["hardware_timing_measured"] is not True or
            index["raw_outputs_rechecked_before_packaging"] is not True or
            any(index.get(key) is not False for key in EXCLUDED_CLAIMS)):
        raise ValueError("invalid measured board capsule boundary")
    archive = output / index["archive"]
    if archive.parent != output or sha256_file(archive) != index["sha256"]:
        raise ValueError("board archive changed")
    with tarfile.open(archive) as bundle:
        if bundle.getnames() != [row["path"] for row in index["files"]]:
            raise ValueError("board archive membership changed")
        for row in index["files"]:
            name, info = PurePosixPath(row["path"]), bundle.getmember(row["path"])
            if (name.is_absolute() or ".." in name.parts or not info.isfile() or info.size != row["bytes"] or
                    hashlib.sha256(bundle.extractfile(info).read()).hexdigest() != row["sha256"]):
                raise ValueError("board archive member changed")
        report = json.load(bundle.extractfile("run/board/results.json"))
        supervisor = json.load(bundle.extractfile("run/results.json"))
        terminal(supervisor, index["configuration"])
        matrix(report)
        if (report["configuration"] != index["configuration"] or
                report["summaries"] != index["summaries"] or supervisor["summaries"] != index["summaries"]):
            raise ValueError("board archive and index disagree")
        for row in report["rows"]:
            path = f"run/board/cases/r{row['repeat']}_{row['graph']}_{row['binding']}/result.json"
            if json.load(bundle.extractfile(path)) != row["observation"]:
                raise ValueError("archived raw observation differs")
    return index


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("attempt", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--failed", type=Path, action="append", default=[])
    args = parser.parse_args()
    print(package(args.attempt.resolve(), args.output.resolve(),
                  [path.resolve() for path in args.failed])["status"], flush=True)
